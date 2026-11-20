// Adaptador do webmail da Hostinger (mail.hostinger.com), no mundo isolado.
//
// Aqui não há modo alias nem interceptação: a Hostinger já deixa escolher um
// alias no "De" e envia por ele. O Enviar nativo fica como está, e o botão
// "Emailing" é o caminho para quem quer a assinatura do alias, os marcadores e
// o histórico do Emailing. O "De" escolhido no webmail vai junto, e é ele que a
// tela do Emailing seleciona quando existe lá um alias com o mesmo endereço.
(function () {
	"use strict";

	var E = globalThis.EmailingExt;
	var COMPOSITOR = '[data-qa="message-composer"]';

	function editorVivo(compositor) {
		var quadro = compositor.querySelector('[data-qa="composer-content-iframe"]');
		try {
			var doc = quadro && quadro.contentDocument;
			return doc ? doc.querySelector(".hmail-editor") || doc.body : null;
		} catch (_erro) {
			return null;
		}
	}

	function quando(texto) {
		var data = new Date(texto);
		if (!texto || isNaN(data.getTime())) return "";
		return data.toLocaleString("pt-BR", { dateStyle: "long", timeStyle: "short" });
	}

	// A Hostinger guarda a mensagem original fora do editor ("conteúdo aparado")
	// e só a junta ao enviar. O que a página expõe dela é o texto simples.
	function citacao(dados) {
		var texto = (dados.textoOriginal || "").trim();
		if (!dados.aparado || !texto) return "";
		var original = dados.original || {};
		var autor = original.de
			? E.escapar(original.de.nome ? original.de.nome + " <" + original.de.email + ">" : original.de.email)
			: "";
		var data = quando(original.data);
		var cabeca;
		if (/^forward/i.test(dados.tipo)) {
			cabeca = "---------- Mensagem encaminhada ----------"
				+ (autor ? "<br>De: " + autor : "")
				+ (data ? "<br>Data: " + E.escapar(data) : "")
				+ (original.assunto ? "<br>Assunto: " + E.escapar(original.assunto) : "");
		} else {
			cabeca = (data ? "Em " + E.escapar(data) + ", " : "") + (autor || "a mensagem original") + " escreveu:";
		}
		return "<br><div>" + cabeca + "</div><blockquote>" + E.textoParaHtml(texto) + "</blockquote>";
	}

	function corpo(compositor, dados) {
		var editor = editorVivo(compositor);
		var doc = E.analisar(editor ? editor.innerHTML : dados.corpo);
		var raiz = doc.body;
		raiz.querySelectorAll(".hmail-signature-prefix, .hmail-signature").forEach(function (no) {
			no.remove();
		});
		var imagensPerdidas = E.imagensQueNaoViajam(raiz);
		E.apararFim(raiz);
		return { html: (raiz.innerHTML.trim() + citacao(dados)).trim(), imagensPerdidas: imagensPerdidas };
	}

	function confirmarDescarte(compositor) {
		return new Promise(function (resolver) {
			var tentativas = 0;
			(function olhar() {
				var modal = document.querySelector('[data-qa="confirmation-modal"]');
				if (modal) {
					var botao = Array.prototype.find.call(modal.querySelectorAll("button"), function (b) {
						return /descartar|discard|excluir|delete/i.test(b.textContent || "");
					});
					if (botao) botao.click();
					resolver(!!botao);
					return;
				}
				if (!document.contains(compositor)) { resolver(true); return; }
				if (++tentativas > 25) { resolver(false); return; }
				setTimeout(olhar, 100);
			})();
		});
	}

	E.registrar({
		nome: "hostinger",
		rotulo: "Hostinger",
		seletorCompositor: COMPOSITOR,

		ancora: function (compositor) {
			// Na linha do "De", à direita: é onde se escolhe o remetente, e há
			// espaço. Ao lado do Enviar não cabe — a barra de baixo já ocupa a
			// largura toda da janela de escrita, e um botão a mais empurra os
			// controles da própria Hostinger para dentro de uma barra de rolagem.
			var fileira = compositor.querySelector('[data-qa="composer-from"]');
			while (fileira && fileira !== compositor && !fileira.querySelector(":scope > label")) {
				fileira = fileira.parentElement;
			}
			if (fileira && fileira !== compositor) return { referencia: fileira, posicao: "beforeend" };

			// Sem a linha do "De" (a tela mudou): depois da grade do Enviar, que tem
			// áreas nomeadas — um filho a mais dentro dela cairia antes do botão.
			var enviar = compositor.querySelector('[data-qa="schedule-send-split-button"]');
			if (!enviar) return null;
			var grade = enviar.parentElement;
			var sozinho = grade && Array.prototype.every.call(grade.children, function (filho) {
				return filho === enviar;
			});
			return { referencia: sozinho ? grade : enviar, posicao: "afterend" };
		},

		montar: function (dados, compositor, arquivos) {
			var de = (dados.de && dados.de.email) || "";
			var naAba = /[^\s<>]+@[^\s<>]+/.exec(document.title || "");
			var assunto = compositor.querySelector('[data-qa="composer-subject"]');
			var original = dados.original || {};
			var resposta = /^reply/i.test(dados.tipo) && original.idMensagem;
			var partes = corpo(compositor, dados);
			return {
				caixa: naAba ? naAba[0] : de,
				de: de,
				para: E.enderecos(dados.para),
				cc: E.enderecos(dados.cc),
				cco: E.enderecos(dados.cco),
				assunto: assunto ? assunto.value : dados.assunto,
				html: partes.html,
				imagensPerdidas: partes.imagensPerdidas,
				emRespostaA: resposta ? original.idMensagem : "",
				referencias: resposta ? [original.idMensagem] : [],
				anexos: (dados.anexos || []).map(function (a) {
					return {
						nome: a.nome,
						tamanho: a.tamanho,
						tipo: a.tipo,
						arquivo: a.posicao >= 0 ? arquivos[a.posicao] || null : null,
					};
				}),
			};
		},

		descartar: function (compositor) {
			var botao = compositor.querySelector('[data-qa="composer-discard-draft"]');
			if (!botao) return false;
			botao.click();
			return confirmarDescarte(compositor);
		},
	});
})();
