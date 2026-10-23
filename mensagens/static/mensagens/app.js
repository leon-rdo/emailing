// Comportamentos de toda tela: avisos que somem sozinhos e confirmação de ação
// sem volta. Servido do próprio domínio (o CSP só aceita script 'self' ou com nonce).
(function () {
	"use strict";

	// Formulário com data-confirmar pergunta antes de enviar: para o que não tem volta.
	document.addEventListener("submit", function (evento) {
		var pergunta = evento.target.dataset && evento.target.dataset.confirmar;
		if (pergunta && !window.confirm(pergunta)) evento.preventDefault();
	});

	// Aviso de sucesso some em 6s; erro e alerta ficam até a próxima navegação,
	// porque dizem o que fazer.
	document.querySelectorAll(".aviso.success, .aviso.info").forEach(function (aviso) {
		setTimeout(function () {
			aviso.classList.add("some");
			setTimeout(function () { aviso.remove(); }, 300);
		}, 6000);
	});

	// Menu em tela estreita: a barra de cima abre uma gaveta com a navegação inteira.
	var menu = document.querySelector(".menu");
	var botao = menu && menu.querySelector(".menu-botao");
	function alternarMenu(aberto) {
		if (aberto) menu.setAttribute("data-aberto", ""); else menu.removeAttribute("data-aberto");
		botao.setAttribute("aria-expanded", String(aberto));
	}
	if (botao) {
		botao.addEventListener("click", function () { alternarMenu(!menu.hasAttribute("data-aberto")); });
		document.addEventListener("keydown", function (e) { if (e.key === "Escape") alternarMenu(false); });
	}
})();
