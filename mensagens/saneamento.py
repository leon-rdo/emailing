"""Normalização e limpeza do HTML digitado no editor.

Isto existe antes de tudo como normalizador de entregabilidade: mata o
`<o:p>`, `mso-*`, `<meta>` e a sopa de classes que chega quando se cola do Word
ou de uma página, e que quebra a renderização no Outlook e no Gmail.
Segurança é bônus.

A assinatura de cada alias **não passa por aqui** — ver `montagem.py`.
"""

from __future__ import annotations

import html
import re

import nh3

_TAGS = {
    "p", "div", "br", "span", "strong", "b", "em", "i", "u", "s", "del", "ins", "a",
    "ul", "ol", "li", "blockquote", "pre", "code",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "table", "thead", "tbody", "tfoot", "tr", "th", "td", "img",
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
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan", "align", "valign", "width"},
    "th": {"colspan", "rowspan", "align", "valign", "width"},
    "table": {"width", "cellpadding", "cellspacing", "border", "role", "align"},
    "*": {"style"},
}

_ESQUEMAS_URL = {"http", "https", "mailto", "tel", "cid"}


def limpar_html(bruto: str) -> str:
    """HTML do editor → HTML normalizado e seguro para envio."""
    if not bruto or not bruto.strip():
        return ""
    return nh3.clean(
        bruto,
        tags=_TAGS,
        attributes=_ATRIBUTOS,
        url_schemes=_ESQUEMAS_URL,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )


# --- HTML → texto simples, para a parte multipart/alternative --------------
#
# ~30 linhas de stdlib. Não precisa ser bonito, precisa ser legível: e-mail
# só-HTML tem penalidade mensurável em filtro de spam.

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

    texto = _LINK.sub(_substituir_link, html_bruto)
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
