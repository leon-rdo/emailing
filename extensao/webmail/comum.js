// Núcleo da extensão dentro do webmail (mundo isolado dos content scripts).
//
// O que é comum ao Titan e à Hostinger mora aqui; o que é de cada um (onde
// fica o botão, como ler o rascunho, como descartá-lo) mora no adaptador, que
// se apresenta com `EmailingExt.registrar({...})`.
//
// O caminho de uma mensagem:
//   1. clique humano no botão "Emailing" (ou no Enviar nativo, no modo alias do Titan);
//   2. a ponte do mundo da página devolve o rascunho (`*-pagina.js`);
//   3. o adaptador o converte numa "carga" (campos prontos para o formulário);
//   4. o service worker abre a tela de redação do Emailing e entrega a carga;
//   5. o envio é o da própria tela, depois de conferida a prévia.
//
// Nada aqui envia e-mail nem fala com o servidor do Emailing: não existe
// requisição da extensão para lá. Ver docs/decisoes.md#extensao.
(function () {
	"use strict";

	var ATRIBUTO_ID = "data-emailing-id";
	var CLASSE_BOTAO = "emailing-ext-botao";
	var FATIA = 3 * 1024 * 1024; // bytes por mensagem ao entregar um anexo
	var MAX_CAPTURADOS = 120;

	var adaptador = null;
	var capturados = []; // File, do mais antigo ao mais novo
	var arquivosPorCompositor = new Map(); // id → (File | null)[]
	var ocupados = new WeakSet();

	// ----------------------------------------------------------------- utilidades

	function analisar(html) {
		// DOMParser devolve um documento inerte: nada carrega, nada executa.
		return new DOMParser().parseFromString("<!DOCTYPE html><body>" + (html || ""), "text/html");
	}

	function escapar(texto) {
		return String(texto)
			.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
	}

	function endereco(pessoa) {
		var email = String((pessoa && pessoa.email) || "").trim();
		var nome = String((pessoa && pessoa.nome) || "").trim();
		if (!email) return "";
		if (!nome || nome.toLowerCase() === email.toLowerCase()) return email;
		return '"' + nome.replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '" <' + email + ">";
	}

	function enderecos(lista) {
		return (lista || []).map(endereco).filter(Boolean).join(", ");
	}

	function idMensagem(bruto) {
		var id = String(bruto || "").trim();
		if (!id) return "";
		return id.charAt(0) === "<" ? id : "<" + id + ">";
	}

	// Tira do fim do corpo os blocos vazios (`<div><br></div>`) que os editores
	// deixam antes da assinatura: sem a assinatura do webmail, sobraria um vão
	// antes da do alias.
	function apararFim(corpo) {
		var ultimo = corpo.lastChild;
		while (ultimo) {
			var vazio = ultimo.nodeType === 3
				? !ultimo.textContent.trim()
				: ultimo.nodeType === 1
					&& !ultimo.textContent.trim()
					&& !ultimo.querySelector("img, table, hr, blockquote")
					&& !/^(IMG|TABLE|HR|BLOCKQUOTE)$/.test(ultimo.tagName);
			if (!vazio) break;
			var anterior = ultimo.previousSibling;
			ultimo.remove();
			ultimo = anterior;
		}
	}

	// Imagem colada no editor do webmail mora no servidor dele ou num `blob:`
	// desta aba: o sanitizador do Emailing só aceita http(s) e cid.
	function imagensQueNaoViajam(corpo) {
		var total = 0;
		corpo.querySelectorAll("img").forEach(function (img) {
			var src = (img.getAttribute("src") || "").trim().toLowerCase();
			if (!/^https?:/.test(src)) total++;
		});
		return total;
	}

	function textoParaHtml(texto) {
		return escapar(String(texto).replace(/\r\n?/g, "\n").trim()).replace(/\n/g, "<br>");
	}

	// ------------------------------------------------------------------- avisos

	function caixaDeAvisos() {
		var caixa = document.querySelector(".emailing-ext-avisos");
		if (!caixa) {
			caixa = document.createElement("div");
			caixa.className = "emailing-ext-avisos";
			caixa.setAttribute("role", "status");
			caixa.setAttribute("aria-live", "polite");
			document.documentElement.appendChild(caixa);
		}
		return caixa;
	}

	function avisar(texto, tipo) {
		var aviso = document.createElement("div");
		aviso.className = "emailing-ext-aviso emailing-ext-aviso--" + (tipo || "info");
		aviso.textContent = texto;
		caixaDeAvisos().appendChild(aviso);
		setTimeout(function () {
			aviso.classList.add("emailing-ext-aviso--some");
			setTimeout(function () { aviso.remove(); }, 300);
		}, tipo === "erro" ? 9000 : 6000);
	}

	// ---------------------------------------------------- arquivos que o usuário anexa

	// O Titan sobe o anexo na hora e guarda só os metadados; para levar o
	// arquivo ao Emailing é preciso tê-lo guardado no momento em que foi
	// escolhido, arrastado ou colado. Guardar um `File` não copia os bytes.
	function guardar(lista) {
		for (var i = 0; lista && i < lista.length; i++) {
			if (lista[i] instanceof File) capturados.push(lista[i]);
		}
		if (capturados.length > MAX_CAPTURADOS) capturados.splice(0, capturados.length - MAX_CAPTURADOS);
	}

	document.addEventListener("change", function (evento) {
		var alvo = evento.target;
		if (alvo instanceof HTMLInputElement && alvo.type === "file") guardar(alvo.files);
	}, true);
	document.addEventListener("drop", function (evento) {
		if (evento.dataTransfer) guardar(evento.dataTransfer.files);
	}, true);
	document.addEventListener("paste", function (evento) {
		if (evento.clipboardData) guardar(evento.clipboardData.files);
	}, true);

	function capturado(nome, tamanho) {
		for (var i = capturados.length - 1; i >= 0; i--) {
			if (capturados[i].name === nome && capturados[i].size === tamanho) return capturados[i];
		}
		return null;
	}

	// -------------------------------------------------------- ponte com a página

	function lerDaPagina(compositor) {
		var marca = crypto.randomUUID();
		var entrada = document.createElement("input");
		entrada.type = "file";
		entrada.multiple = true;
		entrada.hidden = true;
		entrada.setAttribute("data-emailing-arquivos", marca);
		document.documentElement.appendChild(entrada);
		compositor.setAttribute("data-emailing-ponte", marca);

		var resposta = null;
		function ouvir(evento) {
			try {
				var lido = JSON.parse(evento.detail);
				if (lido && lido.marca === marca) resposta = lido;
			} catch (_erro) { /* não era para nós */ }
		}
		// A ponte responde dentro do próprio dispatchEvent: o par é síncrono.
		document.addEventListener("emailing:lido", ouvir);
		document.dispatchEvent(new CustomEvent("emailing:ler", { detail: marca }));
		document.removeEventListener("emailing:lido", ouvir);

		compositor.removeAttribute("data-emailing-ponte");
		var arquivos = Array.prototype.slice.call(entrada.files || []);
		entrada.remove();

		if (!resposta) {
			throw new Error("A extensão não conseguiu ler esta janela. Recarregue a página do webmail.");
		}
		if (!resposta.ok) throw new Error(resposta.erro || "Não consegui ler o rascunho.");
		return { dados: resposta.dados, arquivos: arquivos };
	}

	// ------------------------------------------------------------------- envio

	function idDe(compositor) {
		var id = compositor.getAttribute(ATRIBUTO_ID);
		if (!id) {
			id = crypto.randomUUID();
			compositor.setAttribute(ATRIBUTO_ID, id);
		}
		return id;
	}

	function compositorDe(id) {
		return document.querySelector("[" + ATRIBUTO_ID + '="' + CSS.escape(id) + '"]');
	}

	var ERROS = {
		"sem-configuracao": "Informe o endereço do seu Emailing nas opções da extensão (a página foi aberta).",
		"sem-permissao": "A extensão perdeu a permissão para o endereço do Emailing. Salve as opções de novo.",
		"origem-recusada": "Esta página não é um webmail que a extensão conhece.",
	};

	function abrir(compositor) {
		var lido = lerDaPagina(compositor);
		var parcial = adaptador.montar(lido.dados, compositor, lido.arquivos);
		var avisos = (parcial.avisos || []).slice();

		var anexos = parcial.anexos || [];
		var perdidos = anexos.filter(function (a) { return !a.arquivo; }).map(function (a) { return a.nome; });
		if (perdidos.length) {
			avisos.push(
				(perdidos.length === 1 ? "O anexo " : "Os anexos ") + perdidos.join(", ")
				+ (perdidos.length === 1 ? " não acompanhou" : " não acompanharam")
				+ " a mensagem: anexe de novo aqui."
			);
		}
		if (parcial.imagensPerdidas) {
			avisos.push(
				parcial.imagensPerdidas === 1
					? "Uma imagem colada no corpo não acompanha a mensagem (ela mora no webmail)."
					: parcial.imagensPerdidas + " imagens coladas no corpo não acompanham a mensagem (elas moram no webmail)."
			);
		}

		var id = idDe(compositor);
		arquivosPorCompositor.set(id, anexos.map(function (a) { return a.arquivo || null; }));

		return {
			webmail: adaptador.nome,
			rotulo: adaptador.rotulo,
			idCompositor: id,
			caixa: parcial.caixa || "",
			de: parcial.de || "",
			para: parcial.para || "",
			cc: parcial.cc || "",
			cco: parcial.cco || "",
			assunto: parcial.assunto || "",
			html: parcial.html || "",
			emRespostaA: idMensagem(parcial.emRespostaA),
			referencias: (parcial.referencias || []).map(idMensagem).filter(Boolean).join(" "),
			anexos: anexos.map(function (a) {
				return { nome: a.nome, tamanho: a.tamanho, tipo: a.tipo || "", disponivel: !!a.arquivo };
			}),
			avisos: avisos,
		};
	}

	function iniciarEnvio(compositor) {
		if (!adaptador || ocupados.has(compositor)) return;
		ocupados.add(compositor);
		// Um instante para o webmail assentar o que o clique acabou de tirar de
		// foco (o destinatário digitado vira "ficha" no blur).
		setTimeout(function () {
			var carga;
			try {
				carga = abrir(compositor);
			} catch (erro) {
				ocupados.delete(compositor);
				avisar(String((erro && erro.message) || erro), "erro");
				return;
			}
			chrome.runtime.sendMessage({ tipo: "abrir-confirmacao", carga: carga }).then(function (resposta) {
				ocupados.delete(compositor);
				if (resposta && resposta.ok) {
					avisar("Confira a prévia e envie na janela do Emailing.", "info");
				} else {
					var codigo = resposta && resposta.erro;
					avisar(ERROS[codigo] || codigo || "Não consegui abrir o Emailing.", "erro");
				}
			}, function () {
				ocupados.delete(compositor);
				avisar("A extensão foi atualizada. Recarregue a página do webmail e tente de novo.", "erro");
			});
		}, 80);
	}

	// ------------------------------------------------- o que volta da confirmação

	function fatiaEmBase64(arquivo, inicio) {
		var fim = Math.min(arquivo.size, inicio + FATIA);
		return arquivo.slice(inicio, fim).arrayBuffer().then(function (buffer) {
			var bytes = new Uint8Array(buffer);
			var partes = [];
			for (var i = 0; i < bytes.length; i += 0x8000) {
				partes.push(String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000)));
			}
			return { ok: true, b64: btoa(partes.join("")), fim: fim, total: arquivo.size };
		});
	}

	var TEXTOS = {
		enviado: "Enviado pelo Emailing.",
		agendado: "Agendado no Emailing.",
		rascunho: "Guardado como rascunho no Emailing. O rascunho daqui continua onde estava.",
		falhou: "O Emailing não conseguiu enviar. O rascunho continua aqui.",
	};

	function concluir(mensagem) {
		var compositor = compositorDe(mensagem.idCompositor);
		var resultado = mensagem.resultado;
		if (resultado === "fechada") return; // fechou sem enviar: nada mudou aqui
		if (resultado !== "enviado" && resultado !== "agendado") {
			avisar(TEXTOS[resultado] || resultado, resultado === "falhou" ? "erro" : "info");
			return;
		}
		arquivosPorCompositor.delete(mensagem.idCompositor);
		var descarte = compositor ? adaptador.descartar(compositor) : Promise.resolve(false);
		Promise.resolve(descarte).then(function (descartou) {
			avisar(
				TEXTOS[resultado] + (descartou
					? " O rascunho daqui foi descartado."
					: " Descarte o rascunho que ficou aqui."),
				"sucesso"
			);
		});
	}

	chrome.runtime.onMessage.addListener(function (mensagem, _remetente, responder) {
		if (!mensagem || !adaptador) return;
		if (mensagem.tipo === "fornecer-anexo") {
			var lista = arquivosPorCompositor.get(mensagem.idCompositor) || [];
			var arquivo = lista[mensagem.indice];
			if (!arquivo) {
				responder({ ok: false, erro: "sem-arquivo" });
				return;
			}
			fatiaEmBase64(arquivo, Number(mensagem.inicio) || 0).then(responder, function () {
				responder({ ok: false, erro: "leitura" });
			});
			return true; // resposta assíncrona
		}
		if (mensagem.tipo === "concluido") concluir(mensagem);
	});

	// ----------------------------------------------------------- botão e varredura

	var ICONE = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">'
		+ '<path d="M3 7l9 6 9-6M4 6h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1z" '
		+ 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/></svg>';

	function garantirBotao(compositor) {
		if (compositor.querySelector("." + CLASSE_BOTAO)) return;
		var ancora = adaptador.ancora(compositor);
		if (!ancora || !ancora.referencia) return;
		var botao = document.createElement("button");
		botao.type = "button";
		botao.className = CLASSE_BOTAO;
		botao.title = "Conferir e enviar por um alias, pelo Emailing";
		botao.innerHTML = ICONE + "<span>Emailing</span>";
		botao.addEventListener("click", function (evento) {
			evento.preventDefault();
			evento.stopPropagation();
			// Só gente clica aqui: um clique fabricado pela página é ignorado.
			if (evento.isTrusted) iniciarEnvio(compositor);
		});
		ancora.referencia.insertAdjacentElement(ancora.posicao || "afterend", botao);
	}

	var agendada = false;
	function varrer() {
		agendada = false;
		if (!adaptador) return;
		document.querySelectorAll(adaptador.seletorCompositor).forEach(function (compositor) {
			try {
				garantirBotao(compositor);
				if (adaptador.aoVarrer) adaptador.aoVarrer(compositor);
			} catch (_erro) { /* um compositor torto não derruba os outros */ }
		});
	}

	function agendarVarredura() {
		if (agendada) return;
		agendada = true;
		setTimeout(varrer, 150);
	}

	function registrar(novo) {
		adaptador = novo;
		if (adaptador.aoIniciar) adaptador.aoIniciar();
		new MutationObserver(agendarVarredura).observe(document.documentElement, {
			childList: true,
			subtree: true,
		});
		agendarVarredura();
	}

	globalThis.EmailingExt = {
		registrar: registrar,
		iniciarEnvio: iniciarEnvio,
		avisar: avisar,
		analisar: analisar,
		escapar: escapar,
		enderecos: enderecos,
		apararFim: apararFim,
		imagensQueNaoViajam: imagensQueNaoViajam,
		textoParaHtml: textoParaHtml,
		capturado: capturado,
	};
})();
