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
    # Depois de uma prévia, o botão Enviar e o hash que a amarra aparecem.
    assert 'name="hash_previa"' in conteudo
    assert 'value="enviar"' in conteudo


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
def test_enviar_sem_previa_nao_envia(client, logado):
    """Sem hash_previa (ou vazio), o acao=enviar não bate com hash nenhum."""
    from django.core import mail

    from mensagens.models import RegistroEnvio

    resposta = client.post(
        reverse("mensagens:inicio"),
        {"acao": "enviar", "alias": "financeiro", "para": "c@x.com", "corpo": "<p>oi</p>"},
    )
    assert resposta.status_code == 200  # cai de volta na prévia, não redireciona
    assert len(mail.outbox) == 0
    assert RegistroEnvio.objects.count() == 0


@DOMINIOS
def test_previa_depois_enviar_envia_de_verdade(client, logado):
    from django.core import mail

    from mensagens.models import RegistroEnvio

    dados = {
        "alias": "financeiro", "para": "cliente@example.com",
        "assunto": "Oi", "corpo": "<p>Olá</p>",
    }

    previa = client.post(reverse("mensagens:inicio"), {**dados, "acao": "previa"})
    hash_previa = previa.context["previa"]["hash"]

    resposta = client.post(
        reverse("mensagens:inicio"),
        {**dados, "acao": "enviar", "hash_previa": hash_previa},
    )

    assert resposta.status_code == 302
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["cliente@example.com"]

    registro = RegistroEnvio.objects.get()
    assert registro.status == RegistroEnvio.Status.ENVIADO
    assert resposta.url == reverse("mensagens:registro", args=[registro.pk])


@DOMINIOS
def test_editar_apos_previa_e_enviar_recusa_e_mostra_nova_previa(client, logado):
    """Hash desatualizado: o envio é recusado e a prévia é refeita, não perdida."""
    from django.core import mail

    dados = {"alias": "financeiro", "para": "c@x.com", "corpo": "<p>oi</p>"}
    previa = client.post(reverse("mensagens:inicio"), {**dados, "acao": "previa"})
    hash_velho = previa.context["previa"]["hash"]

    resposta = client.post(
        reverse("mensagens:inicio"),
        {
            "alias": "financeiro", "para": "c@x.com", "corpo": "<p>texto mudou</p>",
            "acao": "enviar", "hash_previa": hash_velho,
        },
    )

    assert resposta.status_code == 200  # não redireciona: não enviou
    assert len(mail.outbox) == 0
    assert resposta.context["previa"] is not None
    assert "texto mudou" in resposta.context["previa"]["html"]
    conteudo = resposta.content.decode()
    assert "mudou desde a última prévia" in conteudo


@DOMINIOS
def test_envio_bem_sucedido_redireciona_para_fora_da_url_de_envio(client, logado):
    """A proteção real contra duplicar no F5 é estrutural: depois de enviar, a
    URL na barra de endereço vira a do registro (GET), não mais a do POST de
    envio — um refresh ali reemite um GET inofensivo, não o envio de novo.
    O que resta depois disso (dois cliques quase simultâneos no botão, antes
    do redirecionamento) é coberto no navegador, desabilitando o botão no
    clique — não em código Python testável por aqui."""
    dados = {"alias": "financeiro", "para": "c@x.com", "corpo": "<p>oi</p>"}
    previa = client.post(reverse("mensagens:inicio"), {**dados, "acao": "previa"})
    hash_previa = previa.context["previa"]["hash"]

    resposta = client.post(
        reverse("mensagens:inicio"), {**dados, "acao": "enviar", "hash_previa": hash_previa}
    )

    assert resposta.status_code == 302
    assert resposta.url.startswith("/historico/")


@DOMINIOS
def test_importar_eml_preenche_a_redacao(client, logado):
    from pathlib import Path

    from django.core.files.uploadedfile import SimpleUploadedFile

    conteudo = (Path(__file__).parent / "fixtures" / "resposta_quoted_printable.eml").read_bytes()
    resposta_import = client.post(
        reverse("mensagens:importar"),
        {"arquivo": SimpleUploadedFile("resposta.eml", conteudo)},
    )
    assert resposta_import.status_code == 302
    assert resposta_import.url == reverse("mensagens:inicio")

    resposta = client.get(reverse("mensagens:inicio"))
    form = resposta.context["form"]
    assert form.initial["para"] == "atendimento@exemplo.com"
    assert form.initial["assunto"] == "Re: Dúvida sobre integração"
    assert form.initial["in_reply_to"] == "<abc123_ticket9001@exemplo.com>"
    assert "ção" in form.initial["citacao_html"]

    # Uso único: uma segunda visita não repete o preenchimento.
    resposta_de_novo = client.get(reverse("mensagens:inicio"))
    assert resposta_de_novo.context["form"].initial.get("para") is None


@DOMINIOS
def test_importar_arquivo_ilegivel_mostra_erro(client, logado):
    from django.core.files.uploadedfile import SimpleUploadedFile

    resposta = client.post(
        reverse("mensagens:importar"),
        {"arquivo": SimpleUploadedFile("lixo.txt", b"nada parecido com e-mail")},
        follow=True,
    )
    conteudo = resposta.content.decode()
    assert "reconhecer este arquivo" in conteudo


@DOMINIOS
def test_importar_message_id_manual(client, logado):
    resposta_import = client.post(
        reverse("mensagens:importar"), {"message_id_manual": "abc@exemplo.com"}
    )
    assert resposta_import.status_code == 302

    resposta = client.get(reverse("mensagens:inicio"))
    form = resposta.context["form"]
    assert form.initial["in_reply_to"] == "<abc@exemplo.com>"
    assert form.initial["referencias"] == "<abc@exemplo.com>"
    # Sem arquivo, não há destinatário/assunto/citação para inferir.
    assert "para" not in form.initial


@DOMINIOS
def test_importar_sem_arquivo_e_sem_message_id_mostra_erro(client, logado):
    resposta = client.post(reverse("mensagens:importar"), {}, follow=True)
    assert "Envie um arquivo" in resposta.content.decode()


@DOMINIOS
def test_importar_eml_grande_demais_e_recusado(client, logado, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile

    settings.EML_MAX_BYTES = 100
    resposta = client.post(
        reverse("mensagens:importar"),
        {"arquivo": SimpleUploadedFile("grande.eml", b"x" * 500)},
        follow=True,
    )
    # O corpo do multipart já passa de EML_MAX_BYTES sozinho, então quem
    # recusa primeiro é a checagem de CONTENT_LENGTH da view externa.
    assert "grande demais" in resposta.content.decode()


@DOMINIOS
def test_historico_mostra_link_responder_so_para_enviados(client, logado):
    from mensagens.models import RegistroEnvio

    RegistroEnvio.objects.create(
        alias="financeiro", remetente="x <financeiro@leonardocosta.dev>",
        para="a@x.com", assunto="Enviado", message_id="<e@x>",
        status=RegistroEnvio.Status.ENVIADO,
    )
    RegistroEnvio.objects.create(
        alias="financeiro", remetente="x <financeiro@leonardocosta.dev>",
        para="a@x.com", assunto="Falhou", message_id="<f@x>",
        status=RegistroEnvio.Status.FALHOU,
    )
    resposta = client.get(reverse("mensagens:historico"))
    conteudo = resposta.content.decode()
    # "responder" sozinho aparece 2x por link (no href "?responder=" e no
    # texto visível) — contar o parâmetro da URL é o que mede quantos links
    # existem, um por envio bem-sucedido.
    assert conteudo.count("?responder=") == 1


@DOMINIOS
def test_responder_dedup_e_cap_de_referencias(client, logado):
    """O fluxo 'responder a algo que eu enviei' usa a mesma lógica de
    dedup/teto de referencias_para_resposta, não uma concatenação ingênua."""
    from mensagens.models import RegistroEnvio

    original = RegistroEnvio.objects.create(
        alias="financeiro", remetente="x <financeiro@leonardocosta.dev>",
        para="cliente@example.com", assunto="Pedido",
        message_id="<abc@leonardocosta.dev>",
        referencias="<a@x> <abc@leonardocosta.dev>",  # já contém o próprio id
        status=RegistroEnvio.Status.ENVIADO,
    )
    resposta = client.get(reverse("mensagens:inicio"), {"responder": original.pk})
    referencias = resposta.context["form"].initial["referencias"]
    assert referencias == "<a@x> <abc@leonardocosta.dev>"  # sem duplicar


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
