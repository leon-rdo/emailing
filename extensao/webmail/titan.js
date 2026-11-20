// Adaptador do Titan (webmail da GoDaddy e afins), no mundo isolado.
//
// Além do botão "Emailing" que todo webmail ganha, o Titan tem um gancho a
// mais: o seletor "De:" já lista os aliases da caixa, mas escolher um abre um
// aviso de upgrade. Aqui a escolha vira o **modo alias** daquela janela de
// escrita: o endereço fica marcado, e o Enviar nativo passa a abrir a
// confirmação do Emailing em vez de mandar pela caixa.
//
// O modo alias intercepta o Enviar por todos os caminhos (clique, "enviar
// depois" e Ctrl+Enter). Deixar escapar um deles mandaria a mensagem pelo
// Titan com o remetente errado — o pior defeito possível desta extensão.
(function () {
	"use strict";

	var E = globalThis.EmailingExt;
	var COMPOSITOR = '[data-testid="composer-container"]';
	var ITEM_DE = '[data-testid="from-field"] .email-alias-item';
	var ENVIAR = '[data-testid="send-action-btn"], [data-testid="send-later-btn"]';
	var ATRIBUTO_ALIAS = "data-emailing-alias";

	function dentro(alvo, seletor) {
		return alvo && alvo.closest ? alvo.closest(seletor) : null;
	}

	function enderecoDoItem(item) {
		var texto = item.textContent || "";
		var achado = /<([^<>\s]+@[^<>\s]+)>/.exec(texto) || /([^\s<>]+@[^\s<>]+)/.exec(texto);
		return achado ? achado[1].toLowerCase() : "";
	}

	// ------------------------------------------------------------- modo alias

	function garantirFicha(compositor) {
		var alias = compositor.getAttribute(ATRIBUTO_ALIAS);
		var ficha = compositor.querySelector(".emailing-ext-ficha");
		if (!alias) {
			if (ficha) ficha.remove();
			return;
		}
		var campo = compositor.querySelector('[data-testid="from-field"] .composer-from-field')
			|| compositor.querySelector('[data-testid="from-field"]');
		if (!campo) return;
		if (!ficha) {
			ficha = document.createElement("span");
			ficha.className = "emailing-ext-ficha";
			var texto = document.createElement("span");
			texto.className = "emailing-ext-ficha-endereco";
			var selo = document.createElement("small");
			selo.textContent = "via Emailing";
			var sair = document.createElement("button");
			sair.type = "button";
			sair.title = "Voltar a enviar pela caixa, pelo próprio Titan";
			sair.setAttribute("aria-label", sair.title);
			sair.textContent = "×";
			sair.addEventListener("click", function (evento) {
				evento.preventDefault();
				evento.stopPropagation();
				definirAlias(compositor, "");
			});
			ficha.append(texto, selo, sair);
			campo.appendChild(ficha);
		}
		ficha.querySelector(".emailing-ext-ficha-endereco").textContent = alias;
	}

	function definirAlias(compositor, alias) {
		if (alias) compositor.setAttribute(ATRIBUTO_ALIAS, alias);
		else compositor.removeAttribute(ATRIBUTO_ALIAS);
		garantirFicha(compositor);
	}

	function fecharSeletor(compositor) {
		var seletor = compositor.querySelector('[data-testid="from-field"] [data-testid="button-dropdown"]');
		var cabeca = seletor && seletor.querySelector('[data-testid="dropdown-header"]');
		if (cabeca && /\bopen\b/.test(seletor.className)) cabeca.click();
	}

	// Um alias bloqueado pelo plano é o item que vem embrulhado no aviso de
	// upgrade. O item da própria caixa (e um alias que o plano libere) não tem
	// o embrulho: esses seguem para o Titan, e o modo alias é desligado.
	function aoMexerNoDe(evento) {
		var item = dentro(evento.target, ITEM_DE);
		if (!item) return;
		var compositor = dentro(item, COMPOSITOR);
		if (!compositor) return;
		var bloqueado = !!item.querySelector(".titan-max-wrapper");
		var alias = enderecoDoItem(item);
		if (!bloqueado || !alias) {
			if (evento.type === "click") definirAlias(compositor, "");
			return;
		}
		// Nenhum dos eventos do gesto chega ao Titan: o aviso de upgrade não abre.
		evento.preventDefault();
		evento.stopImmediatePropagation();
		if (evento.type === "click" && evento.isTrusted) {
			definirAlias(compositor, alias);
			fecharSeletor(compositor);
		}
	}

	function aoMexerNoEnviar(evento) {
		var botao = dentro(evento.target, ENVIAR);
		if (!botao) return;
		var compositor = dentro(botao, COMPOSITOR);
		if (!compositor || !compositor.hasAttribute(ATRIBUTO_ALIAS)) return;
		evento.preventDefault();
		evento.stopImmediatePropagation();
		if (evento.type === "click" && evento.isTrusted) E.iniciarEnvio(compositor);
	}

	function aoTeclar(evento) {
		if (evento.key !== "Enter" || !(evento.ctrlKey || evento.metaKey)) return;
		var compositor = dentro(evento.target, COMPOSITOR);
		if (!compositor || !compositor.hasAttribute(ATRIBUTO_ALIAS)) return;
		evento.preventDefault();
		evento.stopImmediatePropagation();
		if (evento.type === "keydown" && evento.isTrusted && !evento.repeat) E.iniciarEnvio(compositor);
	}

	// --------------------------------------------------------------- o corpo

	// O que está na tela vem do editor (é o que a pessoa vê e acabou de
	// digitar); a citação que o editor esconde numa resposta vem do rascunho.
	function corpo(compositor, corpoDoRascunho) {
		var editor = compositor.querySelector('[data-testid="composer-editor"]');
		var doc = E.analisar(editor ? editor.innerHTML : corpoDoRascunho);
		var raiz = doc.body;
		raiz.querySelectorAll("[data-signature-parent], signature, .fr-marker").forEach(function (no) {
			no.remove();
		});
		// O botão "•••" que esconde a citação numa resposta é um nó do editor
		// (`quoted-text-node-<id>`, não editável). Recolhido, não tem conteúdo.
		raiz.querySelectorAll('[class*="quoted-text-node"]').forEach(function (no) {
			if (!no.querySelector(".gmail_quote, .flockmail-quote, blockquote")) no.remove();
		});

		var imagensPerdidas = E.imagensQueNaoViajam(raiz);
		E.apararFim(raiz);

		if (editor && !raiz.querySelector(".gmail_quote, .flockmail-quote")) {
			var citacao = E.analisar(corpoDoRascunho).body.querySelector(".flockmail-quote, .gmail_quote");
			if (citacao) {
				raiz.appendChild(doc.createElement("br"));
				raiz.appendChild(doc.importNode(citacao, true));
			}
		}
		return { html: raiz.innerHTML.trim(), imagensPerdidas: imagensPerdidas };
	}

	function referencias(dados) {
		var pai = dados.emRespostaA;
		if (!pai) return [];
		var conversa = dados.conversa || [];
		var ate = conversa.indexOf(pai);
		// Só os ancestrais: o que veio depois da mensagem respondida não entra.
		var cadeia = ate === -1 ? [] : conversa.slice(0, ate);
		cadeia.push(pai);
		return cadeia;
	}

	E.registrar({
		nome: "titan",
		rotulo: "Titan",
		seletorCompositor: COMPOSITOR,

		ancora: function (compositor) {
			// Depois do par "Enviar" + "enviar depois", que são dois blocos colados:
			// entrar no meio deles separaria a seta do botão.
			var enviar = compositor.querySelector('[data-testid="send-later-btn"]')
				|| compositor.querySelector('[data-testid="send-action-btn"]');
			if (!enviar) return null;
			return { referencia: enviar.closest(".button-container") || enviar, posicao: "afterend" };
		},

		aoVarrer: garantirFicha,

		aoIniciar: function () {
			// Na janela, em captura: antes dos ouvintes do React, que ficam em #root.
			["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach(function (tipo) {
				window.addEventListener(tipo, aoMexerNoDe, true);
				window.addEventListener(tipo, aoMexerNoEnviar, true);
			});
			["keydown", "keypress", "keyup"].forEach(function (tipo) {
				window.addEventListener(tipo, aoTeclar, true);
			});
		},

		montar: function (dados, compositor) {
			var caixa = (dados.de && dados.de.email) || "";
			var assunto = compositor.querySelector('[data-testid="subject-input"]');
			var partes = corpo(compositor, dados.corpo);
			return {
				caixa: caixa,
				de: compositor.getAttribute(ATRIBUTO_ALIAS) || caixa,
				para: E.enderecos(dados.para),
				cc: E.enderecos(dados.cc),
				cco: E.enderecos(dados.cco),
				assunto: assunto ? assunto.value : dados.assunto,
				html: partes.html,
				imagensPerdidas: partes.imagensPerdidas,
				emRespostaA: dados.emRespostaA,
				referencias: referencias(dados),
				anexos: (dados.anexos || []).filter(function (a) { return !a.embutido; }).map(function (a) {
					return { nome: a.nome, tamanho: a.tamanho, tipo: a.tipo, arquivo: E.capturado(a.nome, a.tamanho) };
				}),
			};
		},

		descartar: function (compositor) {
			var lixeira = compositor.querySelector('[data-testid="composer-trash-btn"]');
			if (!lixeira) return false;
			lixeira.click();
			return true;
		},
	});
})();
