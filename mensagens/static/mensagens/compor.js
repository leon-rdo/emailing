// Modal de escrita: prévia sempre à vista e sempre atual, e o resto do que a
// tela precisa para escrever sem sair do lugar.
//
// A prévia nunca reimplementa a limpeza de HTML: chama /previa-ajax/, que usa o
// mesmo caminho do envio (ver mensagens/views.py:previa_ajax). O que este
// arquivo decide é só quando mostrar, e quando liberar os botões que gravam.
(function () {
	"use strict";

	var modal = document.querySelector("dialog.escrever-modal");
	var form = modal && modal.querySelector("form.form-redacao");
	if (!form) return;

	var campo = function (nome) { return form.querySelector('[name="' + nome + '"]'); };
	var via = modal.querySelector(".via");
	var quadro = via.querySelector(".previa-quadro");
	var textoPre = quadro.querySelector(".previa-texto");
	var iframe = quadro.querySelector(".previa-iframe");
	var errosBox = via.querySelector(".via-erros");
	var situacao = form.querySelector(".situacao");
	var textoSituacao = situacao.querySelector(".texto-situacao");
	var hashInput = campo("hash_previa");
	var botoesEnvio = form.querySelectorAll(".botao-enviar");
	var urlPrevia = modal.dataset.urlPrevia;
	var formato = "html";

	// --- abre como modal de verdade: foco preso e Esc de graça. Sem JS o
	// <dialog open> do HTML já aparece, só que sem prender o foco.
	if (typeof modal.showModal === "function") {
		modal.close();
		modal.showModal();
	}

	// Os avisos ficam acima de tudo na página, mas o <dialog> modal vai para a
	// camada de topo e os cobriria: levá-los para dentro do modal os mantém visíveis.
	var avisos = document.querySelector(".avisos");
	if (avisos) modal.appendChild(avisos);

	// --- fechar sem perder o que foi escrito
	var sujo = modal.dataset.sujo === "1";
	var pronto = false;
	setTimeout(function () { pronto = true; }, 400);
	function marcarSujo() { if (pronto) sujo = true; }

	function pedirFechar() {
		if (sujo && !window.confirm("Fechar sem salvar? O que você escreveu aqui será perdido.")) return;
		window.location.href = modal.dataset.urlFechar;
	}
	modal.addEventListener("cancel", function (evento) {
		evento.preventDefault();
		pedirFechar();
	});
	modal.querySelector(".fechar-modal").addEventListener("click", function (evento) {
		evento.preventDefault();
		pedirFechar();
	});
	// Salvar ou enviar é sair de propósito: não perguntar.
	form.addEventListener("submit", function () { sujo = false; });

	// --- foco: no primeiro campo que ainda falta
	var assunto = campo("assunto");
	var para = campo("para");
	// No toque, focar sozinho abriria o teclado por cima da tela antes de ela ser vista.
	var trixEl = document.getElementById("editor-trix");
	if (window.matchMedia("(pointer: coarse)").matches) {
		modal.focus({ preventScroll: true }); // o foco inicial iria para o botão de fechar
	} else {
		if (para && !para.value) para.focus();
		else if (assunto && !assunto.value) assunto.focus();
		else if (trixEl) {
			// mensagem já preenchida (editar): direto no texto, assim que o Trix existir
			if (trixEl.editor) trixEl.focus();
			else trixEl.addEventListener("trix-initialize", function () { trixEl.focus(); }, { once: true });
		}
	}

	// --- o assunto vira cartaz e condensa ao encher
	var bloco = assunto.parentNode;
	function ajustarAssunto() {
		var n = assunto.value.length;
		var base = parseFloat(getComputedStyle(bloco).getPropertyValue("--assunto-base")) || 54;
		var largura = n <= 12 ? 100 : Math.max(75, 100 - (n - 12) * 1.8);
		var tamanho = n <= 26 ? base : Math.max(base * 0.42, base * 26 / n);
		bloco.style.setProperty("--assunto-larg", largura + "%");
		bloco.style.setProperty("--assunto-tam", tamanho.toFixed(1) + "px");
	}
	assunto.addEventListener("input", ajustarAssunto);
	ajustarAssunto();

	// --- Cc e Cco só aparecem quando pedidos (ou quando já têm valor)
	form.querySelectorAll("[data-mostrar]").forEach(function (botao) {
		botao.addEventListener("click", function () {
			var linha = form.querySelector('[data-linha="' + botao.dataset.mostrar + '"]');
			linha.hidden = false;
			botao.hidden = true;
			linha.querySelector("input").focus();
		});
	});

	// --- prévia
	var sequencia = 0;
	var espera = null;

	// A prévia é tolerante com o destinatário (decisão antiga: ela é do conteúdo, não do
	// envelope), mas enviar, agendar e salvar alterações exigem um. O servidor recusa de
	// qualquer jeito; avisar antes poupa a ida e volta.
	var ultimoEstado = ["aguardando", ""];
	function temDestinatario() { return /\S+@\S+/.test(para.value); }

	function definirEstado(estado, texto) {
		ultimoEstado = [estado, texto];
		var semDestino = estado === "atual" && !temDestinatario();
		via.dataset.estado = estado;
		situacao.dataset.estado = semDestino ? "aguardando" : estado;
		textoSituacao.textContent = semDestino ? "Informe o destinatário para enviar" : texto;
		var liberado = estado === "atual" && !semDestino;
		botoesEnvio.forEach(function (botao) { botao.disabled = !liberado; });
	}
	para.addEventListener("input", function () { definirEstado(ultimoEstado[0], ultimoEstado[1]); });

	function mostrarErros(lista) {
		errosBox.hidden = !lista || !lista.length;
		errosBox.replaceChildren();
		if (!lista || !lista.length) return;
		var ul = document.createElement("ul");
		lista.forEach(function (texto) {
			var li = document.createElement("li");
			li.textContent = texto;
			ul.appendChild(li);
		});
		errosBox.appendChild(ul);
	}

	function aplicarFormato() {
		iframe.hidden = formato !== "html";
		textoPre.hidden = formato !== "texto";
	}

	// Troca o iframe só depois de o novo carregar: atualizar `srcdoc` no mesmo
	// elemento pisca em branco a cada pausa de digitação.
	function mostrarHtml(html) {
		var novo = document.createElement("iframe");
		novo.className = "previa-iframe";
		novo.title = iframe.title;
		novo.setAttribute("sandbox", "");
		novo.hidden = true;
		novo.addEventListener("load", function () {
			iframe.remove();
			iframe = novo;
			aplicarFormato();
		}, { once: true });
		novo.srcdoc = html;
		quadro.insertBefore(novo, quadro.firstChild);
	}

	function atualizarAgora() {
		var minhaVez = ++sequencia;
		definirEstado("atualizando", "Atualizando a prévia…");
		var dados = new FormData(form);
		dados.delete("novo_anexo"); // arquivo não vai a cada pausa; sobe no envio
		fetch(urlPrevia, { method: "POST", body: dados, credentials: "same-origin" })
			.then(function (resposta) {
				if (!resposta.ok) throw new Error("http " + resposta.status);
				return resposta.json();
			})
			.then(function (resultado) {
				if (minhaVez !== sequencia) return; // resposta atrasada: descartada
				if (!resultado.ok) {
					mostrarErros(resultado.erros);
					definirEstado("erro", "Corrija os campos para liberar o envio");
					return;
				}
				mostrarErros(null);
				mostrarHtml(resultado.html);
				textoPre.textContent = resultado.texto;
				hashInput.value = resultado.hash;
				definirEstado("atual", "Prévia em dia");
			})
			.catch(function () {
				if (minhaVez !== sequencia) return;
				definirEstado("erro", "Sem resposta do servidor. A prévia não foi atualizada");
			});
	}

	function reagendar() {
		marcarSujo();
		clearTimeout(espera);
		sequencia++; // invalida o que estiver a caminho
		definirEstado("aguardando", "Digitando…");
		espera = setTimeout(atualizarAgora, 500);
	}

	form.addEventListener("input", reagendar);
	form.addEventListener("change", reagendar);
	form.addEventListener("trix-change", reagendar);

	// Arquivo escolhido sobe agora, pelo mesmo POST de uma prévia completa: o
	// anexo precisa estar em disco para entrar na lista e no hash.
	var arquivo = campo("novo_anexo");
	arquivo.addEventListener("change", function (evento) {
		evento.stopPropagation();
		if (arquivo.files.length) form.requestSubmit(form.querySelector('button[value="previa"]'));
	}, true);

	// Prévia que veio pronta do servidor já vale; a que não veio, pede-se agora.
	if (hashInput.value) definirEstado("atual", "Prévia em dia");
	else atualizarAgora();

	// --- formato e largura da prévia
	via.querySelectorAll("[data-formato]").forEach(function (botao) {
		botao.addEventListener("click", function () {
			formato = botao.dataset.formato;
			via.querySelectorAll("[data-formato]").forEach(function (b) {
				b.setAttribute("aria-pressed", String(b === botao));
			});
			aplicarFormato();
		});
	});
	via.querySelectorAll("[data-largura]").forEach(function (botao) {
		botao.addEventListener("click", function () {
			quadro.style.setProperty("--previa-larg", botao.dataset.largura);
			via.querySelectorAll("[data-largura]").forEach(function (b) {
				b.setAttribute("aria-pressed", String(b === botao));
			});
		});
	});

	// --- telas estreitas: abas Escrever / Prévia
	modal.querySelectorAll("[data-aba-modal]").forEach(function (botao) {
		botao.addEventListener("click", function () {
			modal.dataset.aba = botao.dataset.abaModal;
			modal.querySelectorAll("[data-aba-modal]").forEach(function (b) {
				b.setAttribute("aria-pressed", String(b === botao));
			});
		});
	});

	// --- gravar: um clique duplo em Enviar/Agendar/Salvar não pode gravar duas vezes
	// antes do redirecionamento. Não protege contra F5 (isso é o POST-redirect-GET),
	// só contra a corrida de dois cliques quase simultâneos.
	form.addEventListener("submit", function (evento) {
		var botao = evento.submitter;
		var gravam = ["enviar", "agendar", "salvar", "salvar_rascunho"];
		if (botao && botao.name === "acao" && gravam.indexOf(botao.value) !== -1) {
			setTimeout(function () { botao.disabled = true; }, 0);
		}
	});

	// --- alternar entre o Trix e um textarea de HTML bruto
	//
	// Um campo só (o input oculto "corpo"): o toggle decide qual UI edita esse
	// valor. O HTML colado passa pela mesma limpar_html() do servidor; o que se
	// pula é só o editor Trix, nunca o sanitizador.
	var alternar = document.getElementById("alternar-html-bruto");
	var trix = document.getElementById("editor-trix");
	var bruto = document.getElementById("editor-html-bruto");
	var oculto = document.getElementById("id_corpo");
	var ajudaBruto = form.querySelector("[data-ajuda-bruto]");

	alternar.addEventListener("change", function (evento) {
		evento.stopPropagation(); // não é conteúdo; não reagenda a prévia por si só
		if (alternar.checked) {
			bruto.value = oculto.value;
			trix.hidden = true;
			bruto.hidden = false;
			ajudaBruto.hidden = false;
		} else {
			trix.editor.loadHTML(bruto.value);
			trix.hidden = false;
			bruto.hidden = true;
			ajudaBruto.hidden = true;
		}
		reagendar();
	});
	bruto.addEventListener("input", function () { oculto.value = bruto.value; });
})();
