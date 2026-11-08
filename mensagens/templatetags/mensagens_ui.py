"""Filtros só de apresentação — nada aqui decide o que é enviado."""

import html
import re
import zlib

from django import template
from django.utils import timezone
from django.utils.html import strip_tags

register = template.Library()


# Matizes que um alias pode ter. Fora o vermelho (10–40) de propósito: vermelho é
# a cor de "falhou", e um alias vermelho esconderia um envio que deu errado.
_MATIZES = (55, 150, 180, 215, 255, 290, 325)


@register.filter
def matiz(slug) -> int:
    """Matiz estável para um alias: o bloco de cor que o identifica na lista.

    `crc32` e não `hash()`: o `hash()` de string muda a cada processo, e o alias
    mudaria de cor a cada reinício do gunicorn.
    """
    return _MATIZES[zlib.crc32(str(slug).encode()) % len(_MATIZES)]


@register.filter
def trecho(corpo_html, tamanho=110) -> str:
    """Primeiras palavras do corpo, sem marcação, para a linha da lista.

    O texto sai escapado de novo pelo autoescape do template; `html.unescape`
    só desfaz as entidades (`&nbsp;`, `&amp;`) que o `strip_tags` deixa.
    """
    # Troca a marcação por espaço antes: `<br>` e `</p>` somem no `strip_tags`
    # e "Ana<br>Souza" viraria "AnaSouza".
    texto = html.unescape(strip_tags(re.sub(r"<[^>]+>", " ", corpo_html or "")))
    texto = " ".join(texto.split())
    tamanho = int(tamanho)
    return texto if len(texto) <= tamanho else texto[: tamanho - 1].rstrip() + "…"


@register.filter
def primeiro_destinatario(valor) -> str:
    """O primeiro endereço de "a@x.com, b@y.com" (ou de uma lista), com `+N` do resto.

    A lista mostra uma pessoa por linha, como um webmail; o resto vai no `title`.
    """
    if isinstance(valor, str):
        itens = [p.strip() for p in valor.split(",") if p.strip()]
    else:
        itens = [str(p).strip() for p in (valor or []) if str(p).strip()]
    if not itens:
        return "sem destinatário"
    primeiro = itens[0]
    # "Nome <a@b.com>" → "Nome"
    if "<" in primeiro and primeiro.split("<")[0].strip():
        primeiro = primeiro.split("<")[0].strip().strip('"')
    return primeiro if len(itens) == 1 else f"{primeiro} +{len(itens) - 1}"


@register.filter
def quando(momento) -> str:
    """Data curta para a lista: "hoje 14:32", "ontem 09:10", "21/10 16:00".

    Relativa ao dia local, nos dois sentidos — a fila de agendados fala de
    "amanhã 08:00". Passando de um ano para qualquer lado, o ano aparece.
    """
    if not momento:
        return ""
    local = timezone.localtime(momento)
    hoje = timezone.localdate()
    dias = (local.date() - hoje).days
    hora = local.strftime("%H:%M")
    if dias == 0:
        return f"hoje {hora}"
    if dias == -1:
        return f"ontem {hora}"
    if dias == 1:
        return f"amanhã {hora}"
    if abs(dias) > 300:
        return local.strftime("%d/%m/%Y")
    return local.strftime(f"%d/%m {hora}")


@register.filter
def dominio_de(valor) -> str:
    """O domínio de "Nome <a@b.com>" ou "a@b.com": o que agrupa as caixas na lista."""
    texto = str(valor or "")
    if "<" in texto:
        texto = texto.rsplit("<", 1)[1].rstrip(">")
    return texto.rpartition("@")[2].strip().lower()


@register.filter
def endereco_de(valor) -> str:
    """O endereço puro de "Nome <a@b.com>" (ou o próprio texto, se já for puro)."""
    texto = str(valor or "").strip()
    if "<" in texto:
        texto = texto.rsplit("<", 1)[1].rstrip(">")
    return texto.strip()
