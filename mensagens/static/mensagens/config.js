// Configurações: predefinições de provedor, teste de conexão e o editor da
// assinatura (HTML à esquerda, o e-mail à direita).
(function () {
	"use strict";

	function csrf(form) {
		var campo = form.querySelector('input[name="csrfmiddlewaretoken"]');
		return campo ? campo.value : "";
	}

	// --- conta: preencher servidor, porta e cifra
	var formConta = document.querySelector("form.form-conta");
	if (formConta) {
		var campo = function (nome) { return formConta.querySelector('[name="' + nome + '"]'); };

		formConta.querySelectorAll("[data-host]").forEach(function (botao) {
			botao.addEventListener("click", function () {
				campo("host").value = botao.dataset.host;
				campo("porta").value = botao.dataset.porta;
				var cifra = formConta.querySelector('input[name="cifra"][value="' + botao.dataset.cifra + '"]');
				if (cifra) cifra.checked = true;
				campo("usuario").focus();
			});
		});

		// Trocar a cifra sugere a porta que costuma acompanhá-la; nunca sobrescreve
		// uma porta que o operador mudou de propósito.
		formConta.querySelectorAll('input[name="cifra"]').forEach(function (r) {
			r.addEventListener("change", function () {
				var porta = campo("porta");
				if (porta.value === "587" || porta.value === "465" || !porta.value) {
					porta.value = r.value === "ssl" ? "465" : "587";
				}
			});
		});

		var botaoTeste = document.getElementById("testar-conexao");
		var resultado = formConta.querySelector(".resultado-teste");
		botaoTeste.addEventListener("click", function () {
			var dados = new FormData(formConta);
			dados.set("pk", formConta.dataset.pk || "");
			resultado.dataset.estado = "testando";
			resultado.textContent = "Conectando…";
			botaoTeste.disabled = true;
			fetch(formConta.dataset.urlTestar, {
				method: "POST", body: dados, credentials: "same-origin",
				headers: { "X-CSRFToken": csrf(formConta) },
			})
				.then(function (r) { return r.json(); })
				.then(function (r) {
					resultado.dataset.estado = r.ok ? "ok" : "erro";
					resultado.textContent = r.ok ? "Conectou e autenticou." : r.erro;
				})
				.catch(function () {
					resultado.dataset.estado = "erro";
					resultado.textContent = "Sem resposta do servidor.";
				})
				.then(function () { botaoTeste.disabled = false; });
		});
	}

	// --- alias: editor da assinatura
	var formAlias = document.querySelector("form.form-alias");
	if (formAlias) {
		var area = formAlias.querySelector('textarea[name="assinatura_html"]');
		var iframe = formAlias.querySelector(".previa-iframe");
		var quadro = formAlias.querySelector(".previa-quadro");
		var situacao = formAlias.querySelector(".situacao");
		var textoSituacao = situacao.querySelector(".texto-situacao");
		var sequencia = 0, espera = null;

		function mostrar(html) {
			var novo = document.createElement("iframe");
			novo.className = "previa-iframe";
			novo.title = iframe.title;
			novo.setAttribute("sandbox", "");
			novo.hidden = true;
			novo.addEventListener("load", function () {
				iframe.remove();
				iframe = novo;
				iframe.hidden = false;
			}, { once: true });
			novo.srcdoc = html;
			quadro.insertBefore(novo, quadro.firstChild);
		}

		function definir(estado, texto) {
			situacao.dataset.estado = estado;
			textoSituacao.textContent = texto;
		}

		function atualizar() {
			var minha = ++sequencia;
			definir("atualizando", "Atualizando…");
			var dados = new FormData();
			dados.set("assinatura_html", area.value);
			fetch(formAlias.dataset.urlPrevia, {
				method: "POST", body: dados, credentials: "same-origin",
				headers: { "X-CSRFToken": csrf(formAlias) },
			})
				.then(function (r) { return r.json(); })
				.then(function (r) {
					if (minha !== sequencia) return;
					mostrar(r.html);
					definir("atual", "Atualizada");
				})
				.catch(function () {
					if (minha === sequencia) definir("erro", "Sem resposta do servidor");
				});
		}

		area.addEventListener("input", function () {
			clearTimeout(espera);
			sequencia++;
			definir("aguardando", "Digitando…");
			espera = setTimeout(atualizar, 400);
		});
		atualizar();

		// Trechos prontos, inseridos onde está o cursor (ou envolvendo a seleção).
		var TRECHOS = {
			negrito: ["<strong>", "</strong>", "texto"],
			link: ['<a href="https://" style="color:#1a56db;text-decoration:none;">', "</a>", "texto do link"],
			imagem: ['<img src="https://" alt="" width="120" style="display:block;border:0;">', "", ""],
			linha: ['<hr style="border:0;border-top:1px solid #d9d9d9;margin:12px 0;">', "", ""],
			contato: [
				'<p style="margin:0;font:14px/1.5 Arial,Helvetica,sans-serif;color:#222;">\n' +
				'  <strong>Nome Sobrenome</strong><br>\n  Cargo · Empresa<br>\n' +
				'  <a href="tel:+5500000000000" style="color:#222;text-decoration:none;">+55 00 00000-0000</a>\n</p>', "", ""],
			logo: [
				'<table cellpadding="0" cellspacing="0" border="0" style="font:14px/1.5 Arial,Helvetica,sans-serif;color:#222;">\n' +
				'  <tr>\n    <td style="padding-right:16px;vertical-align:top;"><img src="https://" alt="" width="88" style="display:block;border:0;"></td>\n' +
				'    <td style="vertical-align:top;"><strong>Nome Sobrenome</strong><br>Cargo · Empresa<br>+55 00 00000-0000</td>\n  </tr>\n</table>', "", ""],
		};
		formAlias.querySelectorAll("[data-insere]").forEach(function (botao) {
			botao.addEventListener("click", function () {
				var t = TRECHOS[botao.dataset.insere];
				var ini = area.selectionStart, fim = area.selectionEnd;
				var selecionado = area.value.slice(ini, fim) || t[2];
				var novo = t[0] + selecionado + t[1];
				area.setRangeText(novo, ini, fim, "end");
				area.focus();
				area.dispatchEvent(new Event("input", { bubbles: true }));
			});
		});
	}
})();
