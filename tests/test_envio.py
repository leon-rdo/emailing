"""enviar_email(): grava o RegistroEnvio antes de mandar, nunca levanta."""

import pytest
from django.core import mail
from django.test import override_settings

from mensagens.aliases import alias_por_slug
from mensagens.envio import enviar_email
from mensagens.models import RegistroEnvio
from mensagens.montagem import DadosRedacao

pytestmark = pytest.mark.django_db
DOMINIOS = override_settings(ALIAS_ALLOWED_DOMAINS=["leonardocosta.dev"])
BASE = {
    "SMTP_USER": "me@leonardocosta.dev",
    "SMTP_PASSWORD": "segredo",
    "ALIASES": "financeiro",
    "ALIAS_FINANCEIRO_ADDRESS": "financeiro@leonardocosta.dev",
    "ALIAS_FINANCEIRO_NAME": "Leonardo Costa",
}


@DOMINIOS
def test_envio_bem_sucedido(ambiente_de_aliases, settings):
    settings.MESSAGE_ID_DOMAIN = "leonardocosta.dev"
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(para=["cliente@example.com"], assunto="Oi", corpo_html="<p>Olá</p>")

    registro = enviar_email(alias, dados)

    assert registro.status == RegistroEnvio.Status.ENVIADO
    assert registro.erro == ""
    assert len(mail.outbox) == 1

    cru = mail.outbox[0].message().as_bytes()
    assert b"From: Leonardo Costa <financeiro@leonardocosta.dev>" in cru
    assert b"To: cliente@example.com" in cru
    assert b"Content-Type: multipart/alternative" in cru
    assert f"<{registro.message_id.strip('<>')}>".encode() in cru or (
        registro.message_id.encode() in cru
    )


@DOMINIOS
def test_message_id_termina_no_dominio_do_alias(ambiente_de_aliases, settings):
    settings.MESSAGE_ID_DOMAIN = ""  # vazio → cai no domínio do próprio alias
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    registro = enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"))
    assert registro.message_id.endswith("@leonardocosta.dev>")


@DOMINIOS
def test_grava_enviando_antes_de_mandar(ambiente_de_aliases, monkeypatch):
    """O status ENVIANDO existe para o histórico contar a verdade mesmo se o
    processo morrer no meio da chamada de rede — não dá pra observar isso
    depois do fato num teste síncrono, mas dá pra confirmar que o registro é
    criado ANTES do envio, interceptando o ponto de envio."""
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")

    capturado = {}
    original_send = mail.EmailMultiAlternatives.send

    def _interceptar(self, *args, **kwargs):
        capturado["status_durante_envio"] = RegistroEnvio.objects.get().status
        return original_send(self, *args, **kwargs)

    monkeypatch.setattr(mail.EmailMultiAlternatives, "send", _interceptar)

    enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"))

    assert capturado["status_durante_envio"] == RegistroEnvio.Status.ENVIANDO


@DOMINIOS
def test_falha_de_smtp_grava_status_falhou_e_nao_levanta(ambiente_de_aliases, monkeypatch):
    from smtplib import SMTPAuthenticationError

    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")

    def _quebrar(self, *args, **kwargs):
        raise SMTPAuthenticationError(535, b"credenciais invalidas")

    monkeypatch.setattr(mail.EmailMultiAlternatives, "send", _quebrar)

    registro = enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"))

    assert registro.status == RegistroEnvio.Status.FALHOU
    assert "credenciais invalidas" in registro.erro
    assert len(mail.outbox) == 0


@DOMINIOS
def test_anexos_persistidos_no_registro(ambiente_de_aliases, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from mensagens.anexos import criar_token, salvar_anexo

    settings.RASCUNHOS_DIR = tmp_path
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("nota.pdf", b"conteudo-pdf"))

    registro = enviar_email(
        alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"), token_anexos=token
    )

    assert registro.anexos == [{"nome": "nota.pdf", "tamanho": 12, "tipo": "application/pdf"}]
    assert len(mail.outbox[0].attachments) == 1


@DOMINIOS
def test_rascunho_de_anexo_e_limpo_apos_envio(ambiente_de_aliases, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from mensagens.anexos import criar_token, listar_anexos, salvar_anexo

    settings.RASCUNHOS_DIR = tmp_path
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("nota.pdf", b"x"))

    enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"), token_anexos=token)

    assert listar_anexos(token) == []


@DOMINIOS
def test_corpo_html_guardado_conforme_a_flag(ambiente_de_aliases, settings):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(para=["c@x.com"], corpo_html="<p>guarde isto</p>")

    settings.GUARDAR_CORPO_ENVIADO = True
    com_guarda = enviar_email(alias, dados)
    assert "guarde isto" in com_guarda.corpo_html

    settings.GUARDAR_CORPO_ENVIADO = False
    sem_guarda = enviar_email(alias, dados)
    assert sem_guarda.corpo_html == ""


@DOMINIOS
def test_in_reply_to_e_referencias_persistidos(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(
        para=["c@x.com"], corpo_html="oi",
        in_reply_to="<orig@x>", referencias="<a@x> <orig@x>",
    )
    registro = enviar_email(alias, dados)
    assert registro.in_reply_to == "<orig@x>"
    assert registro.referencias == "<a@x> <orig@x>"
