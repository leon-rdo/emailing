"""Campo de lista de endereços e o formulário de redação."""

from email.utils import parseaddr

import pytest
from django.test import override_settings

from mensagens.forms import FormularioRedacao, dividir_enderecos

pytestmark = pytest.mark.django_db
DOMINIOS = override_settings(ALIAS_ALLOWED_DOMAINS=["leonardocosta.dev"])
BASE = {
    "SMTP_USER": "me@leonardocosta.dev",
    "SMTP_PASSWORD": "segredo",
    "ALIASES": "financeiro",
    "ALIAS_FINANCEIRO_ADDRESS": "financeiro@leonardocosta.dev",
}


def test_divide_por_virgula():
    assert dividir_enderecos("a@x.com, b@x.com") == ["a@x.com", "b@x.com"]


def test_preserva_nome_de_exibicao():
    assert dividir_enderecos("Fulano <a@x.com>") == ["Fulano <a@x.com>"]


def test_ignora_lixo_sem_arroba():
    assert dividir_enderecos("a@x.com, , not-an-email") == ["a@x.com"]


def test_string_vazia_vira_lista_vazia():
    assert dividir_enderecos("") == []
    assert dividir_enderecos("   ") == []


def test_nome_com_virgula_entre_aspas_nao_quebra_a_divisao():
    # getaddresses entende aspas — um .split(",") ingênuo cortaria no meio do nome.
    resultado = dividir_enderecos('"Silva, João" <joao@x.com>, outro@x.com')
    assert len(resultado) == 2
    assert resultado[1] == "outro@x.com"
    # formataddr codifica nome não-ASCII como encoded-word (RFC 2047) — é o
    # cabeçalho de e-mail exigindo isso, não um defeito da divisão em si.
    nome, endereco = parseaddr(resultado[0])
    assert endereco == "joao@x.com"


@DOMINIOS
def test_formulario_recusa_sem_destinatario(ambiente_de_aliases):
    from mensagens.aliases import carregar_aliases

    ambiente_de_aliases(**BASE)
    form = FormularioRedacao(
        {"alias": "financeiro", "para": "", "corpo": "<p>oi</p>", "acao": "previa"},
        aliases=carregar_aliases(),
    )
    assert not form.is_valid()
    assert "para" in form.errors


@DOMINIOS
def test_formulario_recusa_endereco_invalido(ambiente_de_aliases):
    from mensagens.aliases import carregar_aliases

    ambiente_de_aliases(**BASE)
    form = FormularioRedacao(
        {"alias": "financeiro", "para": "isto-nao-e-email", "corpo": "oi"},
        aliases=carregar_aliases(),
    )
    assert not form.is_valid()


@DOMINIOS
def test_formulario_recusa_excesso_de_destinatarios(ambiente_de_aliases, settings):
    from mensagens.aliases import carregar_aliases

    ambiente_de_aliases(**BASE)
    settings.MAX_DESTINATARIOS = 2
    muitos = ", ".join(f"pessoa{i}@x.com" for i in range(3))
    form = FormularioRedacao(
        {"alias": "financeiro", "para": muitos, "corpo": "oi"}, aliases=carregar_aliases()
    )
    assert not form.is_valid()
    assert any("MAX_DESTINATARIOS" not in e and "limite" in e for e in form.non_field_errors())


@DOMINIOS
def test_formulario_valido_com_para_e_cc(ambiente_de_aliases):
    from mensagens.aliases import carregar_aliases

    ambiente_de_aliases(**BASE)
    form = FormularioRedacao(
        {"alias": "financeiro", "para": "c@x.com", "cc": "d@x.com", "corpo": "<p>oi</p>"},
        aliases=carregar_aliases(),
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["para"] == ["c@x.com"]
    assert form.cleaned_data["cc"] == ["d@x.com"]
