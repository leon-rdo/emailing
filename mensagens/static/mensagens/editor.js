// Configuração do editor Trix.

// Anexos do PRÓPRIO editor ficam desligados: o Trix aceita arrastar/colar
// imagem por padrão e gera um <figure> com uma URL blob: que só existe
// enquanto a aba do navegador está aberta — morta a URL, a imagem morre
// junto, silenciosamente, dentro de todo e-mail que já foi enviado. Anexos de
// verdade (upload real, indo para o disco e para o e-mail) são um recurso à
// parte, fora do corpo do editor.
document.addEventListener("trix-file-accept", function (evento) {
	evento.preventDefault();
});

// Fontes seguras para e-mail: as que existem em praticamente todo sistema,
// mais um fallback genérico. Fonte web (@font-face) não vale a pena aqui —
// Outlook e Gmail ignoram, e o resultado seria imprevisível.
var FONTES = [
	["", "Fonte padrão"],
	["Arial, Helvetica, sans-serif", "Arial"],
	["Verdana, Geneva, sans-serif", "Verdana"],
	["Tahoma, Geneva, sans-serif", "Tahoma"],
	["'Trebuchet MS', Helvetica, sans-serif", "Trebuchet"],
	["Georgia, 'Times New Roman', serif", "Georgia"],
	["'Times New Roman', Times, serif", "Times New Roman"],
	["'Courier New', Courier, monospace", "Courier New"],
];

function chaveDaFonte(familia) {
	return "fonte" + familia.replace(/[^a-zA-Z]/g, "");
}

// Configurado no carregamento, não no evento "trix-before-initialize": o Trix
// só registra os custom elements num setTimeout, então window.Trix já existe
// aqui, e depender do evento é uma corrida que se perde em silêncio (foi o
// que aconteceu: os atributos não chegavam a ser registrados).
if (window.Trix) {
	// O "code" nativo do Trix é atributo de BLOCO: marca o parágrafo inteiro
	// como <pre>. Este é atributo de TEXTO, então dá para marcar uma palavra
	// no meio da frase — que é o que se quer 90% das vezes.
	Trix.config.textAttributes.codigo = {
		tagName: "code",
		inheritable: true,
	};

	FONTES.forEach(function (par) {
		var familia = par[0];
		if (!familia) return;
		Trix.config.textAttributes[chaveDaFonte(familia)] = {
			style: { fontFamily: familia },
			inheritable: true,
			parser: function (elemento) {
				return elemento.style.fontFamily === familia;
			},
		};
	});
}

document.addEventListener("trix-initialize", function (evento) {
	var editor = evento.target;
	var barra = editor.toolbarElement;
	if (!barra || barra.dataset.personalizada) return;
	barra.dataset.personalizada = "1";

	var grupoTexto = barra.querySelector(".trix-button-group--text-tools");
	if (!grupoTexto) return;

	// --- botão de código inline ---
	var botaoCodigo = document.createElement("button");
	botaoCodigo.type = "button";
	botaoCodigo.className = "trix-button trix-button--icon botao-codigo-inline";
	botaoCodigo.dataset.trixAttribute = "codigo";
	botaoCodigo.title = "Código (só o trecho selecionado)";
	botaoCodigo.textContent = "</>";
	grupoTexto.appendChild(botaoCodigo);

	// --- seletor de fonte ---
	var seletor = document.createElement("select");
	seletor.className = "seletor-de-fonte";
	seletor.title = "Fonte do trecho selecionado";
	FONTES.forEach(function (par) {
		var opcao = document.createElement("option");
		opcao.value = par[0];
		opcao.textContent = par[1];
		if (par[0]) opcao.style.fontFamily = par[0];
		seletor.appendChild(opcao);
	});

	seletor.addEventListener("change", function () {
		// Trocar de fonte é trocar de atributo: desativa todas antes, senão
		// duas famílias ficariam aplicadas ao mesmo trecho.
		FONTES.forEach(function (par) {
			if (par[0]) editor.editor.deactivateAttribute(chaveDaFonte(par[0]));
		});
		if (seletor.value) {
			editor.editor.activateAttribute(chaveDaFonte(seletor.value));
		}
		editor.focus();
	});

	grupoTexto.appendChild(seletor);
});
