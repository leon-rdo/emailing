// Configuração do editor Trix.
//
// Anexos do PRÓPRIO editor ficam desligados: o Trix aceita arrastar/colar
// imagem por padrão e gera um <figure> com uma URL blob: que só existe
// enquanto a aba do navegador está aberta — morta a URL, a imagem morre
// junto, silenciosamente, dentro de todo e-mail que já foi enviado. Anexos de
// verdade (upload real, indo para o disco e para o e-mail) são um recurso à
// parte, fora do corpo do editor.
document.addEventListener("trix-file-accept", function (evento) {
	evento.preventDefault();
});
