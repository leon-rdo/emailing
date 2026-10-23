---
version: 1
slug: "mensagens-templates-mensagens-base-html"
primary_target: "mensagens/templates/mensagens/base.html"
related_targets: []
---

# Surface brief: shell e telas do Emailing (mode: Operate)

Escopo: todas as telas do app (entrar, enviados, agendados, rascunhos, detalhes, modal de escrita) e a barra do Trix. Usuário único, desktop largo. Estrutura pinada pelo usuário: webmail (menu lateral com configurações, lista de enviados, tela de rascunhos, modal de escrita) como modelo, não como visual.

Não resolvido: nada de busca no servidor além de `?q=` simples no histórico; /admin fora do escopo.

## Direction contract

THESIS: A tipografia é a interface. O eixo de largura e peso de uma fonte variável distingue o que importa; o assunto vira cartaz enquanto se digita e condensa ao encher. Recusa o webmail genérico de cápsulas cinza e o creme com serifa.
OWN-WORLD: Papel branco-azulado #f5f6f8, tinta #0e0e12, azul de fundição #2a35ff como única cor de ação, vermelho #c8102e só para falha. Bricolage Grotesque variável (largura 75 a 100, peso 200 a 800) e Spline Sans Mono só para datas, contagens e cabeçalhos técnicos. Hairlines de 1px, raio 6/14, linhas densas de 36px; alias é um bloco de cor fixo por slug.
STORY: O operador entende de relance o que saiu, o que está na fila e o que falhou; ao escrever, vê a prévia fiel ao lado, sempre atual, e só envia com a prévia em dia.
FIRST VIEWPORT: Menu lateral de 248px (Escrever em azul, Enviados, Agendados, Rascunhos, Configurações, Sair); lista de enviados densa; modal de escrita de 1020px com assunto em corpo 54 que condensa, editor Trix, rodapé de ações, e a via de prévia de 420px fixa à direita.
FORM: webmail clássico reinterpretado como espécime tipográfico, candidato 1 da mão ousada (variable-font-specimen), seed:f68f5a880f2628b0.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
