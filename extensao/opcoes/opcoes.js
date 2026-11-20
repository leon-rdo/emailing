// Página de opções: o endereço do Emailing e a permissão para ele.
(function () {
	"use strict";

	const form = document.getElementById("form-endereco");
	const campo = document.getElementById("endereco");
	const estado = document.getElementById("estado");

	function mostrar(texto, tipo) {
		estado.textContent = texto;
		estado.dataset.tipo = tipo || "";
	}

	async function situacao() {
		const config = await EmailingConfig.ler();
		if (!config) {
			mostrar("Ainda não configurado.", "");
			return;
		}
		campo.value = config.url;
		const permitido = await chrome.permissions.contains({ origins: [config.padrao] });
		mostrar(
			permitido
				? "Pronto: a extensão está ligada a " + config.url + "."
				: "Falta a permissão para " + config.url + ". Clique em Salvar para concedê-la.",
			permitido ? "ok" : "erro"
		);
	}

	form.addEventListener("submit", (evento) => {
		evento.preventDefault();
		// Quem digita só "emailing.example.com" quer dizer https.
		const digitado = campo.value.trim();
		const nova = EmailingConfig.normalizar(/^[a-z][a-z0-9+.-]*:\/\//i.test(digitado) ? digitado : "https://" + digitado);
		if (!nova) {
			mostrar("Esse endereço não serve: precisa ser https:// (http só para localhost).", "erro");
			return;
		}
		// Direto no gesto do clique, sem `await` antes: o Chrome só mostra o
		// pedido de permissão em resposta a uma ação de quem está usando.
		chrome.permissions.request({ origins: [nova.padrao] }).then(async (concedida) => {
			if (!concedida) {
				mostrar("Sem essa permissão a extensão não consegue preencher a tela do Emailing.", "erro");
				return;
			}
			const anterior = await EmailingConfig.ler();
			await EmailingConfig.gravar(nova.url);
			if (anterior && anterior.padrao !== nova.padrao) {
				await chrome.permissions.remove({ origins: [anterior.padrao] }).catch(() => {});
			}
			await situacao();
		}, () => mostrar("O Chrome recusou o pedido de permissão para esse endereço.", "erro"));
	});

	situacao();
})();
