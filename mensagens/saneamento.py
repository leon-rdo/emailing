"""Preparo do HTML para envio: CSS embutido nos elementos, depois limpeza.

Duas etapas, nesta ordem, e a ordem importa:

1. **Embutir o CSS** (`css-inline`). Um template de e-mail de verdade vem com
   as regras num `<style>` e classes nos elementos — e é assim que ele quebra
   no Outlook, que ignora boa parte do CSS de folha. Toda ferramenta séria de
   e-mail transforma essas regras em `style="…"` em cada elemento antes de
   mandar; é o denominador comum que todo cliente entende. O `<style>`
   original é mantido, porque `@media` (o responsivo) não tem como virar
   inline.

2. **Limpar** (`nh3`). Mata `<script>`, `<iframe>`, `<form>`, manipuladores
   `on*` e tags fora da lista (o `<o:p>` do Word entre elas).

   O que **não** é mais removido, desde que o passo 1 existe: `class` e o
   `<style>`, porque as media queries preservadas miram as classes — tirar uma
   sem a outra quebraria o responsivo. Propriedades CSS individuais também
   passam (o nh3 é tudo-ou-nada por tag no `style`), então `mso-*` colado do
   Word sobrevive: feio, inofensivo, e o preço de aceitar template de verdade.

Sem a etapa 1, a etapa 2 apagava o `<style>` e as `class` e o e-mail chegava
sem formatação nenhuma — que é exatamente o que acontecia antes disto existir.

A assinatura de cada alias **não passa por aqui** — ver `montagem.py`.
"""

from __future__ import annotations

import html
import re

import css_inline
import nh3

_TAGS = {
    "p", "div", "br", "span", "strong", "b", "em", "i", "u", "s", "del", "ins", "a",
    "ul", "ol", "li", "blockquote", "pre", "code",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "img",
    # <style> sobrevive por causa das media queries; ver o cabeçalho do módulo.
    "style", "center", "font",
}

# nh3 não filtra propriedades CSS: "style" é tudo-ou-nada por tag (ver
# CLAUDE.md). Aceitável aqui porque quem escreve o corpo é o único usuário do
# app; seria inaceitável num app multi-inquilino.
#
# "rel" fica de fora de propósito: com link_rel definido abaixo, o nh3 recusa
# que "rel" também apareça em `attributes` (ele quem passa a gerenciar esse
# atributo sozinho).
_ATRIBUTOS = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height", "border"},
    "td": {"colspan", "rowspan", "align", "valign", "width", "height", "bgcolor"},
    "th": {"colspan", "rowspan", "align", "valign", "width", "height", "bgcolor"},
    "tr": {"align", "valign", "bgcolor"},
    "table": {
        "width", "height", "cellpadding", "cellspacing", "border", "role", "align", "bgcolor",
    },
    "font": {"color", "face", "size"},
    # `class` fica junto do `style` porque as media queries preservadas no
    # <style> continuam mirando as classes — tirar uma sem a outra quebraria
    # o responsivo.
    "*": {"style", "class", "id", "dir", "lang"},
}

_ESQUEMAS_URL = {"http", "https", "mailto", "tel", "cid"}

# Tag removida COM o conteúdo. Sem estar aqui, o nh3 tira só a tag e mantém o
# texto — o que é o certo para `<span>`, e desastroso para `<title>`: o título
# do documento vazava como primeira linha visível do e-mail (visto num envio
# real, "Email de Teste - Plataforma de Emailing" antes do conteúdo).
#
# `style` NÃO entra aqui, porque queremos manter o `<style>` pelas media
# queries — e o nh3 recusa (com panic) se a mesma tag aparecer nas duas listas.
_TAGS_REMOVIDAS_COM_CONTEUDO = {
    "script", "iframe", "object", "embed", "form", "noscript",
    # Tudo que pertence ao <head> de um documento e não é conteúdo de e-mail.
    "title", "head", "meta", "link", "base", "template",
}

# O css-inline aplica as regras que casam com `*` em todo elemento — inclusive
# no próprio `<style>`, que sai com um `style="…"` inútil. Não afeta a
# renderização (a tag não é desenhada), mas suja quem abrir "ver original".
_ATRIBUTO_EM_STYLE = re.compile(r"(<style)\s+[^>]*?(>)", re.IGNORECASE)


def embutir_css(bruto: str) -> str:
    """Transforma as regras do `<style>` em `style="…"` em cada elemento.

    Nunca deixa a preparação do e-mail falhar por causa de um CSS malformado:
    se o inliner reclamar, segue com o HTML como veio (o `<style>` ainda é
    preservado pela limpeza adiante, então clientes que leem folha de estilo
    continuam funcionando).
    """
    try:
        return css_inline.inline(bruto, keep_style_tags=True)
    except Exception:
        return bruto


def limpar_html(bruto: str) -> str:
    """HTML do editor (ou colado) → HTML pronto para enviar."""
    if not bruto or not bruto.strip():
        return ""
    limpo = nh3.clean(
        embutir_css(bruto),
        tags=_TAGS,
        attributes=_ATRIBUTOS,
        clean_content_tags=_TAGS_REMOVIDAS_COM_CONTEUDO,
        url_schemes=_ESQUEMAS_URL,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )
    return _ATRIBUTO_EM_STYLE.sub(r"\1\2", limpo).strip()


# --- HTML → texto simples, para a parte multipart/alternative --------------
#
# ~30 linhas de stdlib. Não precisa ser bonito, precisa ser legível: e-mail
# só-HTML tem penalidade mensurável em filtro de spam.

# O <style> sobrevive à limpeza (media queries), mas aqui o conteúdo dele é
# código, não texto — sem isto as regras CSS apareceriam cruas na parte em
# texto simples do e-mail.
_BLOCO_DE_ESTILO = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_LINK = re.compile(r'<a\b[^>]*\bhref="([^"]*)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_ITEM_LISTA = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_QUEBRA_DE_BLOCO = re.compile(
    r"</?(p|div|br|li|ul|ol|h[1-6]|tr|table|blockquote|hr)\b[^>]*>", re.IGNORECASE
)
_QUALQUER_TAG = re.compile(r"<[^>]+>")
_ESPACOS_REPETIDOS = re.compile(r"[ \t]+")
_LINHAS_EM_BRANCO_REPETIDAS = re.compile(r"\n{3,}")

# Marcadores fora da faixa Unicode de uso privado: seguram a URL do link
# durante a etapa de remoção de tags, para que "<https://…>" não seja
# confundido com uma tag de verdade por _QUALQUER_TAG e apagado junto.
_MARCA_ABRE, _MARCA_FECHA = "", ""


def _substituir_link(m: re.Match) -> str:
    url = m.group(1)
    rotulo = _QUALQUER_TAG.sub("", m.group(2)).strip()
    marcada = f"{_MARCA_ABRE}{url}{_MARCA_FECHA}"
    return f"{rotulo} {marcada}" if rotulo and rotulo != url else marcada


def html_para_texto(html_bruto: str) -> str:
    """Aproximação simples e legível do HTML em texto simples."""
    if not html_bruto:
        return ""

    texto = _BLOCO_DE_ESTILO.sub("", html_bruto)
    texto = _LINK.sub(_substituir_link, texto)
    texto = _ITEM_LISTA.sub("\n- ", texto)
    texto = _QUEBRA_DE_BLOCO.sub("\n", texto)
    texto = _QUALQUER_TAG.sub("", texto)
    texto = texto.replace(_MARCA_ABRE, "<").replace(_MARCA_FECHA, ">")
    texto = html.unescape(texto)
    texto = _ESPACOS_REPETIDOS.sub(" ", texto)
    linhas = [linha.strip() for linha in texto.splitlines()]
    texto = "\n".join(linhas)
    texto = _LINHAS_EM_BRANCO_REPETIDAS.sub("\n\n", texto)
    return texto.strip()
