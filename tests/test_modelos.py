"""RegistroEnvio: modelo, admin somente leitura, telas de histórico."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import override_settings
from django.urls import reverse

from mensagens.models import RegistroEnvio

pytestmark = pytest.mark.django_db
SENHA = "uma-senha-bem-comprida-123"


def _registro(**extra):
    dados = {
        "alias": "financeiro",
        "remetente": "Ana Souza <financeiro@empresa.example>",
        "para": "cliente@example.com",
        "assunto": "Assunto de teste",
        "message_id": "<abc123@empresa.example>",
        "status": RegistroEnvio.Status.ENVIADO,
    }
    dados.update(extra)
    return RegistroEnvio.objects.create(**dados)


@pytest.fixture
def logado(client):
    """`client.login()` não passa `request` ao backend, e o axes exige um.

    Autenticar pela própria view de login (como um navegador faria) evita o
    problema e ainda exercita o caminho real.
    """
    usuario = get_user_model().objects.create_superuser(
        username="operador", email="me@empresa.example", password=SENHA
    )
    with override_settings(OTP_OBRIGATORIO=False):
        client.post(reverse("mensagens:entrar"), {"username": "operador", "password": SENHA})
    return usuario


def test_message_id_e_unico():
    _registro(message_id="<repetido@empresa.example>")
    with pytest.raises(IntegrityError):
        _registro(message_id="<repetido@empresa.example>")


def test_ordenacao_padrao_do_mais_novo():
    primeiro = _registro(message_id="<1@x>")
    segundo = _registro(message_id="<2@x>")
    assert list(RegistroEnvio.objects.all()) == [segundo, primeiro]


def test_selo_css():
    assert _registro(message_id="<a@x>", status=RegistroEnvio.Status.ENVIADO).selo_css == "enviado"
    assert _registro(message_id="<b@x>", status=RegistroEnvio.Status.FALHOU).selo_css == "falhou"
    assert (
        _registro(message_id="<c@x>", status=RegistroEnvio.Status.ENVIANDO).selo_css == "enviando"
    )


def test_historico_lista_do_mais_novo(client, logado):
    _registro(message_id="<1@x>", assunto="Primeiro")
    _registro(message_id="<2@x>", assunto="Segundo")
    resposta = client.get(reverse("mensagens:historico"))
    assert resposta.status_code == 200
    conteudo = resposta.content.decode()
    assert conteudo.index("Segundo") < conteudo.index("Primeiro")


def test_historico_pagina(client, logado):
    for i in range(30):
        _registro(message_id=f"<{i}@x>")
    resposta = client.get(reverse("mensagens:historico"))
    assert len(resposta.context["pagina"].object_list) == 25
    assert resposta.context["pagina"].paginator.num_pages == 2


def test_detalhe_do_registro(client, logado):
    item = _registro(message_id="<abc@x>", corpo_html="<p>oi</p>")
    resposta = client.get(reverse("mensagens:registro", args=[item.pk]))
    assert resposta.status_code == 200
    assert "abc@x" in resposta.content.decode()


def test_detalhe_inexistente_da_404(client, logado):
    resposta = client.get(reverse("mensagens:registro", args=[9999]))
    assert resposta.status_code == 404


def test_historico_exige_login(client):
    assert client.get(reverse("mensagens:historico")).status_code == 302


def test_admin_nao_vaza_a_chave_totp(client, logado):
    """OTP_ADMIN_HIDE_SENSITIVE_DATA: o padrão do django-otp é False, o que
    mostraria a chave secreta do TOTP em texto puro no admin."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    dispositivo = TOTPDevice.objects.create(user=logado, name="teste", confirmed=True)
    url = reverse("admin:otp_totp_totpdevice_change", args=[dispositivo.pk])
    resposta = client.get(url)
    assert resposta.status_code == 200
    conteudo = resposta.content.decode()
    assert dispositivo.key not in conteudo
    assert "qrcode" not in conteudo.lower()


def test_admin_e_somente_leitura(client, logado):
    item = _registro(message_id="<ro@x>")
    url = reverse("admin:mensagens_registroenvio_change", args=[item.pk])
    resposta = client.get(url)
    assert resposta.status_code == 200
    assert b'name="_save"' not in resposta.content

    resposta_add = client.get(reverse("admin:mensagens_registroenvio_add"))
    assert resposta_add.status_code == 403

    resposta_delete = client.get(reverse("admin:mensagens_registroenvio_delete", args=[item.pk]))
    assert resposta_delete.status_code == 403
