"""Configurações (contas, aliases, assinatura) e a separação por caixa."""

import smtplib
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from mensagens.forms import opcoes_de_alias
from mensagens.models import Alias, ContaEmail, RegistroEnvio

pytestmark = pytest.mark.django_db
SENHA = "uma-senha-bem-comprida-123"


@pytest.fixture
def logado(client, alias_de_teste):
    get_user_model().objects.create_superuser(
        username="leonardo", email="me@leonardocosta.dev", password=SENHA
    )
    with override_settings(OTP_OBRIGATORIO=False):
        client.post(reverse("mensagens:entrar"), {"username": "leonardo", "password": SENHA})


def _conta_pelo_formulario(**extra):
    dados = {
        "nome": "Hostinger — altaris.love", "host": "smtp.hostinger.com", "porta": "465",
        "usuario": "suporte@altaris.love", "senha": "segredo", "cifra": "ssl",
        "timeout": "20", "dominios_permitidos": "altaris.love", "envelope_from": "",
        "ativa": "on",
    }
    dados.update(extra)
    return dados


def test_telas_de_configuracao_carregam(client, logado, alias_de_teste):
    for nome, args in [
        ("config_contas", []), ("config_conta_nova", []), ("config_aliases", []),
        ("config_alias_novo", []), ("config_alias", [alias_de_teste.pk]),
        ("config_conta", [alias_de_teste.conta_id]),
    ]:
        resposta = client.get(reverse(f"mensagens:{nome}", args=args))
        assert resposta.status_code == 200, nome


def test_configuracoes_exigem_login(client):
    resposta = client.get(reverse("mensagens:config_contas"))
    assert resposta.status_code == 302
    assert "/entrar/" in resposta["Location"]


def test_criar_conta_cifra_a_senha_e_traduz_a_cifra(client, logado):
    resposta = client.post(reverse("mensagens:config_conta_nova"), _conta_pelo_formulario())
    assert resposta.status_code == 302
    conta = ContaEmail.objects.get(usuario="suporte@altaris.love")
    assert conta.usar_ssl and not conta.usar_tls
    assert conta.senha == "segredo"
    assert "segredo" not in conta.senha_cifrada


def test_editar_conta_com_senha_em_branco_mantem_a_atual(client, logado, conta_de_teste):
    antes = conta_de_teste.senha_cifrada
    dados = _conta_pelo_formulario(nome="Outro nome", senha="", cifra="tls", porta="587")
    resposta = client.post(reverse("mensagens:config_conta", args=[conta_de_teste.pk]), dados)
    assert resposta.status_code == 302
    conta_de_teste.refresh_from_db()
    assert conta_de_teste.nome == "Outro nome"
    assert conta_de_teste.senha_cifrada == antes
    assert conta_de_teste.usar_tls and not conta_de_teste.usar_ssl


def test_conta_nova_exige_senha(client, logado):
    resposta = client.post(reverse("mensagens:config_conta_nova"), _conta_pelo_formulario(senha=""))
    assert resposta.status_code == 200
    assert not ContaEmail.objects.filter(usuario="suporte@altaris.love").exists()


def test_senha_nunca_volta_para_a_tela(client, logado, conta_de_teste):
    html = client.get(reverse("mensagens:config_conta", args=[conta_de_teste.pk])).content.decode()
    assert "segredo-de-teste" not in html
    assert conta_de_teste.senha_cifrada not in html


def test_criar_alias_com_assinatura_html_cru(client, logado, conta_de_teste):
    assinatura = '<table style="color:#222"><tr><td>Leonardo</td></tr></table>'
    resposta = client.post(reverse("mensagens:config_alias_novo"), {
        "conta": conta_de_teste.pk, "slug": "suporte", "endereco": "suporte@leonardocosta.dev",
        "nome_exibicao": "Suporte", "reply_to": "", "assinatura_html": assinatura,
        "ativo": "on", "ordem": "5",
    })
    assert resposta.status_code == 302
    assert Alias.objects.get(slug="suporte").assinatura_html == assinatura  # sem sanitizar


def test_alias_fora_do_dominio_da_conta_e_recusado(client, logado, conta_de_teste):
    resposta = client.post(reverse("mensagens:config_alias_novo"), {
        "conta": conta_de_teste.pk, "slug": "x", "endereco": "x@outro-dominio.com",
        "ativo": "on", "ordem": "0",
    })
    assert resposta.status_code == 200
    assert "DMARC" in resposta.content.decode()


def test_slug_do_alias_nao_muda_depois_de_criado(client, logado, alias_de_teste):
    client.post(reverse("mensagens:config_alias", args=[alias_de_teste.pk]), {
        "conta": alias_de_teste.conta_id, "slug": "mudou", "endereco": alias_de_teste.endereco,
        "nome_exibicao": "Novo nome", "ativo": "on", "ordem": "0",
    })
    alias_de_teste.refresh_from_db()
    assert alias_de_teste.slug == "financeiro"
    assert alias_de_teste.nome_exibicao == "Novo nome"


def test_previa_da_assinatura_usa_a_montagem_do_envio(client, logado):
    resposta = client.post(
        reverse("mensagens:config_assinatura_previa"),
        {"assinatura_html": "<p>Leonardo <b>Costa</b></p><script>alert(1)</script>"},
    )
    corpo = resposta.json()
    assert corpo["ok"]
    assert "<!DOCTYPE html>" in corpo["html"]            # a moldura da prévia
    assert "Leonardo <b>Costa</b>" in corpo["html"]      # a assinatura, como foi escrita


def test_testar_conta_explica_senha_recusada(client, logado):
    with mock.patch("mensagens.views_configuracoes.smtplib.SMTP_SSL") as ssl_:
        ssl_.return_value.__enter__.return_value.login.side_effect = (
            smtplib.SMTPAuthenticationError(535, b"no")
        )
        resposta = client.post(reverse("mensagens:config_conta_testar"), {
            "host": "smtp.x.com", "porta": "465", "usuario": "a@x.com", "senha": "errada",
            "cifra": "ssl", "timeout": "5",
        })
    assert resposta.json() == {"ok": False, "erro": "O servidor recusou o usuário ou a senha."}


def test_testar_conta_sem_senha_usa_a_guardada(client, logado, conta_de_teste):
    with mock.patch("mensagens.views_configuracoes.smtplib.SMTP") as smtp:
        servidor = smtp.return_value.__enter__.return_value
        resposta = client.post(reverse("mensagens:config_conta_testar"), {
            "pk": conta_de_teste.pk, "host": "smtp.x.com", "porta": "587",
            "usuario": "a@x.com", "senha": "", "cifra": "tls", "timeout": "5",
        })
    assert resposta.json() == {"ok": True}
    servidor.starttls.assert_called_once()
    servidor.login.assert_called_once_with("a@x.com", "segredo-de-teste")
    servidor.sendmail.assert_not_called()  # testar não envia nada


# ------------------------------------------------------------ caixas


@pytest.fixture
def duas_caixas(alias_de_teste, criar_alias):
    outra = ContaEmail(
        nome="Hostinger — altaris.love", host="h", usuario="s@altaris.love",
        dominios_permitidos="altaris.love",
    )
    outra.senha = "x"
    outra.save()
    suporte = criar_alias("suporte", "suporte@altaris.love", conta=outra)
    return alias_de_teste.conta, outra, alias_de_teste, suporte


def _registro(alias, assunto):
    return RegistroEnvio.objects.create(
        alias=alias.slug, remetente=alias.remetente, para="x@y.com", assunto=assunto,
        message_id=f"<{assunto}@t>", status="enviado",
    )


def test_historico_filtra_pela_caixa(client, logado, duas_caixas):
    conta_a, conta_b, a, b = duas_caixas
    _registro(a, "da-leonardo")
    _registro(b, "da-altaris")

    tudo = client.get(reverse("mensagens:historico")).content.decode()
    assert "da-leonardo" in tudo and "da-altaris" in tudo

    so_b = client.get(reverse("mensagens:historico"), {"caixa": conta_b.pk}).content.decode()
    assert "da-altaris" in so_b and "da-leonardo" not in so_b


def test_menu_lista_as_caixas_so_quando_ha_mais_de_uma(client, logado, alias_de_teste):
    assert "Todas as caixas" not in client.get(reverse("mensagens:historico")).content.decode()


def test_menu_lista_as_caixas(client, logado, duas_caixas):
    html = client.get(reverse("mensagens:historico")).content.decode()
    assert "Todas as caixas" in html and "Hostinger — altaris.love" in html


def test_seletor_de_agrupa_por_caixa(duas_caixas):
    _, _, a, b = duas_caixas
    grupos = opcoes_de_alias([a, b])
    assert [nome for nome, _ in grupos] == ["Conta de teste", "Hostinger — altaris.love"]
    assert opcoes_de_alias([a]) == [(a.slug, str(a))]  # uma caixa só: lista simples


def test_escrever_pela_caixa_ja_escolhe_o_alias_dela(client, logado, duas_caixas):
    _, conta_b, _, b = duas_caixas
    resposta = client.get(reverse("mensagens:inicio"), {"caixa": conta_b.pk})
    assert resposta.context["form"].initial["alias"] == b.slug
