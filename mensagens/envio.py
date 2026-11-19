"""Envio de verdade: conexão SMTP por alias, gravando o `RegistroEnvio`.

`status=ENVIANDO` é gravado **antes** da chamada SMTP — é o registro de que o
envio foi tentado, e o que faz o histórico contar a verdade mesmo se o
processo morrer no meio da chamada de rede em vez de simplesmente falhar.

Depois que o SMTP aceita, a mensagem é copiada na pasta de enviados da caixa por
IMAP (`_copiar_em_enviados`): o SMTP não grava cópia, e sem isso o e-mail não
aparece no "Enviados" do webmail.
"""

from __future__ import annotations

import logging
from email.utils import make_msgid
from smtplib import SMTPException

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.utils import DNS_NAME

from . import caixa
from .anexos import ler_anexos, limpar_rascunho
from .models import Alias, RegistroEnvio
from .montagem import DadosRedacao, montar_email

logger = logging.getLogger(__name__)


def _fixar_nome_no_ehlo(dominio: str) -> None:
    """Faz o SMTP se apresentar com o domínio do remetente.

    Sem isto o Django usa `socket.getfqdn()` no EHLO, que numa VPS vira algo
    como `vmi2934480` — alguns MTAs pontuam mal quem se apresenta assim. É por
    envio, e não no boot, porque cada conta pode estar num domínio diferente.
    """
    DNS_NAME._fqdn = dominio


def _copiar_em_enviados(alias: Alias, mensagem, message_id: str) -> None:
    """Melhor-esforço: a mensagem **já saiu**, então nada aqui pode virar falha de envio.

    Sem `imap_host` não há o que fazer (a caixa é só de envio), e a conta pode ter
    desligado a cópia (`guardar_enviados`: o provedor já guarda). Qualquer erro vira
    aviso no log — o `RegistroEnvio` continua `ENVIADO`, que é a verdade.
    """
    conta = alias.conta
    if not conta.imap_host or not conta.guardar_enviados:
        return
    try:
        copia = mensagem.message()
        if mensagem.bcc:  # o Django tira o Bcc do que sai; na cópia de quem enviou ele aparece
            copia["Bcc"] = ", ".join(mensagem.bcc)
        pasta = caixa.guardar_em_enviados(conta, copia.as_bytes())
    except Exception as exc:  # noqa: BLE001 — ver docstring: nada pode derrubar um envio feito
        logger.warning(
            "Enviado %s, mas não consegui guardar em Enviados de %s: %s",
            message_id, conta.usuario, exc,
        )
    else:
        logger.info("Cópia de %s guardada em %r de %s", message_id, pasta, conta.usuario)


def enviar_email(alias: Alias, dados: DadosRedacao, token_anexos: str = "") -> RegistroEnvio:
    """Monta, registra e envia. Nunca levanta — o status do retorno é a resposta."""
    message_id = make_msgid(domain=alias.dominio_message_id)
    _fixar_nome_no_ehlo(alias.dominio_message_id)
    anexos = ler_anexos(token_anexos)
    mensagem = montar_email(dados, alias, anexos=anexos, message_id=message_id)
    html_final = mensagem.alternatives[0][0]

    registro = RegistroEnvio.objects.create(
        alias=alias.slug,
        remetente=mensagem.extra_headers["From"],
        para=", ".join(dados.para),
        cc=", ".join(dados.cc),
        cco=", ".join(dados.cco),
        assunto=dados.assunto,
        message_id=message_id,
        in_reply_to=dados.in_reply_to,
        referencias=dados.referencias,
        status=RegistroEnvio.Status.ENVIANDO,
        anexos=[{"nome": a.nome, "tamanho": len(a.conteudo), "tipo": a.tipo} for a in anexos],
        corpo_html=html_final if settings.GUARDAR_CORPO_ENVIADO else "",
    )

    mensagem.connection = get_connection(**alias.smtp)
    try:
        mensagem.send()
    except (SMTPException, OSError) as exc:
        logger.warning("Falha ao enviar %s via alias %s: %s", message_id, alias.slug, exc)
        registro.status = RegistroEnvio.Status.FALHOU
        registro.erro = str(exc)
        registro.save(update_fields=["status", "erro"])
        return registro

    registro.status = RegistroEnvio.Status.ENVIADO
    registro.save(update_fields=["status"])
    _copiar_em_enviados(alias, mensagem, message_id)
    limpar_rascunho(token_anexos)
    return registro
