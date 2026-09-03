"""Fluxo de redação: formulário, prévia e a casca de navegação."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db
DOMINIOS = override_settings(ALIAS_ALLOWED_DOMAINS=["leonardocosta.dev"])
BASE = {
    "SMTP_USER": "me@leonardocosta.dev",
    "SMTP_PASSWORD": "segredo",
    "ALIASES": "financeiro",
    "ALIAS_FINANCEIRO_ADDRESS": "financeiro@leonardocosta.dev",
    "ALIAS_FINANCEIRO_NAME": "Leonardo Costa",
}
SENHA = "uma-senha-bem-comprida-123"


@pytest.fixture
def logado(client, ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    usuario = get_user_model().objects.create_superuser(
        username="leonardo", email="me@leonardocosta.dev", password=SENHA
    )
    with override_settings(OTP_OBRIGATORIO=False):
        client.post(reverse("mensagens:entrar"), {"username": "leonardo", "password": SENHA})
    return usuario


@DOMINIOS
def test_tela_de_redacao_carrega(client, logado):
    resposta = client.get(reverse("mensagens:inicio"))
    assert resposta.status_code == 200
    assert b"trix-editor" in resposta.content


@DOMINIOS
def test_previa_mostra_html_sanitizado_no_iframe(client, logado):
    resposta = client.post(
        reverse("mensagens:inicio"),
        {
            "acao": "previa",
            "alias": "financeiro",
            "para": "cliente@example.com",
            "assunto": "Assunto de teste",
            "corpo": "<p><b>Olá</b></p><script>alert(1)</script>",
        },
    )
    assert resposta.status_code == 200
    conteudo = resposta.content.decode()
    # srcdoc é escapado pelo autoescape do Django — de propósito, é o que o
    # torna seguro sem |safe (ver CLAUDE.md). O navegador desfaz o escape ao
    # interpretar o atributo; aqui conferimos a forma escapada mesmo.
    assert "&lt;b&gt;Olá&lt;/b&gt;" in conteudo
    # O campo do editor propositalmente devolve o que foi digitado, sem
    # sanitizar (para o usuário continuar editando) — dentro de um atributo
    # escapado, então é inerte. O que precisa estar limpo é a prévia.
    assert "<script>" not in conteudo  # nunca sem escapar, em lugar nenhum
    inicio_previa = conteudo.index("previa-iframe")
    assert "alert(1)" not in conteudo[inicio_previa:]
    assert 'name="hash_previa"' not in conteudo  # Etapa 5 ainda não tem botão Enviar


@DOMINIOS
def test_previa_com_formulario_invalido_nao_quebra(client, logado):
    resposta = client.post(
        reverse("mensagens:inicio"),
        {"acao": "previa", "alias": "financeiro", "para": "", "corpo": "oi"},
    )
    assert resposta.status_code == 200
    assert b"Informe pelo menos um endere" in resposta.content


@DOMINIOS
def test_anexar_lista_e_persiste_entre_previas(client, logado, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.RASCUNHOS_DIR = tmp_path
    dados_base = {
        "acao": "previa", "alias": "financeiro",
        "para": "c@x.com", "corpo": "<p>oi</p>",
    }

    primeira = client.post(
        reverse("mensagens:inicio"),
        {**dados_base, "novo_anexo": SimpleUploadedFile("nota.pdf", b"conteudo")},
    )
    assert primeira.status_code == 200
    token = primeira.context["form"]["rascunho"].value()
    assert token
    assert [a.nome for a in primeira.context["anexos"]] == ["nota.pdf"]

    # O token volta no campo oculto — a segunda prévia, sem novo arquivo,
    # continua mostrando o anexo já salvo.
    segunda = client.post(reverse("mensagens:inicio"), {**dados_base, "rascunho": token})
    assert [a.nome for a in segunda.context["anexos"]] == ["nota.pdf"]


@DOMINIOS
def test_remover_anexo_mantem_os_demais(client, logado, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from mensagens.anexos import criar_token, salvar_anexo

    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    um = salvar_anexo(token, SimpleUploadedFile("um.pdf", b"1"))
    salvar_anexo(token, SimpleUploadedFile("dois.pdf", b"2"))

    resposta = client.post(
        reverse("mensagens:inicio"),
        {
            "alias": "financeiro", "para": "c@x.com", "corpo": "<p>oi</p>",
            "rascunho": token, "remover_anexo": um.id,
        },
    )
    assert resposta.status_code == 200
    assert [a.nome for a in resposta.context["anexos"]] == ["dois.pdf"]


@DOMINIOS
def test_anexo_com_extensao_bloqueada_mostra_erro(client, logado, tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.RASCUNHOS_DIR = tmp_path
    settings.ANEXOS_EXTENSOES_BLOQUEADAS = ["exe"]

    resposta = client.post(
        reverse("mensagens:inicio"),
        {
            "acao": "previa", "alias": "financeiro", "para": "c@x.com", "corpo": "<p>oi</p>",
            "novo_anexo": SimpleUploadedFile("virus.exe", b"MZ"),
        },
    )
    assert resposta.status_code == 200
    assert b"n\xc3\xa3o permitido" in resposta.content
    assert resposta.context["previa"] is None


@DOMINIOS
def test_responder_pre_preenche_destinatario_original(client, logado):
    from mensagens.models import RegistroEnvio

    original = RegistroEnvio.objects.create(
        alias="financeiro",
        remetente="Leonardo Costa <financeiro@leonardocosta.dev>",
        para="cliente@example.com",
        assunto="Pedido",
        message_id="<abc@leonardocosta.dev>",
        status=RegistroEnvio.Status.ENVIADO,
    )
    resposta = client.get(reverse("mensagens:inicio"), {"responder": original.pk})
    assert resposta.status_code == 200
    form = resposta.context["form"]
    assert form.initial["para"] == "cliente@example.com"
    assert form.initial["assunto"] == "Re: Pedido"
    assert form.initial["in_reply_to"] == "<abc@leonardocosta.dev>"
