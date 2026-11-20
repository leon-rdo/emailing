// Ponte do Titan — roda no mundo da PÁGINA (world: MAIN), não no da extensão.
//
// Só aqui dá para ler o estado do React: as propriedades `__reactFiber$…` que
// ele pendura nos elementos não existem no mundo isolado dos content scripts.
// Em troca, este arquivo fica ao alcance do JavaScript do próprio Titan — por
// isso ele **só lê e repassa**. Não envia, não descarta, não clica em nada e
// não conhece `chrome.*`. Quem decide o que fazer com o que sai daqui é o
// `comum.js`, e quem envia é a tela do Emailing, depois de um clique humano.
//
// Protocolo (o mesmo do `hostinger-pagina.js`):
//   mundo isolado → document: CustomEvent("emailing:ler", detail = marca)
//   aqui → document: CustomEvent("emailing:lido", detail = JSON {marca, ok, dados | erro})
// A marca é o valor de `data-emailing-ponte` no compositor a ler.
(function () {
	"use strict";

	var LIMITE_SUBIDA = 160;

	function fibraDe(elemento) {
		for (var chave in elemento) {
			if (chave.indexOf("__reactFiber$") === 0) return elemento[chave];
		}
		return null;
	}

	// Sobe pela árvore do React a partir de `elemento` até achar props que
	// passem em `serve`.
	function propsAcima(elemento, serve, limite) {
		var fibra = elemento && fibraDe(elemento);
		for (var i = 0; fibra && i < (limite || LIMITE_SUBIDA); i++, fibra = fibra.return) {
			var props = fibra.memoizedProps;
			if (props && serve(props)) return props;
		}
		return null;
	}

	function pessoas(lista) {
		return (lista || [])
			.filter(function (p) { return p && p.email; })
			.map(function (p) { return { nome: String(p.name || ""), email: String(p.email) }; });
	}

	// Os Message-ID das mensagens abertas da mesma conversa, na ordem da tela:
	// é o que dá para pôr em `References` sem pedir nada ao servidor do Titan.
	function idsDaConversa(rascunho) {
		var conversa = rascunho.replyToThreadId || rascunho.threadId;
		if (!conversa) return [];
		var ids = [];
		document.querySelectorAll('[data-testid="message-item-wrap"]').forEach(function (item) {
			var props = propsAcima(item, function (p) {
				return p.message && typeof p.message === "object";
			}, 8);
			var mensagem = props && props.message;
			if (!mensagem || mensagem.draft || mensagem.threadId !== conversa) return;
			if (mensagem.messageIdHeader) ids.push(String(mensagem.messageIdHeader));
		});
		return ids;
	}

	function ler(compositor) {
		var ponto = compositor.querySelector('[data-testid="send-action-btn"]') || compositor;
		var props = propsAcima(ponto, function (p) {
			return p.draft && typeof p.draft === "object" && p.session;
		});
		if (!props) throw new Error("O Titan mudou: não achei o rascunho desta janela.");
		var rascunho = props.draft;
		return {
			de: pessoas(rascunho.from)[0] || null,
			para: pessoas(rascunho.to),
			cc: pessoas(rascunho.cc),
			cco: pessoas(rascunho.bcc),
			assunto: String(rascunho.subject || ""),
			corpo: String(rascunho.body || ""),
			emRespostaA: String(rascunho.replyToMessageHeaderId || ""),
			conversa: idsDaConversa(rascunho),
			anexos: (rascunho.files || []).map(function (arquivo) {
				return {
					nome: String(arquivo.filename || ""),
					tamanho: Number(arquivo.size) || 0,
					tipo: String(arquivo.contentType || ""),
					embutido: String(arquivo.disposition || "").toUpperCase() === "INLINE",
				};
			}),
		};
	}

	document.addEventListener("emailing:ler", function (evento) {
		var marca = String(evento.detail || "");
		var resposta = { marca: marca, ok: false };
		try {
			var compositor = document.querySelector('[data-emailing-ponte="' + CSS.escape(marca) + '"]');
			if (!compositor) throw new Error("Janela de escrita não encontrada.");
			resposta.dados = ler(compositor);
			resposta.ok = true;
		} catch (erro) {
			resposta.erro = String((erro && erro.message) || erro);
		}
		document.dispatchEvent(new CustomEvent("emailing:lido", { detail: JSON.stringify(resposta) }));
	});
})();
