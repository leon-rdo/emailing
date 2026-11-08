"""Extrai de um `.eml`/`.txt` o que é preciso para responder com threading
correto: `In-Reply-To`, `References`, destinatário e assunto sugeridos, e o
trecho original já sanitizado para citação.

Trabalha só sobre bytes limitados, em memória — a correspondência importada é
de terceiros (ver `views.importar_eml`, que força `MemoryFileUploadHandler`
para nunca tocar o disco).
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from email.utils import formataddr, getaddresses

from .saneamento import limpar_html

_BOM_UTF8 = b"\xef\xbb\xbf"

# Um Message-ID é "<algo@algo>"; usado para separar um cabeçalho References
# dobrado em várias linhas em identificadores individuais — nunca com
# .split(" "), que quebra fácil com espaçamento irregular.
_TOKEN_MSGID = re.compile(r"<[^<>@\s]+@[^<>\s]+>")

# Prefixos de resposta/encaminhamento em português e inglês. RES:/ENC: são o
# que o Outlook em pt-BR usa — Re:/Fwd: sozinhos não cobrem esse caso.
_PREFIXO_ASSUNTO = re.compile(r"^\s*(re|res|enc|fwd|fw)(\[\d+\])?\s*:\s*", re.IGNORECASE)

MAX_REFERENCIAS = 20


class ErroImportacaoEML(Exception):
    """A mensagem já é o texto pronto para mostrar ao usuário."""


@dataclass
class EmailImportado:
    message_id: str = ""
    referencias: str = ""
    assunto: str = ""
    para: str = ""
    citacao_html: str = ""
    avisos: list[str] = field(default_factory=list)


def normalizar_message_id(bruto: str) -> str:
    """Garante exatamente um par de `<>`, sem espaço interno, ou string vazia."""
    valor = (bruto or "").strip()
    if not valor:
        return ""
    if not valor.startswith("<"):
        valor = f"<{valor}"
    if not valor.endswith(">"):
        valor = f"{valor}>"
    return valor


def _assunto_com_re(bruto: str) -> str:
    """Remove TODOS os prefixos existentes e prefixa exatamente um "Re: "."""
    atual = bruto
    while True:
        novo = _PREFIXO_ASSUNTO.sub("", atual, count=1)
        if novo == atual:
            break
        atual = novo
    return f"Re: {atual}" if atual else "Re:"


def _endereco_de_resposta(msg) -> str:
    """"Para" da resposta: prefere `Reply-To`; sem ele, cai no `From`."""
    for cabecalho in ("Reply-To", "From"):
        bruto = str(msg.get(cabecalho, ""))
        for nome, endereco in getaddresses([bruto]):
            if endereco and "@" in endereco:
                return formataddr((nome, endereco)) if nome else endereco
    return ""


def _referencias_do_original(msg) -> list[str]:
    """IDs do `References` do original — semeado de `In-Reply-To` quando
    `References` falta (RFC 5322 §3.6.4) — sem duplicatas, preservando ordem."""
    bruto = " ".join(str(v) for v in msg.get_all("References", []))
    ids = _TOKEN_MSGID.findall(bruto)
    if not ids:
        semente = normalizar_message_id(str(msg.get("In-Reply-To", "")))
        if semente:
            ids = [semente]
    vistos: set[str] = set()
    unicos = []
    for id_ in ids:
        if id_ not in vistos:
            vistos.add(id_)
            unicos.append(id_)
    return unicos


def referencias_para_resposta(referencias_originais: list[str], message_id: str) -> str:
    """`References` do original + `Message-ID` do original, por último, sem
    duplicar (nem entre si nem repetindo o `message_id`), e limitado a
    `MAX_REFERENCIAS` (mantendo o primeiro e os últimos — é o primeiro da
    thread que mais importa preservar)."""
    vistos: set[str] = set()
    cadeia = []
    for id_ in referencias_originais:
        if id_ and id_ != message_id and id_ not in vistos:
            vistos.add(id_)
            cadeia.append(id_)
    if message_id:
        cadeia.append(message_id)
    if len(cadeia) > MAX_REFERENCIAS:
        cadeia = [cadeia[0], *cadeia[-(MAX_REFERENCIAS - 1):]]
    return " ".join(cadeia)


def _corpo_citado(msg) -> str:
    corpo = msg.get_body(preferencelist=("html", "plain")) if hasattr(msg, "get_body") else None
    if corpo is None:
        return ""

    try:
        conteudo = corpo.get_content()
    except (LookupError, UnicodeError, ValueError):
        bruto = corpo.get_payload(decode=True) or b""
        conteudo = bruto.decode(corpo.get_content_charset() or "utf-8", errors="replace")

    if corpo.get_content_type() == "text/plain":
        conteudo = f"<pre>{_html.escape(conteudo)}</pre>"
    return limpar_html(conteudo)


def analisar_eml(bruto: bytes) -> EmailImportado:
    """Levanta `ErroImportacaoEML` quando o arquivo não parece um e-mail."""
    if bruto.startswith(_BOM_UTF8):
        bruto = bruto[len(_BOM_UTF8):]

    try:
        msg = BytesParser(policy=policy.default).parsebytes(bruto)
    except Exception as exc:  # o parser da stdlib não documenta um tipo só
        raise ErroImportacaoEML(
            "Não consegui ler este arquivo como e-mail. Exporte o .eml de verdade "
            "do seu cliente de e-mail (não copie e cole o texto)."
        ) from exc

    resultado = EmailImportado()
    resultado.para = _endereco_de_resposta(msg)

    assunto_bruto = str(msg.get("Subject", "")).strip()
    resultado.assunto = _assunto_com_re(assunto_bruto) if assunto_bruto else ""

    if not resultado.para and not assunto_bruto:
        # Sintoma clássico de colagem do Outlook ("De:", "Enviada em:", "Para:")
        # em vez de um .eml de verdade: nenhum cabeçalho reconhecido.
        raise ErroImportacaoEML(
            "Não consegui reconhecer este arquivo como um e-mail. Se você colou o "
            "texto de um e-mail do Outlook, exporte o .eml de verdade em vez disso."
        )

    message_id = normalizar_message_id(str(msg.get("Message-ID", "")))
    referencias_originais = _referencias_do_original(msg)
    if message_id:
        resultado.message_id = message_id
        resultado.referencias = referencias_para_resposta(referencias_originais, message_id)
    else:
        resultado.referencias = " ".join(referencias_originais)
        resultado.avisos.append(
            "Este arquivo não tem Message-ID — a resposta não vai encadear com o "
            "e-mail original, mas o destinatário e o assunto foram preenchidos."
        )

    resultado.citacao_html = _corpo_citado(msg)
    return resultado
