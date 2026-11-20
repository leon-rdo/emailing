// Roda nas páginas do Emailing, mas só age na janela de confirmação que a
// extensão abriu: pergunta ao service worker se há um rascunho do webmail
// esperando nesta aba e, se não houver, sai sem tocar em nada.
//
// Havendo, **preenche o formulário de redação como uma pessoa faria** — pelos
// campos e pelos eventos que a própria tela já escuta. Não há requisição daqui
// para o servidor: a prévia, a trava de `hash_previa` e o envio continuam
// sendo os da tela, e o clique em Enviar é de quem está olhando.
//
// Três coisas que parecem estranhas (ver docs/decisoes.md#extensao):
//   - o corpo entra pelo "Editar HTML bruto", não pelo Trix: o Trix reescreve
//     o HTML para o que ele sabe representar e achataria a formatação que veio
//     do webmail. O sanitizador do servidor continua valendo;
//   - a citação da mensagem respondida vai dentro do corpo, e não no campo
//     `citacao_html`, porque aquele campo não passa pelo sanitizador;
//   - o Trix reescreve o campo `corpo` a cada carga da página, então o corpo é
//     reaplicado depois de cada volta do servidor (anexo novo, erro de campo).
(function () {
	"use strict";

	const PREFIXO = "emailing-ext:";
	const ACOES = ["enviar", "agendar", "salvar_rascunho"];

	function pedir(mensagem) {
		return chrome.runtime.sendMessage(mensagem).catch(() => null);
	}

	// ------------------------------------------------------------------ faixas

	function criarFaixa(titulo, texto, tipo) {
		const faixa = document.createElement("div");
		faixa.className = "emailing-ext-faixa" + (tipo ? " emailing-ext-faixa--" + tipo : "");
		faixa.setAttribute("role", "status");
		const forte = document.createElement("strong");
		forte.textContent = titulo;
		faixa.append(forte, " ", texto);
		return faixa;
	}

	// Para as páginas sem o formulário (login, registro do envio).
	function faixaSolta(titulo, texto, tipo) {
		document.querySelectorAll(".emailing-ext-faixa--solta").forEach((velha) => velha.remove());
		const faixa = criarFaixa(titulo, texto, tipo);
		faixa.classList.add("emailing-ext-faixa--solta");
		document.body.appendChild(faixa);
		return faixa;
	}

	// ------------------------------------------------------------------- campos

	function definir(form, nome, valor) {
		const campo = form.querySelector('[name="' + nome + '"]');
		if (!campo) return;
		campo.value = valor || "";
		campo.dispatchEvent(new Event("input", { bubbles: true }));
	}

	function escolherAlias(form, carga, avisos) {
		const seletor = form.querySelector('select[name="alias"]');
		if (!seletor) return;
		// O texto de cada opção é "slug <endereço>" (Alias.__str__).
		const opcoes = Array.from(seletor.options).map((opcao) => ({
			valor: opcao.value,
			endereco: ((/<([^<>]+)>\s*$/.exec(opcao.textContent) || [])[1] || "").toLowerCase(),
		}));
		const pedido = (carga.de || "").toLowerCase();
		const caixa = (carga.caixa || "").toLowerCase();
		let escolhida = opcoes.find((opcao) => opcao.endereco && opcao.endereco === pedido);
		if (!escolhida) {
			// Sem alias com esse endereço: ao menos um da mesma caixa (mesmo domínio).
			const dominio = (caixa || pedido).split("@")[1];
			if (dominio) escolhida = opcoes.find((opcao) => opcao.endereco.endsWith("@" + dominio));
			avisos.push(
				pedido && pedido !== caixa
					? "O endereço " + carga.de + " não é um alias cadastrado no Emailing: escolha o remetente em “De”."
					: "Confira o remetente em “De”: o webmail estava com o endereço da caixa, não com um alias."
			);
		}
		if (escolhida) {
			seletor.value = escolhida.valor;
			seletor.dispatchEvent(new Event("change", { bubbles: true }));
		}
	}

	function preencherCampos(form, carga, avisos) {
		escolherAlias(form, carga, avisos);
		for (const nome of ["cc", "cco"]) {
			const mostrar = form.querySelector('[data-mostrar="' + nome + '"]');
			if (carga[nome] && mostrar && !mostrar.hidden) mostrar.click();
		}
		definir(form, "para", carga.para);
		definir(form, "cc", carga.cc);
		definir(form, "cco", carga.cco);
		definir(form, "assunto", carga.assunto);
		definir(form, "in_reply_to", carga.emRespostaA);
		definir(form, "referencias", carga.referencias);
	}

	// -------------------------------------------------------------------- corpo

	// O Trix regrava o campo oculto `corpo` quando inicializa. Mexer antes disso
	// é perder o que se escreveu; o `editor.js` marca a barra dele no evento de
	// inicialização, e essa marca é visível daqui.
	function trixPronto() {
		const trix = document.getElementById("editor-trix");
		if (!trix || document.querySelector("trix-toolbar[data-personalizada]")) return Promise.resolve();
		return new Promise((resolver) => {
			trix.addEventListener("trix-initialize", () => setTimeout(resolver, 0), { once: true });
			setTimeout(resolver, 4000);
		});
	}

	async function aplicarCorpo(corpo) {
		if (!corpo || corpo.bruto === false) return; // a pessoa voltou para o editor: vale o dele
		await trixPronto();
		const alternar = document.getElementById("alternar-html-bruto");
		const bruto = document.getElementById("editor-html-bruto");
		if (!alternar || !bruto) return;
		if (!alternar.checked) {
			alternar.checked = true;
			alternar.dispatchEvent(new Event("change", { bubbles: true }));
		}
		bruto.value = corpo.html || "";
		bruto.dispatchEvent(new Event("input", { bubbles: true }));
	}

	// ------------------------------------------------------------------- anexos

	async function baixar(indice, meta) {
		const partes = [];
		let inicio = 0;
		for (;;) {
			const fatia = await pedir({ tipo: "pedir-anexo", indice, inicio });
			if (!fatia || !fatia.ok) throw new Error("anexo");
			const binario = atob(fatia.b64);
			const bytes = new Uint8Array(binario.length);
			for (let i = 0; i < binario.length; i++) bytes[i] = binario.charCodeAt(i);
			partes.push(bytes);
			if (fatia.fim >= fatia.total || fatia.fim <= inicio) break;
			inicio = fatia.fim;
		}
		return new File(partes, meta.nome, { type: meta.tipo || "application/octet-stream" });
	}

	async function buscarAnexos(carga, avisos) {
		const arquivos = [];
		const perdidos = [];
		for (let i = 0; i < (carga.anexos || []).length; i++) {
			const meta = carga.anexos[i];
			if (!meta.disponivel) continue;
			try {
				arquivos.push(await baixar(i, meta));
			} catch (_erro) {
				perdidos.push(meta.nome);
			}
		}
		if (perdidos.length) {
			avisos.push("Não consegui trazer do webmail: " + perdidos.join(", ") + ". Anexe de novo aqui.");
		}
		return arquivos;
	}

	// ----------------------------------------------------------------- desfecho

	function avaliar(acao) {
		const caminho = location.pathname;
		const sucesso = document.querySelector(".avisos .aviso.success");
		const falha = document.querySelector(".avisos .aviso.error");
		if (acao === "enviar" && /\/historico\/\d+\/?$/.test(caminho)) {
			if (sucesso) return "enviado";
			if (falha) return "falhou";
		}
		if (acao === "agendar" && /\/agendados\/?$/.test(caminho) && sucesso) return "agendado";
		if (acao === "salvar_rascunho" && /\/mensagens\/\d+\/editar\/?$/.test(caminho) && sucesso) return "rascunho";
		return null;
	}

	// --------------------------------------------------------------- o roteiro

	async function iniciar(confirmacao) {
		const carga = confirmacao.carga;
		const chave = PREFIXO + confirmacao.id;

		// O que precisa atravessar as recargas desta aba: em que ponto estamos, o
		// corpo como estava no último envio do formulário, e qual botão foi clicado.
		let memoria = { etapa: "nova", corpo: null, acao: "", editando: "" };
		try {
			memoria = Object.assign(memoria, JSON.parse(sessionStorage.getItem(chave) || "{}"));
		} catch (_erro) { /* memória ilegível: começa do zero */ }
		const gravar = () => sessionStorage.setItem(chave, JSON.stringify(memoria));

		const acao = memoria.acao;
		if (acao) {
			memoria.acao = "";
			gravar();
		}
		const desfecho = acao ? avaliar(acao) : null;

		if (desfecho === "enviado" || desfecho === "agendado") {
			sessionStorage.removeItem(chave);
			await pedir({ tipo: "resultado", resultado: desfecho });
			faixaSolta(
				desfecho === "enviado" ? "Enviado." : "Agendado.",
				"Esta janela fecha sozinha; o webmail cuida do rascunho que ficou lá.",
				"sucesso"
			);
			setTimeout(() => pedir({ tipo: "fechar-janela" }), 2200);
			return;
		}
		if (desfecho === "falhou") {
			await pedir({ tipo: "resultado", resultado: "falhou" });
			faixaSolta("O envio falhou.", "O rascunho continua no webmail, do jeito que estava.", "erro");
			return;
		}
		if (desfecho === "rascunho") {
			memoria.editando = location.pathname;
			gravar();
			await pedir({ tipo: "resultado", resultado: "rascunho" });
		}

		const form = document.querySelector("dialog.escrever-modal form.form-redacao");
		if (!form) {
			if (document.querySelector('input[name="username"], input[name="otp_token"]')) {
				faixaSolta("Entre para continuar.", "A mensagem que veio do webmail está esperando.");
			}
			return;
		}

		const modal = form.closest("dialog");
		const aposPost = modal.dataset.sujo === "1";
		const editando = /\/mensagens\/\d+\/editar\/?$/.test(location.pathname);
		if (editando && location.pathname !== memoria.editando) return; // outra mensagem: não é a nossa
		// Tela de redação em branco (primeira vez, ou voltou a ela depois de sair):
		// começa do começo.
		if (!aposPost && !editando) memoria.etapa = "nova";

		const avisos = (carga.avisos || []).slice();
		const faixa = criarFaixa(
			"Veio do " + (carga.rotulo || "webmail") + (carga.caixa ? " (" + carga.caixa + ")." : "."),
			"Confira a prévia e envie por aqui: o rascunho de lá é descartado quando a mensagem sair."
		);
		const coluna = modal.querySelector(".coluna-escrita") || form.parentNode;
		coluna.insertBefore(faixa, coluna.firstChild);

		if (memoria.etapa === "nova") {
			preencherCampos(form, carga, avisos);
			memoria.corpo = { html: carga.html, bruto: true };
			const pendentes = (carga.anexos || []).filter((meta) => meta.disponivel).length;
			if (pendentes) {
				faixa.append(" Trazendo " + (pendentes === 1 ? "o anexo" : "os " + pendentes + " anexos") + "…");
				const arquivos = await buscarAnexos(carga, avisos);
				const entrada = form.querySelector('input[type="file"][name="novo_anexo"]');
				if (arquivos.length && entrada) {
					const bandeja = new DataTransfer();
					arquivos.forEach((arquivo) => bandeja.items.add(arquivo));
					memoria.etapa = "anexando";
					memoria.avisos = avisos;
					gravar();
					// A tela sobe o anexo num POST de prévia e recarrega; o corpo entra
					// na volta (antes, o Trix o reescreveria ao inicializar).
					entrada.files = bandeja.files;
					entrada.dispatchEvent(new Event("change", { bubbles: true }));
					return;
				}
			}
			memoria.etapa = "pronta";
			memoria.avisos = avisos;
			gravar();
		} else if (memoria.etapa === "anexando") {
			memoria.etapa = "pronta";
			gravar();
		}

		const lista = memoria.avisos || avisos;
		if (lista.length) {
			const ul = document.createElement("ul");
			lista.forEach((texto) => {
				const li = document.createElement("li");
				li.textContent = texto;
				ul.appendChild(li);
			});
			faixa.appendChild(ul);
		}
		if (carga.emRespostaA && !form.querySelector(".nota-resposta")) {
			const nota = document.createElement("p");
			nota.className = "nota nota-resposta";
			const codigo = document.createElement("code");
			codigo.textContent = carga.emRespostaA;
			nota.append("Em resposta à mensagem ", codigo, ".");
			const primeira = form.querySelector(".escrita .linha-campo");
			if (primeira) primeira.parentNode.insertBefore(nota, primeira);
		}

		await aplicarCorpo(memoria.corpo);

		// Antes de cada ida ao servidor: guarda o corpo como está e o botão clicado.
		form.addEventListener("submit", (evento) => {
			const botao = evento.submitter;
			const oculto = document.getElementById("id_corpo");
			const alternar = document.getElementById("alternar-html-bruto");
			memoria.acao = botao && botao.name === "acao" && ACOES.includes(botao.value) ? botao.value : "";
			memoria.corpo = { html: oculto ? oculto.value : "", bruto: !!(alternar && alternar.checked) };
			gravar();
		}, true);
	}

	pedir({ tipo: "carga-da-aba" }).then((confirmacao) => {
		if (confirmacao && confirmacao.carga) iniciar(confirmacao);
	});
})();
