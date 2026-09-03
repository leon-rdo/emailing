"""Monta o e-mail a partir dos dados do formulário.

`montar_email` é uma função pura: dados os mesmos `dados` e o mesmo `alias`,
sempre produz a mesma mensagem (o `message_id` à parte, que quem chama passa
explicitamente só quando quer persistir — ver `envio.py`). É essa pureza que
permite a prévia e o envio compartilharem o mesmo caminho de código, em vez de
a prévia depender de um rascunho guardado em algum lugar que pode divergir do
que de fato sai (ver `views.redigir` e `CLAUDE.md`).

A exceção são os marcadores (`{{ data }}`, `{{ hora }}`…), que por definição
mudam com o relógio. Por isso existem dois HTMLs aqui: o **autoral**, com os
marcadores intactos, e o **final**, com eles expandidos. O `hash_previa` é
sempre do autoral — se fosse do final, `{{ hora }}` mudaria sozinho entre a
prévia e o clique em Enviar, e o envio seria recusado por "o conteúdo mudou".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from django.core.mail import EmailMultiAlternatives

from .assinaturas import assinatura_de
from .marcadores import expandir
from .models import Alias
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
    """(html, texto) **autorais**: sanitizados, com os marcadores intactos.

    É esta versão que entra no `hash_previa` — ver o cabeçalho do módulo.
    Para o que de fato sai no e-mail, use `montar_corpo_final`.
    """
    partes = [limpar_html(dados.corpo_html)]
    if dados.citacao_html:
        partes.append(f"<blockquote>{dados.citacao_html}</blockquote>")

    # A assinatura NÃO passa pelo sanitizador: é conteúdo do operador,
    # cadastrado por quem administra o app. Sanitizá-la não protege de nada e
    # só pode destruir o layout em <table> e os estilos inline.
    assinatura = assinatura_de(alias)
    if assinatura:
        partes.append(assinatura)

    html_autoral = "\n".join(p for p in partes if p)
    return html_autoral, html_para_texto(html_autoral)


def montar_corpo_final(dados: DadosRedacao, alias: Alias) -> tuple[str, str]:
    """(html, texto) com os marcadores já trocados pelos valores do momento."""
    html_autoral, texto_autoral = montar_corpo(dados, alias)
    return (
        expandir(html_autoral, alias, dados, escapar_html=True),
        expandir(texto_autoral, alias, dados, escapar_html=False),
    )


def emoldurar_para_previa(html_final: str) -> str:
    """Envolve o HTML numa moldura que imita o padrão de um cliente de e-mail.

    O iframe da prévia não herda estilo nenhum, então HTML sem `font-family`
    cai na fonte padrão do navegador — serifada — e a prévia mente sobre o
    resultado: Gmail, Outlook e afins aplicam uma sans-serif. A moldura só
    existe na tela; o que é enviado é o `html_final` puro, e é ele que entra
    no hash.
    """
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        "html,body{margin:0;padding:0;}"
        "body{padding:16px;background:#fff;color:#222;"
        "font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;}"
        "</style></head><body>" + html_final + "</body></html>"
    )


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
    html_final, texto_final = montar_corpo_final(dados, alias)

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
