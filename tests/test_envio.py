"""enviar_email(): grava o RegistroEnvio antes de mandar, nunca levanta."""

import pytest
from django.core import mail

from mensagens.envio import enviar_email
from mensagens.models import RegistroEnvio
from mensagens.montagem import DadosRedacao

pytestmark = pytest.mark.django_db


def test_envio_bem_sucedido(alias_de_teste, settings):
    settings.MESSAGE_ID_DOMAIN = "leonardocosta.dev"
    alias = alias_de_teste
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


def test_message_id_termina_no_dominio_do_alias(alias_de_teste, settings):
    settings.MESSAGE_ID_DOMAIN = ""  # vazio → cai no domínio do próprio alias
    alias = alias_de_teste
    registro = enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"))
    assert registro.message_id.endswith("@leonardocosta.dev>")


def test_grava_enviando_antes_de_mandar(alias_de_teste, monkeypatch):
    """O status ENVIANDO existe para o histórico contar a verdade mesmo se o
    processo morrer no meio da chamada de rede — não dá pra observar isso
    depois do fato num teste síncrono, mas dá pra confirmar que o registro é
    criado ANTES do envio, interceptando o ponto de envio."""
    alias = alias_de_teste

    capturado = {}
    original_send = mail.EmailMultiAlternatives.send

    def _interceptar(self, *args, **kwargs):
        capturado["status_durante_envio"] = RegistroEnvio.objects.get().status
        return original_send(self, *args, **kwargs)

    monkeypatch.setattr(mail.EmailMultiAlternatives, "send", _interceptar)

    enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"))

    assert capturado["status_durante_envio"] == RegistroEnvio.Status.ENVIANDO


def test_falha_de_smtp_grava_status_falhou_e_nao_levanta(alias_de_teste, monkeypatch):
    from smtplib import SMTPAuthenticationError

    alias = alias_de_teste

    def _quebrar(self, *args, **kwargs):
        raise SMTPAuthenticationError(535, b"credenciais invalidas")

    monkeypatch.setattr(mail.EmailMultiAlternatives, "send", _quebrar)

    registro = enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"))

    assert registro.status == RegistroEnvio.Status.FALHOU
    assert "credenciais invalidas" in registro.erro
    assert len(mail.outbox) == 0


def test_anexos_persistidos_no_registro(alias_de_teste, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from mensagens.anexos import criar_token, salvar_anexo

    settings.RASCUNHOS_DIR = tmp_path
    alias = alias_de_teste
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("nota.pdf", b"conteudo-pdf"))

    registro = enviar_email(
        alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"), token_anexos=token
    )

    assert registro.anexos == [{"nome": "nota.pdf", "tamanho": 12, "tipo": "application/pdf"}]
    assert len(mail.outbox[0].attachments) == 1


def test_rascunho_de_anexo_e_limpo_apos_envio(alias_de_teste, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from mensagens.anexos import criar_token, listar_anexos, salvar_anexo

    settings.RASCUNHOS_DIR = tmp_path
    alias = alias_de_teste
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("nota.pdf", b"x"))

    enviar_email(alias, DadosRedacao(para=["c@x.com"], corpo_html="oi"), token_anexos=token)

    assert listar_anexos(token) == []


def test_corpo_html_guardado_conforme_a_flag(alias_de_teste, settings):
    alias = alias_de_teste
    dados = DadosRedacao(para=["c@x.com"], corpo_html="<p>guarde isto</p>")

    settings.GUARDAR_CORPO_ENVIADO = True
    com_guarda = enviar_email(alias, dados)
    assert "guarde isto" in com_guarda.corpo_html

    settings.GUARDAR_CORPO_ENVIADO = False
    sem_guarda = enviar_email(alias, dados)
    assert sem_guarda.corpo_html == ""


def test_in_reply_to_e_referencias_persistidos(alias_de_teste):
    alias = alias_de_teste
    dados = DadosRedacao(
        para=["c@x.com"], corpo_html="oi",
        in_reply_to="<orig@x>", referencias="<a@x> <orig@x>",
    )
    registro = enviar_email(alias, dados)
    assert registro.in_reply_to == "<orig@x>"
    assert registro.referencias == "<a@x> <orig@x>"
