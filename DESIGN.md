---
name: Emailing
description: Webmail de usuário único em que a tipografia variável é a interface e um único azul age.
colors:
  papel: "#f5f6f8"
  superficie: "#ffffff"
  tinta: "#0e0e12"
  tinta-2: "#3d414d"
  mudo: "#5b5f6c"
  linha: "#d9dce3"
  linha-forte: "#b9bdc8"
  acao: "#2a35ff"
  acao-escura: "#1a24d6"
  acao-fraca: "#e6e8ff"
  erro: "#c8102e"
  erro-fraco: "#fdecee"
  ok: "#0a7d4b"
  ok-fraco: "#e3f5ec"
  fila: "#7a4b00"
  fila-fraco: "#fff1d6"
typography:
  marca:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "28px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.025em"
  cartaz:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "54px"
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: "-0.025em"
  display:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(56px, 12vw, 84px)"
    fontWeight: 800
    lineHeight: 0.95
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "36px"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 700
    lineHeight: 1.5
  body:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.5
  dado:
    fontFamily: "Spline Sans Mono, ui-monospace, SF Mono, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.5
rounded:
  sm: "4px"
  md: "6px"
  aviso: "10px"
  modal: "14px"
  pilula: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  pagina: "28px"
  menu: "248px"
components:
  botao-primario:
    backgroundColor: "{colors.acao}"
    textColor: "#ffffff"
    typography: "{typography.label}"
    rounded: "{rounded.pilula}"
    padding: "10px 20px"
  botao-primario-hover:
    backgroundColor: "{colors.acao-escura}"
  botao-secundario:
    backgroundColor: "transparent"
    textColor: "{colors.tinta}"
    rounded: "{rounded.pilula}"
    padding: "10px 20px"
  botao-escrever:
    backgroundColor: "{colors.acao}"
    textColor: "#ffffff"
    rounded: "{rounded.pilula}"
    padding: "13px 22px 13px 18px"
  menu-item:
    textColor: "{colors.tinta-2}"
    rounded: "{rounded.md}"
    padding: "9px 12px"
  menu-item-ativo:
    backgroundColor: "{colors.acao-fraca}"
    textColor: "{colors.acao-escura}"
  campo:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.md}"
    padding: "10px 12px"
  linha-lista:
    backgroundColor: "transparent"
    textColor: "{colors.tinta}"
    padding: "6px 28px"
    height: "44px"
  linha-lista-hover:
    backgroundColor: "{colors.superficie}"
  selo-falhou:
    backgroundColor: "{colors.erro-fraco}"
    textColor: "{colors.erro}"
    rounded: "{rounded.pilula}"
    padding: "1px 9px"
  selo-agendado:
    backgroundColor: "{colors.fila-fraco}"
    textColor: "{colors.fila}"
    rounded: "{rounded.pilula}"
    padding: "1px 9px"
  modal-escrever:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.modal}"
  aviso:
    backgroundColor: "{colors.tinta}"
    textColor: "#ffffff"
    rounded: "{rounded.aviso}"
    padding: "12px 16px"
---

# Design System: Emailing

## Overview

**Creative North Star: "O Espécime Tipográfico"**

A tipografia é a interface. Uma única fonte variável, Bricolage Grotesque, carrega a hierarquia inteira pelos eixos de largura (75% a 100%) e peso (200 a 800): o que importa fica largo e pesado, o que é contexto fica condensado e leve. O assunto da mensagem vira cartaz enquanto se digita (800, 54px, largura 100%) e condensa ao encher, até 75% de largura e 42% do tamanho base. O resto da tela se cala para que isso aconteça: papel branco-azulado, tinta quase preta, hairlines de 1px e um único azul.

O sistema é um webmail clássico (menu lateral, lista densa, modal de escrita com prévia ao lado) lido como espécime. A densidade é de ferramenta de uso diário: linhas de 44px, texto de 15px, números e datas em mono. O sistema recusa o webmail genérico de cápsulas cinza e o creme com serifa. Não há ilustração nem imagem decorativa; a cor de alias (um quadrado de 14px) é a única marca visual por conta.

Observação de divergência: o contrato previa modal de 1020px com via de prévia fixa de 420px. O build entrega modal de até 1280px e a prévia ocupa 46% (mínimo 440px; 44% e 380px abaixo de 1180px de largura). Vale o build.

**Key Characteristics:**
- Uma família variável para tudo; mono apenas para dado.
- Um azul de ação; vermelho só para falha.
- Hairlines em vez de sombras; profundidade só no modal, no aviso e na folha da prévia.
- Botões e campos de busca em pílula; campos, menus e blocos em raio 6px.
- Linhas densas de 44px, margem de página de 28px.

## Colors

Papel frio, tinta densa, um azul de fundição. Cores de estado (verde, âmbar, vermelho) existem só como selos e faixas, sempre em par texto forte e fundo fraco.

### Primary
- **Azul de Fundição** (`acao`): único agente de ação. Botão primário, Escrever, links, anel de foco, cursor de texto, item ativo do menu (em `acao-escura` sobre `acao-fraca`), botão ativo do Trix.
- **Azul de Fundição Escuro** (`acao-escura`): hover do primário e texto do item ativo.
- **Névoa de Azul** (`acao-fraca`): fundo de item ativo, halo de foco de 3px, seleção de texto, fundo de `code`.

### Secondary
- **Vermelho de Falha** (`erro`, fundo `erro-fraco`): só quando algo falhou: selo, bloco de alias da linha que falhou, faixa de erro, erros de campo, aviso de erro, estado de erro da prévia.
- **Verde de Entregue** (`ok`, `ok-fraco`): selo "enviado" e indicador "prévia em dia".
- **Âmbar de Fila** (`fila`, `fila-fraco`): selo "agendado".

### Neutral
- **Papel Azulado** (`papel`): fundo da página, topo do modal, grupos da barra do Trix.
- **Superfície** (`superficie`): campos, modal, rodapé de ações, linha em hover.
- **Tinta** (`tinta`): texto, contorno de botão secundário, fundo do aviso.
- **Tinta 2** (`tinta-2`): menu, rótulos secundários. **Mudo** (`mudo`): datas, notas, placeholders.
- **Linha** (`linha`) e **Linha Forte** (`linha-forte`): hairlines e contorno de campo.
- Blocos de alias usam `oklch(58% .16 H)` com H derivado do slug por crc32; é cor de dado, não token de marca.

### Named Rules
**The One Blue Rule.** Só o azul age. Nenhum segundo acento, nenhum botão colorido por categoria.
**The Red Means Failed Rule.** O vermelho não decora nem enfatiza: aparece apenas onde algo falhou ou é destrutivo em hover.
**The Alias Swatch Rule.** A identidade de uma conta é um bloco de 14px com matiz fixo por slug, nunca avatar nem iniciais.

## Typography

**Display Font:** Bricolage Grotesque, variável, auto-hospedada (com Segoe UI, system-ui, sans-serif)
**Body Font:** Bricolage Grotesque (mesma)
**Label/Mono Font:** Spline Sans Mono (com ui-monospace, Menlo, Consolas), 300 a 700

**Character:** Um grotesco de traço humano que muda de corpo conforme a largura: condensado e pesado para títulos, normal para leitura. O mono entra seco, tabular, só onde há dado.

### Hierarchy
- **Cartaz** (800, 54px, 1.05, largura 75 a 100%): o campo de assunto. Largura cai 1,8 ponto por caractere acima de 12; tamanho encolhe a partir de 26 caracteres, piso em 42% do base.
- **Display** (800, clamp(56px, 12vw, 84px), 0.95, largura 75%): título da tela de entrada.
- **Headline** (800, 36px, 1, largura 75%): título de página nas listas. Detalhe de mensagem: 800, clamp(30px, 4vw, 46px), 1.04, largura 78%. Estado vazio: 800, 26px.
- **Marca** (800, 28px, largura 75%): nome no menu.
- **Title** (700, 14 a 18px): títulos de seção e da via de prévia.
- **Body** (400, 15px, 1.5): texto geral; editor Trix em 16px/1.65. Notas em 14px/mudo, limite de 60 a 65ch.
- **Label** (600, 14 a 15px): rótulos de campo, botões, resumos de `details`.
- **Dado** (mono 500, 12px, tabular-nums): datas, contagens, tamanho de anexo, estado de salvamento.
- Na lista, assunto em 600, trecho em 300 com largura 85%, remetente em 700.

### Named Rules
**The Width Is Weight Rule.** Hierarquia se faz com largura e peso da mesma fonte; não se adiciona segunda família de texto.
**The Mono Is Data Rule.** Mono só para datas, contagens, tamanhos e código. Nunca em rótulo ou botão.

## Layout

Casca em grade de duas colunas: menu fixo de 248px (sticky, 100vh) e área principal fluida. O menu abriga marca, botão Escrever, itens (Enviados, Agendados, Rascunhos), grupo de configurações e rodapé com Sair. Cada página tem uma cabeça de no mínimo 72px com título, total em mono e busca em pílula de até 340px à direita, e conteúdo sem contêiner: listas vão de borda a borda com recuo de 28px.

A lista é uma grade de cinco colunas: bloco de alias 14px, remetente (120 a 190px), texto (assunto + trecho, elipse), estado, data (132px). Linhas de 44px, borda inferior de 1px. A linha inteira é um link; ações (botões ícone de 36px) substituem estado e data em hover ou foco. Telas de leitura têm largura máxima de 980px.

O modal de escrita é uma grade de duas colunas: escrita à esquerda, via de prévia à direita (46%, mínimo 440px), com topo de largura total e rodapé de ações abaixo da escrita. Cada campo de cabeçalho é uma linha de rótulo de 64px mais entrada sem caixa. Ritmo de espaçamento: 4, 8, 10, 12, 16, 24 e 28px.

Responsivo: até 1180px a via estreita (44%, 380px). Até 900px o menu vira barra horizontal no topo, a lista empilha em duas linhas, ações de linha somem e o modal ocupa a tela inteira com abas Escrever e Prévia (aba ativa marcada por traço de 3px em azul). Até 560px a lista de metadados vira coluna única.

## Elevation & Depth

Plano por padrão, separado por hairlines de 1px e por troca tonal (papel, superfície, fundo `#eceef3` da via de prévia). Sombra aparece só em três lugares: o modal (`0 28px 70px -14px rgb(14 14 18 / .5)` com anel de 1px), o aviso (`0 10px 30px -8px rgb(14 14 18 / .45)`) e a folha da prévia, que é papel branco sobre fundo cinza-azulado (`0 1px 2px rgb(14 14 18 / .12), 0 6px 18px -10px rgb(14 14 18 / .3)`). Menus de diálogo do Trix usam `0 12px 32px -10px rgb(14 14 18 / .3)`. O foco de campo é um halo de 3px em `acao-fraca` mais borda azul.

### Named Rules
**The Hairline Rule.** Superfícies de página se separam por linha de 1px e tom, nunca por sombra.
**The Float Only Rule.** Sombra difusa e suave é exclusiva do que flutua sobre a página: modal, aviso, diálogo do editor.

## Shapes

Duas famílias de forma. Ação e filtro são pílulas (999px): botões, Escrever, busca, selos de estado. Estrutura é raio curto: 6px em campos, itens de menu, botões de ícone, faixas de erro, segmentos e quadro de corpo; 4px em `code`; 3px no bloco de alias; 10px no aviso; 14px no modal. Selos têm contorno de 1px na cor do estado; "cancelado" é riscado e "rascunho" tem contorno tracejado. Ícones são SVG de traço (20px, traço 1.75, pontas redondas) de um sprite inline.

## Components

### Buttons
- **Shape:** pílula (999px), 10px 20px, 600/15px.
- **Primary:** fundo `acao`, texto branco; hover em `acao-escura`. Desabilitado: fundo `linha`, texto `mudo`.
- **Secondary (padrão):** transparente, contorno de 1px em `tinta`; hover escurece 6%.
- **Link / ícone:** sem contorno, raio 6px, hover cinza 7%; variante de perigo vai a `erro-fraco` e `erro` em hover. Ícone: 36x36px.
- **Foco:** contorno de 2px em `acao`, deslocado 2px. Transição de cor de 120 a 150ms.

### Menu lateral
Itens de 9px 12px, ícone de 20px e rótulo, contagem em mono à direita. Ativo: fundo `acao-fraca`, texto `acao-escura`, peso 700, marcado com `aria-current="page"`.

### Lista de mensagens
Linha densa de 44px descrita em Layout. Hover e foco trazem fundo de superfície; foco de teclado desenha contorno de 2px por dentro da linha. Selo de estado em pílula: enviado (verde), falhou (vermelho com fundo), enviando (mudo), agendado (âmbar), cancelado (riscado), rascunho (tracejado).

### Inputs / Fields
- **Style:** contorno de 1px em `linha-forte`, fundo superfície, raio 6px, 10px 12px.
- **Focus:** borda `acao` e halo de 3px `acao-fraca`; no cabeçalho do modal e no editor o foco é uma linha azul de 1 a 2px na base, sem caixa.
- **Error:** bloco `erro-fraco` com texto `erro` abaixo do campo.

### Assunto-cartaz
Campo sem caixa, 800, 54px, que reage ao comprimento por custom properties (`--assunto-larg`, `--assunto-tam`) com transição de largura de 150ms. É a assinatura do sistema.

### Via de prévia
Coluna de fundo `#eceef3` com título, segmentos (controle segmentado, selecionado em superfície com sombra de 1px) para largura e HTML/texto, e a folha branca. Indicador "em dia / atualizando / erro" no rodapé de ações (ponto de 8px que pulsa ao atualizar). O envio depende da prévia em dia.

### Aviso (toast)
Faixa escura (`tinta`; `erro` em falha), raio 10px, canto inferior esquerdo; dentro do modal sobe para o topo central para não cobrir Enviar. Entra em 280ms com `cubic-bezier(.16, 1, .3, 1)`.

### Barra do Trix
Grupos achatados em fundo papel, botões de 32px separados por hairline, hover `acao-fraca`, ativo em `acao` com ícone invertido. Anexo nativo do Trix oculto; anexos têm lista própria.

## Do's and Don'ts

### Do:
- **Do** hierarquizar com largura e peso de Bricolage Grotesque (75% a 100%, 200 a 800) antes de pensar em cor ou tamanho.
- **Do** usar `acao` (#2a35ff) como única cor de ação e `erro` apenas para falha.
- **Do** compor texto de estado em par: cor forte sobre o fundo fraco correspondente.
- **Do** separar áreas com hairline de 1px em `linha`; reservar sombra a modal, aviso e diálogos.
- **Do** manter botões e busca em pílula e todo o resto em raio 6px (modal 14px).
- **Do** mostrar datas, contagens e tamanhos em Spline Sans Mono 12px com numerais tabulares.
- **Do** respeitar `prefers-reduced-motion`: toda animação reduz a 0,01ms.
- **Do** manter o foco visível: contorno de 2px em `acao` ou linha azul na base nos campos sem caixa.

### Don't:
- **Don't** introduzir um segundo acento, gradiente ou botão colorido por categoria.
- **Don't** usar o vermelho como ênfase ou decoração.
- **Don't** adicionar uma segunda família de texto; o mono nunca entra em rótulos ou botões.
- **Don't** voltar às cápsulas cinza de webmail genérico nem ao creme com serifa.
- **Don't** usar avatares, iniciais ou ícones de fonte para contas; use o bloco de alias de 14px e o sprite SVG existente.
- **Don't** empilhar sombras em cartões de página; superfícies de página são planas.
- **Don't** fazer o aviso cobrir o botão Enviar dentro do modal.
- **Don't** traduzir a prévia em nada que não seja o que o destinatário recebe: a folha é branca, sem estilo do app dentro.

_Não canonizado: nenhum defeito estrutural observado. Pendências do build (não regras): o CSS de telas estreitas declara `.menu` duas vezes (flex-wrap e overflow redundantes) e há regras soltas no fim do arquivo fora da ordem de seções; o contrato descrevia modal de 1020px e prévia de 420px, e o build usa 1280px e 46%._

## Atualização: caixas, configurações e celular

Acréscimos posteriores ao primeiro registro; o detector ainda os lista como fora da escala
dos tokens acima, e é por isso que estão escritos aqui.

- **Cor da caixa:** o bloco de 14px de cada linha usa `oklch(58% .16 <matiz>)`, com o matiz
  vindo do domínio do endereço de saída entre sete valores fixos (55, 150, 180, 215, 255,
  290, 325), nunca o vermelho (reservado para falha). "Todas as caixas" usa um conic-gradient
  com quatro desses matizes.
- **Texto pequeno de apoio:** 13px (dicas de campo, rótulos do menu, botões segmentados);
  títulos de seção de configuração em 17px e `font-stretch: 85%`; o título da página cai de
  36px para 32px no celular.
- **Raios:** 8px nos botões segmentados e na cifra (dentro do contêiner de 10px) e 3px nos
  blocos de cor; todo o resto segue 6/14/pílula.
- **Celular (até 900px):** barra fixa de 56px com a gaveta de navegação, alvos de toque de
  44px, ações da fila sempre visíveis, assunto em 34px, o modal de escrita em tela cheia com
  abas Escrever/Prévia.
