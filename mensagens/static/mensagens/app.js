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
})();
