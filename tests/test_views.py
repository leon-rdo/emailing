"""Fluxo de redação: formulário, prévia e a casca de navegação."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

_TAG_BOTAO_ENVIAR = re.compile(r'<button[^>]*name="acao" value="enviar"[^>]*>')
_TAG_PAINEL_PREVIA = re.compile(r'<div class="via painel-previa"[^>]*>')


def _tag_botao_enviar(html: str) -> str:
    return _TAG_BOTAO_ENVIAR.search(html).group(0)


def _tag_painel_previa(html: str) -> str:
    return _TAG_PAINEL_PREVIA.search(html).group(0)

pytestmark = pytest.mark.django_db
SENHA = "uma-senha-bem-comprida-123"


@pytest.fixture
def logado(client, alias_de_teste):
    usuario = get_user_model().objects.create_superuser(
        username="leonardo", email="me@leonardocosta.dev", password=SENHA
    )
    with override_settings(OTP_OBRIGATORIO=False):
        client.post(reverse("mensagens:entrar"), {"username": "leonardo", "password": SENHA})
    return usuario


def test_tela_de_redacao_carrega(client, logado):
    resposta = client.get(reverse("mensagens:inicio"))
    assert resposta.status_code == 200
    assert b"trix-editor" in resposta.content


def test_sem_previa_botao_enviar_nasce_desabilitado(client, logado):
    """O painel de prévia está sempre à vista (a prévia ao vivo o preenche logo
    ao abrir), mas o botão Enviar nasce `disabled` até haver uma prévia em dia
    — sem JS, a trava de `hash_previa` do servidor continua valendo igual."""
    resposta = client.get(reverse("mensagens:inicio"))
    conteudo = resposta.content.decode()
    assert 'name="hash_previa"' in conteudo  # sempre presente, começa vazio
    assert 'value=""' in conteudo
    assert "disabled" in _tag_botao_enviar(conteudo)
    assert "hidden" not in _tag_painel_previa(conteudo)


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
    # Depois de uma prévia, o hash não fica vazio e o botão Enviar não tem
    # mais o atributo disabled que carregava na carga inicial.
    assert 'name="hash_previa" value=""' not in conteudo
    assert "disabled" not in _tag_botao_enviar(conteudo)


def test_previa_com_formulario_invalido_nao_quebra(client, logado):
    resposta = client.post(
        reverse("mensagens:inicio"),
        {"acao": "previa", "alias": "financeiro", "para": "", "corpo": "oi"},
    )
    assert resposta.status_code == 200
    assert b"Informe pelo menos um endere" in resposta.content


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


def test_previa_ajax_devolve_json_com_html_sanitizado(client, logado):
    resposta = client.post(
        reverse("mensagens:previa_ajax"),
        {
            "alias": "financeiro", "para": "c@x.com", "assunto": "Oi",
            "corpo": "<p><b>Olá</b></p><script>alert(1)</script>",
        },
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["ok"] is True
    assert "<b>Olá</b>" in corpo["html"]
    assert "<script>" not in corpo["html"]
    assert "hash" in corpo and corpo["hash"]


def test_previa_ajax_funciona_antes_de_ter_destinatario(client, logado):
    """Escrever o corpo antes do "Para" é a ordem natural — a prévia ao vivo
    tem que responder já aí, senão fica morta justamente no começo."""
    resposta = client.post(
        reverse("mensagens:previa_ajax"),
        {"alias": "financeiro", "para": "", "corpo": "<p>escrevendo primeiro</p>"},
    )
    corpo = resposta.json()
    assert corpo["ok"] is True
    assert "escrevendo primeiro" in corpo["html"]


@pytest.mark.parametrize(
    "parcial",
    ["", "c", "cliente@", "cliente@exe", "cliente@exemplo.com", "a@x.com, parcial@"],
)
def test_previa_ajax_sobrevive_a_endereco_sendo_digitado(client, logado, parcial):
    """Todo e-mail passa por estados inválidos enquanto é digitado
    ("cliente@exe"). Se isso invalidar a prévia, ela congela no meio de cada
    digitação e parece que só o botão funciona — foi o defeito relatado."""
    resposta = client.post(
        reverse("mensagens:previa_ajax"),
        {"alias": "financeiro", "para": parcial, "corpo": "<p>corpo estável</p>"},
    )
    corpo = resposta.json()
    assert corpo["ok"] is True, f"prévia quebrou com para={parcial!r}"
    assert "corpo estável" in corpo["html"]


def test_previa_traz_moldura_com_fonte_sem_serifa(client, logado):
    """O iframe não herda estilo: sem moldura, HTML sem font-family cairia na
    fonte serifada do navegador, que nenhum cliente de e-mail usa."""
    resposta = client.post(
        reverse("mensagens:previa_ajax"),
        {"alias": "financeiro", "para": "c@x.com", "corpo": "<p>oi</p>"},
    )
    html = resposta.json()["html"]
    assert "sans-serif" in html
    assert "<p>oi</p>" in html


def test_moldura_nao_entra_no_que_e_enviado(client, logado):
    """A moldura é só da tela — o que sai no e-mail não pode levá-la junto."""
    from django.core import mail

    dados = {"alias": "financeiro", "para": "c@x.com", "corpo": "<p>oi</p>"}
    previa = client.post(reverse("mensagens:inicio"), {**dados, "acao": "previa"})
    client.post(
        reverse("mensagens:inicio"),
        {**dados, "acao": "enviar", "hash_previa": previa.context["previa"]["hash"]},
    )

    enviado = mail.outbox[0].alternatives[0][0]
    assert "<p>oi</p>" in enviado
    assert "<!DOCTYPE html>" not in enviado
    assert "Arial,Helvetica" not in enviado


def test_previa_ajax_com_dados_invalidos_devolve_erro_sem_quebrar(client, logado):
    resposta = client.post(
        reverse("mensagens:previa_ajax"),
        {"alias": "alias-que-nao-existe", "para": "c@x.com", "corpo": "oi"},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["ok"] is False
    assert corpo["erros"]


def test_previa_ajax_bate_com_a_previa_do_post_completo(client, logado):
    """As duas rotas usam a mesma função — o hash de uma serve na outra."""
    dados = {"alias": "financeiro", "para": "c@x.com", "assunto": "Oi", "corpo": "<p>oi</p>"}

    via_ajax = client.post(reverse("mensagens:previa_ajax"), dados).json()
    via_post = client.post(reverse("mensagens:inicio"), {**dados, "acao": "previa"})

    assert via_ajax["hash"] == via_post.context["previa"]["hash"]
    # As duas rotas mandam para o iframe a versão emoldurada, idêntica.
    assert via_ajax["html"] == via_post.context["previa"]["html_previa"]


def test_previa_ajax_get_nao_permitido(client, logado):
    resposta = client.get(reverse("mensagens:previa_ajax"))
    assert resposta.status_code == 405


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


def test_importar_arquivo_ilegivel_mostra_erro(client, logado):
    from django.core.files.uploadedfile import SimpleUploadedFile

    resposta = client.post(
        reverse("mensagens:importar"),
        {"arquivo": SimpleUploadedFile("lixo.txt", b"nada parecido com e-mail")},
        follow=True,
    )
    conteudo = resposta.content.decode()
    assert "reconhecer este arquivo" in conteudo


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


def test_importar_sem_arquivo_e_sem_message_id_mostra_erro(client, logado):
    resposta = client.post(reverse("mensagens:importar"), {}, follow=True)
    assert "Envie um arquivo" in resposta.content.decode()


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


# ---------------------------------------------------------------------------
# Agendar pela tela
# ---------------------------------------------------------------------------


def _dados_de_redacao(**extra):
    base = {
        "alias": "financeiro",
        "para": "cliente@example.com",
        "assunto": "Depois",
        "corpo": "<p>Olá</p>",
    }
    return {**base, **extra}


def _com_previa(client, dados):
    """Faz a prévia e devolve os dados prontos para o POST seguinte, com o hash
    que a prévia calculou — é o que a trava do envio compara."""
    previa = client.post(reverse("mensagens:inicio"), {**dados, "acao": "previa"})
    return {**dados, "hash_previa": previa.context["previa"]["hash"]}


def test_agendar_apos_previa_poe_na_fila(client, logado):
    from datetime import timedelta

    from django.core import mail
    from django.utils import timezone

    from mensagens.models import EnvioAgendado

    quando = timezone.localtime() + timedelta(days=1)
    dados = _com_previa(client, _dados_de_redacao())

    resposta = client.post(
        reverse("mensagens:inicio"),
        {**dados, "acao": "agendar", "enviar_em": quando.strftime("%Y-%m-%dT%H:%M")},
    )

    assert resposta.status_code == 302
    assert resposta["Location"] == reverse("mensagens:agendados")
    assert mail.outbox == []
    agendado = EnvioAgendado.objects.get()
    assert agendado.status == EnvioAgendado.Status.AGENDADO
    assert timezone.localtime(agendado.enviar_em).strftime("%Y-%m-%dT%H:%M") == (
        quando.strftime("%Y-%m-%dT%H:%M")
    )


def test_agendar_sem_previa_nao_agenda(client, logado):
    """A mesma trava do envio: o que vai para a fila é o que foi conferido — e
    aqui ela importa mais, porque ninguém relê a mensagem quando ela sai."""
    from datetime import timedelta

    from django.utils import timezone

    from mensagens.models import EnvioAgendado

    quando = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    resposta = client.post(
        reverse("mensagens:inicio"),
        {**_dados_de_redacao(), "acao": "agendar", "enviar_em": quando, "hash_previa": ""},
    )

    assert resposta.status_code == 200
    assert EnvioAgendado.objects.count() == 0
    assert "O conteúdo mudou" in resposta.content.decode()


def test_agendar_sem_data_avisa_e_mantem_a_previa(client, logado):
    from mensagens.models import EnvioAgendado

    dados = _com_previa(client, _dados_de_redacao())
    resposta = client.post(reverse("mensagens:inicio"), {**dados, "acao": "agendar"})

    assert resposta.status_code == 200
    assert EnvioAgendado.objects.count() == 0
    assert "informe a data" in resposta.content.decode().lower()
    assert resposta.context["previa"] is not None


def test_agendar_no_passado_avisa(client, logado):
    from datetime import timedelta

    from django.utils import timezone

    from mensagens.models import EnvioAgendado

    passado = (timezone.localtime() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    dados = _com_previa(client, _dados_de_redacao())

    resposta = client.post(
        reverse("mensagens:inicio"), {**dados, "acao": "agendar", "enviar_em": passado}
    )

    assert EnvioAgendado.objects.count() == 0
    assert "já passou" in resposta.content.decode()


def test_data_meio_digitada_nao_derruba_a_previa(client, logado):
    """A lição do `pressSequentially`, aplicada à data: "2026-09-1" é um estado
    pelo qual toda digitação passa, e a prévia não pode morrer nele."""
    resposta = client.post(
        reverse("mensagens:previa_ajax"),
        {**_dados_de_redacao(), "enviar_em": "2026-09-1"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["ok"] is True


def test_data_nao_entra_no_hash_da_previa(client, logado):
    """A data não é conteúdo: mudar a hora do agendamento não pode invalidar uma
    prévia já conferida."""
    sem = client.post(reverse("mensagens:previa_ajax"), _dados_de_redacao())
    com = client.post(
        reverse("mensagens:previa_ajax"),
        {**_dados_de_redacao(), "enviar_em": "2026-12-25T09:00"},
    )
    assert sem.json()["hash"] == com.json()["hash"]


def test_fila_lista_e_cancela(client, logado, alias_de_teste):
    from datetime import timedelta

    from django.utils import timezone

    from mensagens.agendamento import agendar
    from mensagens.models import EnvioAgendado
    from mensagens.montagem import DadosRedacao

    agendado = agendar(
        alias_de_teste,
        DadosRedacao(para=["cliente@example.com"], assunto="Na fila"),
        timezone.now() + timedelta(days=1),
    )

    lista = client.get(reverse("mensagens:agendados"))
    assert lista.status_code == 200
    assert b"Na fila" in lista.content

    resposta = client.post(reverse("mensagens:cancelar_agendado", args=[agendado.pk]))
    assert resposta.status_code == 302
    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.CANCELADO


def test_cancelar_exige_post(client, logado, alias_de_teste):
    from datetime import timedelta

    from django.utils import timezone

    from mensagens.agendamento import agendar
    from mensagens.models import EnvioAgendado
    from mensagens.montagem import DadosRedacao

    agendado = agendar(
        alias_de_teste, DadosRedacao(para=["c@x.com"]), timezone.now() + timedelta(days=1)
    )
    resposta = client.get(reverse("mensagens:cancelar_agendado", args=[agendado.pk]))

    assert resposta.status_code == 405
    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.AGENDADO


# ---------------------------------------------------------------------------
# Rascunhos, edição de agendados e detalhe
# ---------------------------------------------------------------------------


def _amanha_texto():
    from datetime import timedelta

    from django.utils import timezone

    return (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")


def _guardar_agendado(alias, **extra):
    from datetime import timedelta

    from django.utils import timezone

    from mensagens.agendamento import agendar
    from mensagens.montagem import DadosRedacao

    base = {"para": ["cliente@example.com"], "assunto": "Na fila", "corpo_html": "<p>Oi</p>"}
    dados = DadosRedacao(**{**base, **extra})
    return agendar(alias, dados, timezone.now() + timedelta(days=1))


def test_salvar_rascunho_nao_exige_previa_nem_destinatario(client, logado):
    from mensagens.models import EnvioAgendado

    resposta = client.post(
        reverse("mensagens:inicio"),
        {"acao": "salvar_rascunho", "alias": "financeiro", "assunto": "Só uma ideia",
         "corpo": "<p>depois eu termino</p>", "hash_previa": ""},
    )

    rascunho = EnvioAgendado.objects.get()
    assert rascunho.status == EnvioAgendado.Status.RASCUNHO
    assert rascunho.para == []
    assert rascunho.enviar_em is None
    assert resposta.status_code == 302
    assert resposta["Location"] == reverse("mensagens:editar", args=[rascunho.pk])


@pytest.mark.parametrize("digitado", ["joao", "cliente@exemplo"])
def test_rascunho_com_endereco_invalido_nao_descarta_em_silencio(client, logado, digitado):
    """"joao" nem chega ao validador (o `getaddresses` o descarta antes); "cliente@exemplo"
    chega e é recusado. Nos dois casos o rascunho não pode voltar com o campo vazio."""
    from mensagens.models import EnvioAgendado

    resposta = client.post(
        reverse("mensagens:inicio"),
        {"acao": "salvar_rascunho", "alias": "financeiro", "para": digitado,
         "corpo": "<p>x</p>"},
    )

    assert resposta.status_code == 200
    assert EnvioAgendado.objects.count() == 0
    assert "Endereço inválido" in resposta.content.decode()


def test_rascunho_aparece_na_lista_e_nao_na_fila(client, logado, alias_de_teste):
    from mensagens.agendamento import guardar_rascunho
    from mensagens.montagem import DadosRedacao

    guardar_rascunho(alias_de_teste, DadosRedacao(para=[], assunto="Meu rascunho"))

    assert b"Meu rascunho" in client.get(reverse("mensagens:rascunhos")).content
    fila = client.get(reverse("mensagens:agendados"))
    # nem em "Esperando" nem em "Encerrados": só o aviso de que existe
    assert b"Meu rascunho" not in fila.content
    assert "1 rascunho" in fila.content.decode()


def test_abrir_rascunho_traz_os_campos_de_volta(client, logado, alias_de_teste):
    from mensagens.agendamento import guardar_rascunho
    from mensagens.montagem import DadosRedacao

    rascunho = guardar_rascunho(
        alias_de_teste,
        DadosRedacao(para=["a@example.com"], cc=["b@example.com"], assunto="Retomar",
                     corpo_html="<p>texto</p>"),
    )
    resposta = client.get(reverse("mensagens:editar", args=[rascunho.pk]))

    assert resposta.status_code == 200
    inicial = resposta.context["form"].initial
    assert inicial["para"] == "a@example.com"
    assert inicial["cc"] == "b@example.com"
    assert inicial["corpo"] == "<p>texto</p>"
    # incompleto/válido ou não, a tela abre; aqui é válido, então já há prévia
    assert resposta.context["previa"] is not None


def test_abrir_rascunho_incompleto_abre_sem_previa_nem_erro(client, logado, alias_de_teste):
    from mensagens.agendamento import guardar_rascunho
    from mensagens.montagem import DadosRedacao

    rascunho = guardar_rascunho(alias_de_teste, DadosRedacao(para=[], assunto="Sem destino"))
    resposta = client.get(reverse("mensagens:editar", args=[rascunho.pk]))

    assert resposta.status_code == 200
    assert resposta.context["previa"] is None
    assert "errorlist" not in resposta.content.decode()


def test_salvar_rascunho_existente_atualiza_a_mesma_linha(client, logado, alias_de_teste):
    from mensagens.agendamento import guardar_rascunho
    from mensagens.models import EnvioAgendado
    from mensagens.montagem import DadosRedacao

    rascunho = guardar_rascunho(alias_de_teste, DadosRedacao(para=[], assunto="v1"))
    client.post(
        reverse("mensagens:editar", args=[rascunho.pk]),
        {"acao": "salvar_rascunho", "alias": "financeiro", "assunto": "v2", "corpo": "<p>x</p>"},
    )

    assert EnvioAgendado.objects.count() == 1
    rascunho.refresh_from_db()
    assert rascunho.assunto == "v2"


def test_agendar_a_partir_do_rascunho_vira_agendado_na_mesma_linha(client, logado, alias_de_teste):
    from mensagens.agendamento import guardar_rascunho
    from mensagens.models import EnvioAgendado
    from mensagens.montagem import DadosRedacao

    rascunho = guardar_rascunho(
        alias_de_teste, DadosRedacao(para=["c@example.com"], assunto="Vai", corpo_html="<p>x</p>")
    )
    url = reverse("mensagens:editar", args=[rascunho.pk])
    dados = _com_previa_em(
        client, url,
        {"alias": "financeiro", "para": "c@example.com", "assunto": "Vai", "corpo": "<p>x</p>"},
    )
    resposta = client.post(url, {**dados, "acao": "agendar", "enviar_em": _amanha_texto()})

    assert resposta["Location"] == reverse("mensagens:agendados")
    assert EnvioAgendado.objects.count() == 1
    rascunho.refresh_from_db()
    assert rascunho.status == EnvioAgendado.Status.AGENDADO


def _com_previa_em(client, url, dados):
    previa = client.post(url, {**dados, "acao": "previa"})
    return {**dados, "hash_previa": previa.context["previa"]["hash"]}


def test_enviar_a_partir_do_rascunho_manda_e_apaga_o_rascunho(client, logado, alias_de_teste):
    from django.core import mail

    from mensagens.agendamento import guardar_rascunho
    from mensagens.models import EnvioAgendado, RegistroEnvio
    from mensagens.montagem import DadosRedacao

    rascunho = guardar_rascunho(
        alias_de_teste, DadosRedacao(para=["c@example.com"], assunto="Sai", corpo_html="<p>x</p>")
    )
    url = reverse("mensagens:editar", args=[rascunho.pk])
    dados = _com_previa_em(
        client, url,
        {"alias": "financeiro", "para": "c@example.com", "assunto": "Sai", "corpo": "<p>x</p>"},
    )
    client.post(url, {**dados, "acao": "enviar"})

    assert len(mail.outbox) == 1
    assert RegistroEnvio.objects.get().status == RegistroEnvio.Status.ENVIADO
    assert EnvioAgendado.objects.count() == 0


def test_enviar_com_falha_preserva_o_rascunho(client, logado, alias_de_teste, monkeypatch):
    from smtplib import SMTPException

    from django.core import mail

    from mensagens.agendamento import guardar_rascunho
    from mensagens.models import EnvioAgendado
    from mensagens.montagem import DadosRedacao

    def falha(self, *args, **kwargs):
        raise SMTPException("fora do ar")

    monkeypatch.setattr(mail.EmailMultiAlternatives, "send", falha)
    rascunho = guardar_rascunho(
        alias_de_teste, DadosRedacao(para=["c@example.com"], assunto="Tenta", corpo_html="<p>x</p>")
    )
    url = reverse("mensagens:editar", args=[rascunho.pk])
    dados = _com_previa_em(
        client, url,
        {"alias": "financeiro", "para": "c@example.com", "assunto": "Tenta", "corpo": "<p>x</p>"},
    )
    client.post(url, {**dados, "acao": "enviar"})

    assert EnvioAgendado.objects.filter(pk=rascunho.pk).exists()


def test_editar_agendado_salva_alteracoes_apos_previa(client, logado, alias_de_teste):
    agendado = _guardar_agendado(alias_de_teste)
    url = reverse("mensagens:editar", args=[agendado.pk])
    dados = _com_previa_em(
        client, url,
        {"alias": "financeiro", "para": "novo@example.com", "assunto": "Corrigido",
         "corpo": "<p>novo</p>"},
    )
    resposta = client.post(url, {**dados, "acao": "salvar", "enviar_em": _amanha_texto()})

    assert resposta["Location"] == reverse("mensagens:agendados")
    agendado.refresh_from_db()
    assert (agendado.assunto, agendado.para) == ("Corrigido", ["novo@example.com"])
    assert agendado.status == "agendado"


def test_editar_agendado_sem_previa_nao_salva(client, logado, alias_de_teste):
    """A mesma trava de agendar: ninguém relê a mensagem quando ela sai."""
    agendado = _guardar_agendado(alias_de_teste, assunto="Original")
    resposta = client.post(
        reverse("mensagens:editar", args=[agendado.pk]),
        {"acao": "salvar", "alias": "financeiro", "para": "x@example.com",
         "assunto": "Trocado", "corpo": "<p>x</p>", "enviar_em": _amanha_texto(),
         "hash_previa": ""},
    )

    assert resposta.status_code == 200
    assert "O conteúdo mudou" in resposta.content.decode()
    agendado.refresh_from_db()
    assert agendado.assunto == "Original"


def test_abrir_agendado_para_editar_ja_traz_a_previa_e_o_botao_salvar(
    client, logado, alias_de_teste
):
    agendado = _guardar_agendado(alias_de_teste)
    resposta = client.get(reverse("mensagens:editar", args=[agendado.pk]))

    conteudo = resposta.content.decode()
    assert resposta.context["previa"] is not None
    assert 'value="salvar"' in conteudo
    assert 'value="enviar"' not in conteudo  # quem está na fila não "envia agora"
    assert 'name="enviar_em"' in conteudo
    assert agendado.enviar_em.year  # a data guardada volta preenchida
    assert 'value="' + resposta.context["form"].initial["enviar_em"] + '"' in conteudo


def test_salvar_agendado_depois_do_despacho_nao_sobrescreve(client, logado, alias_de_teste):
    """A corrida pela tela: abre a edição, o cron reivindica, o operador salva."""
    from mensagens.models import EnvioAgendado

    agendado = _guardar_agendado(alias_de_teste, assunto="Original")
    url = reverse("mensagens:editar", args=[agendado.pk])
    dados = _com_previa_em(
        client, url,
        {"alias": "financeiro", "para": "x@example.com", "assunto": "Tarde", "corpo": "<p>x</p>"},
    )
    EnvioAgendado.objects.filter(pk=agendado.pk).update(status=EnvioAgendado.Status.ENVIANDO)

    resposta = client.post(url, {**dados, "acao": "salvar", "enviar_em": _amanha_texto()})

    assert resposta["Location"] == reverse("mensagens:agendado", args=[agendado.pk])
    agendado.refresh_from_db()
    assert agendado.assunto == "Original"


def test_agendado_nao_pode_ser_enviado_por_fora_da_fila(client, logado, alias_de_teste):
    """Um POST forjado com acao=enviar sobre quem está na fila é ignorado."""
    from django.core import mail

    agendado = _guardar_agendado(alias_de_teste)
    url = reverse("mensagens:editar", args=[agendado.pk])
    dados = _com_previa_em(
        client, url,
        {"alias": "financeiro", "para": "x@example.com", "assunto": "Forjado", "corpo": "<p>x</p>"},
    )
    client.post(url, {**dados, "acao": "enviar"})

    assert mail.outbox == []


def test_tirar_da_fila_vira_rascunho_sem_cancelar(client, logado, alias_de_teste):
    agendado = _guardar_agendado(alias_de_teste)
    resposta = client.post(
        reverse("mensagens:editar", args=[agendado.pk]),
        {"acao": "salvar_rascunho", "alias": "financeiro", "para": "cliente@example.com",
         "assunto": "Na fila", "corpo": "<p>Oi</p>"},
    )

    assert resposta["Location"] == reverse("mensagens:editar", args=[agendado.pk])
    agendado.refresh_from_db()
    assert agendado.status == "rascunho"


def test_encerrado_nao_abre_para_edicao(client, logado, alias_de_teste):
    from mensagens.agendamento import cancelar

    agendado = _guardar_agendado(alias_de_teste)
    cancelar(agendado.pk)

    resposta = client.get(reverse("mensagens:editar", args=[agendado.pk]))

    assert resposta["Location"] == reverse("mensagens:agendado", args=[agendado.pk])


def test_detalhe_de_cancelado_mostra_tudo_e_os_anexos_que_havia(
    client, logado, alias_de_teste, tmp_path, settings
):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from mensagens.agendamento import agendar, cancelar
    from mensagens.anexos import criar_token, salvar_anexo
    from mensagens.montagem import DadosRedacao

    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("contrato.pdf", b"x" * 2048))
    from datetime import timedelta

    from django.utils import timezone

    agendado = agendar(
        alias_de_teste,
        DadosRedacao(
            para=["cliente@example.com"], cc=["copia@example.com"], assunto="Proposta",
            corpo_html="<p>Bom dia, são {{ hora }}</p>", in_reply_to="<abc@x.com>",
        ),
        timezone.now() + timedelta(days=2),
        token_anexos=token,
    )
    cancelar(agendado.pk)

    resposta = client.get(reverse("mensagens:agendado", args=[agendado.pk]))

    conteudo = resposta.content.decode()
    assert resposta.status_code == 200
    assert "Cancelado" in conteudo
    for esperado in ("Proposta", "cliente@example.com", "copia@example.com", "&lt;abc@x.com&gt;",
                     "contrato.pdf", "financeiro"):
        assert esperado in conteudo
    # os arquivos se foram, e a tela diz isso em vez de omitir a lista
    assert "já não existem" in conteudo
    # marcador como foi escrito: o valor só existe na hora da entrega
    assert "{{ hora }}" in conteudo
    # cancelado não oferece mais nada a fazer
    assert "Cancelar agendamento" not in conteudo
    assert ">Editar<" not in conteudo


def test_detalhe_de_agendado_oferece_editar_e_cancelar(client, logado, alias_de_teste):
    agendado = _guardar_agendado(alias_de_teste)
    conteudo = client.get(reverse("mensagens:agendado", args=[agendado.pk])).content.decode()

    assert reverse("mensagens:editar", args=[agendado.pk]) in conteudo
    assert reverse("mensagens:cancelar_agendado", args=[agendado.pk]) in conteudo


def test_detalhe_nao_executa_html_do_corpo(client, logado, alias_de_teste):
    agendado = _guardar_agendado(alias_de_teste, corpo_html="<p>ok</p><script>alert(1)</script>")
    conteudo = client.get(reverse("mensagens:agendado", args=[agendado.pk])).content.decode()

    assert "<script>alert" not in conteudo
    assert 'sandbox=""' in conteudo


def test_descartar_rascunho_exige_post_e_apaga(client, logado, alias_de_teste):
    from mensagens.agendamento import guardar_rascunho
    from mensagens.models import EnvioAgendado
    from mensagens.montagem import DadosRedacao

    rascunho = guardar_rascunho(alias_de_teste, DadosRedacao(para=[], assunto="x"))
    url = reverse("mensagens:descartar_rascunho", args=[rascunho.pk])

    assert client.get(url).status_code == 405
    assert EnvioAgendado.objects.count() == 1
    assert client.post(url).status_code == 302
    assert EnvioAgendado.objects.count() == 0


def test_descartar_nao_apaga_agendado(client, logado, alias_de_teste):
    from mensagens.models import EnvioAgendado

    agendado = _guardar_agendado(alias_de_teste)
    client.post(reverse("mensagens:descartar_rascunho", args=[agendado.pk]))

    assert EnvioAgendado.objects.filter(pk=agendado.pk).exists()


def test_editar_anexos_de_agendado_so_vale_ao_salvar(
    client, logado, alias_de_teste, tmp_path, settings
):
    """Pela tela, de ponta a ponta: remover um anexo e abandonar não muda nada."""
    from datetime import timedelta

    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    from mensagens.agendamento import agendar
    from mensagens.anexos import criar_token, listar_anexos, salvar_anexo
    from mensagens.montagem import DadosRedacao

    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("a.pdf", b"x"))
    agendado = agendar(
        alias_de_teste, DadosRedacao(para=["c@example.com"], corpo_html="<p>x</p>"),
        timezone.now() + timedelta(days=1), token_anexos=token,
    )
    url = reverse("mensagens:editar", args=[agendado.pk])

    aberta = client.get(url)
    copia = aberta.context["form"].initial["rascunho"]
    assert copia and copia != agendado.token_anexos
    anexo_id = aberta.context["anexos"][0].id

    client.post(url, {
        "acao": "previa", "alias": "financeiro", "para": "c@example.com", "corpo": "<p>x</p>",
        "rascunho": copia, "remover_anexo": anexo_id,
    })

    assert listar_anexos(copia) == []  # a cópia perdeu o arquivo...
    assert len(listar_anexos(agendado.token_anexos)) == 1  # ...a mensagem não


def test_admin_abre_rascunho_sem_data(client, logado, alias_de_teste):
    """`enviar_em` nulo não pode quebrar a lista nem a ficha do admin."""
    from mensagens.agendamento import guardar_rascunho
    from mensagens.montagem import DadosRedacao

    rascunho = guardar_rascunho(alias_de_teste, DadosRedacao(para=[], assunto="x"))

    assert client.get(reverse("admin:mensagens_envioagendado_changelist")).status_code == 200
    ficha = reverse("admin:mensagens_envioagendado_change", args=[rascunho.pk])
    assert client.get(ficha).status_code == 200
