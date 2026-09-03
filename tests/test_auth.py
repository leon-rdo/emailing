"""Autenticação: tudo fechado por padrão, TOTP e lockout."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

pytestmark = pytest.mark.django_db

SENHA = "uma-senha-bem-comprida-123"


@pytest.fixture
def usuario():
    return get_user_model().objects.create_superuser(
        username="leonardo", email="me@leonardocosta.dev", password=SENHA
    )


def test_raiz_exige_login(client):
    resposta = client.get("/")
    assert resposta.status_code == 302
    assert resposta.headers["Location"].startswith("/entrar/")


def test_admin_exige_login(client):
    assert client.get("/admin/").status_code == 302


def test_pagina_de_login_e_publica(client):
    assert client.get("/entrar/").status_code == 200


@override_settings(OTP_OBRIGATORIO=False)
def test_login_sem_otp_em_desenvolvimento(client, usuario):
    resposta = client.post(
        "/entrar/", {"username": "leonardo", "password": SENHA}, follow=True
    )
    assert resposta.status_code == 200
    assert resposta.wsgi_request.user.is_authenticated


@override_settings(OTP_OBRIGATORIO=True)
def test_senha_certa_sem_dispositivo_nao_entra(client, usuario):
    """Sessão autenticada mas não verificada é encerrada pelo middleware."""
    client.post("/entrar/", {"username": "leonardo", "password": SENHA})
    resposta = client.get("/")
    assert resposta.status_code == 302
    assert resposta.headers["Location"].startswith("/entrar/")


@override_settings(OTP_OBRIGATORIO=True)
def test_com_dispositivo_o_token_e_obrigatorio(client, usuario):
    TOTPDevice.objects.create(user=usuario, name="teste", confirmed=True)
    resposta = client.post("/entrar/", {"username": "leonardo", "password": SENHA})
    # Fica na página de login: o formulário recusa sem o código.
    assert resposta.status_code == 200
    assert not resposta.wsgi_request.user.is_authenticated


@override_settings(OTP_OBRIGATORIO=True)
def test_token_correto_entra_com_dispositivo_unico(client, usuario):
    """Com um dispositivo só, não é preciso escolhê-lo no formulário."""
    dispositivo = TOTPDevice.objects.create(user=usuario, name="teste", confirmed=True)
    resposta = client.post(
        "/entrar/",
        {"username": "leonardo", "password": SENHA, "otp_token": _token(dispositivo)},
        follow=True,
    )
    assert resposta.wsgi_request.user.is_authenticated
    assert resposta.wsgi_request.user.is_verified()


@override_settings(OTP_OBRIGATORIO=True)
def test_com_dois_dispositivos_a_escolha_volta_a_ser_obrigatoria(client, usuario):
    primeiro = TOTPDevice.objects.create(user=usuario, name="celular", confirmed=True)
    TOTPDevice.objects.create(user=usuario, name="reserva", confirmed=True)

    recusado = client.post(
        "/entrar/",
        {"username": "leonardo", "password": SENHA, "otp_token": _token(primeiro)},
    )
    assert not recusado.wsgi_request.user.is_authenticated

    aceito = client.post(
        "/entrar/",
        {
            "username": "leonardo",
            "password": SENHA,
            "otp_device": primeiro.persistent_id,
            "otp_token": _token(primeiro),
        },
        follow=True,
    )
    assert aceito.wsgi_request.user.is_verified()


@override_settings(OTP_OBRIGATORIO=True)
def test_token_errado_nao_entra(client, usuario):
    TOTPDevice.objects.create(user=usuario, name="teste", confirmed=True)
    resposta = client.post(
        "/entrar/", {"username": "leonardo", "password": SENHA, "otp_token": "000000"}
    )
    assert resposta.status_code == 200
    assert not resposta.wsgi_request.user.is_authenticated


@override_settings(AXES_FAILURE_LIMIT=3, OTP_OBRIGATORIO=False)
def test_lockout_depois_do_limite(client, usuario):
    for _ in range(3):
        client.post("/entrar/", {"username": "leonardo", "password": "errada"})
    # A senha certa não vale mais: o axes corta antes do backend.
    resposta = client.post("/entrar/", {"username": "leonardo", "password": SENHA})
    assert resposta.status_code in (403, 429)
    assert not resposta.wsgi_request.user.is_authenticated


def test_cabecalhos_de_seguranca(client):
    resposta = client.get("/entrar/")
    assert resposta.headers["X-Robots-Tag"] == "noindex, nofollow"
    csp = resposta.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    assert "gravatar.com" in csp  # img-src precisa liberar a foto da assinatura


def test_url_de_login_bate_com_o_settings():
    assert reverse("mensagens:entrar") == "/entrar/"


def _token(dispositivo: TOTPDevice) -> str:
    from django_otp.oath import TOTP

    totp = TOTP(dispositivo.bin_key, dispositivo.step, dispositivo.t0, dispositivo.digits)
    return f"{totp.token():0{dispositivo.digits}d}"
