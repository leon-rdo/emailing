// Ponte do webmail da Hostinger — roda no mundo da PÁGINA (world: MAIN).
//
// O app é Vue 3 em build de produção: os elementos não carregam
// `__vueParentComponent`, então o caminho é descer a árvore de vnodes a partir
// de `#app` até o componente `MessageComposer` desta janela e ler as props dele.
//
// Como no Titan, este arquivo **só lê e repassa** (ver `titan-pagina.js`). A
// única coisa que ele escreve é a lista de arquivos num `<input type=file>`
// oculto que o `comum.js` criou para isso: é o jeito de um `File` atravessar do
// mundo da página para o da extensão sem passar por JSON.
(function () {
	"use strict";

	function nomeDe(instancia) {
		var tipo = instancia && instancia.type;
		return (tipo && (tipo.__name || tipo.name)) || "";
	}

	function compositores() {
		var raiz = document.querySelector("#app");
		var inicio = raiz && raiz._vnode;
		var achados = [];
		var vistos = new Set();
		var pilha = inicio ? [inicio] : [];
		while (pilha.length) {
			var no = pilha.pop();
			if (!no || typeof no !== "object" || vistos.has(no)) continue;
			vistos.add(no);
			if (no.component) {
				if (nomeDe(no.component) === "MessageComposer") achados.push(no.component);
				pilha.push(no.component.subTree);
				continue;
			}
			if (no.suspense) pilha.push(no.suspense.activeBranch);
			if (Array.isArray(no.children)) {
				for (var i = 0; i < no.children.length; i++) pilha.push(no.children[i]);
			}
		}
		return achados;
	}

	function elementoDe(instancia) {
		var el = instancia.subTree && instancia.subTree.el;
		while (el && el.nodeType !== 1) el = el.nextElementSibling || el.parentElement;
		return el || null;
	}

	function doCompositor(elemento) {
		var todos = compositores();
		for (var i = 0; i < todos.length; i++) {
			var el = elementoDe(todos[i]);
			if (el && (el === elemento || elemento.contains(el) || el.contains(elemento))) return todos[i];
		}
		// Uma janela só aberta: não há como errar de qual é.
		return todos.length === 1 ? todos[0] : null;
	}

	function pessoas(lista) {
		return (lista || [])
			.filter(function (p) { return p && p.email; })
			.map(function (p) { return { nome: String(p.name || ""), email: String(p.email) }; });
	}

	function ler(elemento, marca) {
		var instancia = doCompositor(elemento);
		if (!instancia) throw new Error("A Hostinger mudou: não achei o rascunho desta janela.");
		var p = instancia.props;
		var original = p.message || null;

		var entrada = document.querySelector('input[data-emailing-arquivos="' + CSS.escape(marca) + '"]');
		var bandeja = new DataTransfer();
		var anexos = (p.attachments || []).map(function (anexo) {
			var arquivo = anexo && anexo.file instanceof File ? anexo.file : null;
			var posicao = -1;
			if (arquivo && entrada) {
				bandeja.items.add(arquivo);
				posicao = bandeja.files.length - 1;
			}
			return {
				nome: String((anexo && anexo.name) || (arquivo && arquivo.name) || ""),
				tamanho: Number((anexo && anexo.size) || (arquivo && arquivo.size)) || 0,
				tipo: String((arquivo && arquivo.type) || ""),
				posicao: posicao,
			};
		});
		if (entrada) entrada.files = bandeja.files;

		return {
			de: p.from && p.from.email
				? { nome: String(p.from.displayName || ""), email: String(p.from.email) }
				: null,
			para: pessoas(p.to),
			cc: pessoas(p.cc),
			cco: pessoas(p.bcc),
			assunto: String(p.subject || ""),
			corpo: String(p.content || ""),
			tipo: String(p.messageType || ""),
			aparado: !!p.isContentTrimmed,
			textoOriginal: String(p.originalMessageText || ""),
			original: original
				? {
					idMensagem: String(original.messageId || ""),
					assunto: String(original.subject || ""),
					data: String(original.date || ""),
					de: original.from
						? { nome: String(original.from.name || ""), email: String(original.from.address || "") }
						: null,
				}
				: null,
			anexos: anexos,
		};
	}

	document.addEventListener("emailing:ler", function (evento) {
		var marca = String(evento.detail || "");
		var resposta = { marca: marca, ok: false };
		try {
			var compositor = document.querySelector('[data-emailing-ponte="' + CSS.escape(marca) + '"]');
			if (!compositor) throw new Error("Janela de escrita não encontrada.");
			resposta.dados = ler(compositor, marca);
			resposta.ok = true;
		} catch (erro) {
			resposta.erro = String((erro && erro.message) || erro);
		}
		document.dispatchEvent(new CustomEvent("emailing:lido", { detail: JSON.stringify(resposta) }));
	});
})();
