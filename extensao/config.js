// O único dado que a extensão guarda: o endereço do Emailing. Compartilhado
// pelo service worker (`importScripts`) e pela página de opções (`<script>`).
//
// Não há endereço embutido: o repositório é genérico, e a extensão só ganha
// permissão para o Emailing de quem a instalou depois de ele informar onde
// fica (ver docs/decisoes.md#extensao-endereco).
(function () {
	"use strict";

	var CHAVE = "urlEmailing";
	var LOCAIS = ["localhost", "127.0.0.1"];

	// "https://emailing.example.com/" → { url, origem, padrao } ou `null`.
	// `padrao` é o que o Chrome entende como permissão de host; não leva porta.
	function normalizar(bruto) {
		var u;
		try {
			u = new URL(String(bruto || "").trim());
		} catch (_erro) {
			return null;
		}
		var local = LOCAIS.indexOf(u.hostname) !== -1;
		if (u.protocol !== "https:" && !(u.protocol === "http:" && local)) return null;
		return {
			url: (u.origin + u.pathname).replace(/\/+$/, ""),
			origem: u.origin,
			padrao: u.protocol + "//" + u.hostname + "/*",
		};
	}

	function ler() {
		return chrome.storage.local.get(CHAVE).then(function (guardado) {
			return normalizar(guardado[CHAVE]);
		});
	}

	function gravar(url) {
		var item = {};
		item[CHAVE] = url;
		return chrome.storage.local.set(item);
	}

	globalThis.EmailingConfig = { CHAVE: CHAVE, normalizar: normalizar, ler: ler, gravar: gravar };
})();
