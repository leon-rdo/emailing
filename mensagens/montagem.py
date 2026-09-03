"""Monta o e-mail a partir dos dados do formulário.

`montar_email` é uma função pura: dados os mesmos `dados` e o mesmo `alias`,
sempre produz a mesma mensagem (module `message_id` à parte, que quem chama
passa explicitamente só quando quer persistir — ver `envio.py`). É essa pureza
que permite a prévia e o envio compartilharem o mesmo caminho de código, em vez
de a prévia depender de um rascunho guardado em algum lugar que pode divergir
do que de fato sai (ver `views.redigir` e `CLAUDE.md`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from django.core.mail import EmailMultiAlternatives

from .aliases import Alias
from .assinaturas import assinatura_de
from .saneamento import html_para_texto, limpar_html


@dataclass
class Anexo:
    nome: str
    conteudo: bytes
    tipo: str


@dataclass
class DadosRedacao:
    para: list[str]
    cc: list[str] = field(default_factory=list)
    cco: list[str] = field(default_factory=list)
    assunto: str = ""
    corpo_html: str = ""      # HTML bruto do editor, ainda não sanitizado
    citacao_html: str = ""    # HTML já sanitizado do trecho citado (Etapa 8)
    in_reply_to: str = ""
    referencias: str = ""


def montar_corpo(dados: DadosRedacao, alias: Alias) -> tuple[str, str]:
    """(html_final, texto_final): corpo sanitizado + citação + assinatura."""
    partes = [limpar_html(dados.corpo_html)]
    if dados.citacao_html:
        partes.append(f"<blockquote>{dados.citacao_html}</blockquote>")

    # A assinatura NÃO passa pelo sanitizador: é conteúdo do operador, num
    # arquivo que só quem tem ssh na máquina escreve. Sanitizá-la não protege
    # de nada e só pode destruir o layout em <table> e os estilos inline.
    assinatura = assinatura_de(alias)
    if assinatura:
        partes.append(assinatura)

    html_final = "\n".join(p for p in partes if p)
    return html_final, html_para_texto(html_final)


def calcular_hash_previa(dados: DadosRedacao, alias: Alias, html_final: str,
                          ids_anexos: list[str] = ()) -> str:
    """Assinatura de tudo que define o envio — não só o corpo.

    Comparada no momento do envio: se o corpo, os anexos, o alias ou QUALQUER
    destinatário/assunto mudaram desde a última prévia, o envio é recusado e a
    prévia é refeita — sem guardar rascunho nenhum, só recalculando sobre o
    mesmo POST. Cobrir só o HTML final (como uma versão anterior deste código
    fazia) deixaria passar batido, por exemplo, trocar o destinatário depois
    de pré-visualizar e antes de clicar Enviar.
    """
    material = "|".join([
        alias.slug,
        ",".join(dados.para), ",".join(dados.cc), ",".join(dados.cco),
        dados.assunto, html_final, ",".join(sorted(ids_anexos)),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def montar_email(
    dados: DadosRedacao,
    alias: Alias,
    *,
    anexos: list[Anexo] = (),
    message_id: str = "",
) -> EmailMultiAlternatives:
    html_final, texto_final = montar_corpo(dados, alias)

    headers = {"From": alias.remetente}
    if message_id:
        headers["Message-ID"] = message_id
    if dados.in_reply_to:
        headers["In-Reply-To"] = dados.in_reply_to
    if dados.referencias:
        headers["References"] = dados.referencias

    mensagem = EmailMultiAlternatives(
        subject=dados.assunto,
        body=texto_final,
        # from_email é o envelope (MAIL FROM); o cabeçalho From: vem de
        # headers["From"] acima — os dois levers são independentes no Django.
        from_email=alias.envelope,
        to=dados.para,
        cc=dados.cc,
        bcc=dados.cco,
        reply_to=[alias.reply_to] if alias.reply_to else None,
        headers=headers,
    )
    mensagem.attach_alternative(html_final, "text/html")
    for anexo in anexos:
        mensagem.attach(anexo.nome, anexo.conteudo, anexo.tipo)
    return mensagem
