"""Carga e validação dos aliases a partir do ambiente."""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from mensagens.aliases import (
    Alias,
    alias_por_slug,
    carregar_aliases,
    montar_aliases,
    nome_variavel,
)

BASE = {
    "SMTP_USER": "me@leonardocosta.dev",
    "SMTP_PASSWORD": "segredo-de-teste",
    "ALIASES": "financeiro,contato",
    "ALIAS_FINANCEIRO_ADDRESS": "financeiro@leonardocosta.dev",
    "ALIAS_FINANCEIRO_NAME": "Leonardo Costa",
    "ALIAS_CONTATO_ADDRESS": "contato@leonardocosta.dev",
}

DOMINIOS = override_settings(ALIAS_ALLOWED_DOMAINS=["leonardocosta.dev"])


def test_nome_variavel_normaliza_o_slug():
    assert nome_variavel("financeiro", "ADDRESS") == "ALIAS_FINANCEIRO_ADDRESS"
    assert nome_variavel("nota-fiscal", "NAME") == "ALIAS_NOTA_FISCAL_NAME"
    assert nome_variavel("a.b c", "SMTP_HOST") == "ALIAS_A_B_C_SMTP_HOST"


@DOMINIOS
def test_carrega_dois_aliases(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    aliases, erros = montar_aliases()
    assert erros == []
    assert [a.slug for a in aliases] == ["financeiro", "contato"]
    assert isinstance(aliases[0], Alias)


@DOMINIOS
def test_smtp_cai_no_global_quando_o_alias_nao_sobrescreve(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    financeiro = carregar_aliases()[0]
    assert financeiro.smtp["username"] == "me@leonardocosta.dev"
    assert financeiro.smtp["host"] == "smtpout.secureserver.net"
    assert financeiro.smtp["use_tls"] is True


@DOMINIOS
def test_sobrescrita_por_alias_vence_o_global(ambiente_de_aliases):
    ambiente_de_aliases(
        **BASE,
        ALIAS_CONTATO_SMTP_HOST="smtp.outro.com",
        ALIAS_CONTATO_SMTP_PORT="465",
        ALIAS_CONTATO_SMTP_USE_TLS="0",
        ALIAS_CONTATO_SMTP_USE_SSL="1",
    )
    contato = alias_por_slug("contato")
    assert contato.smtp["host"] == "smtp.outro.com"
    assert contato.smtp["port"] == 465
    assert contato.smtp["use_ssl"] is True
    # O que não foi sobrescrito continua vindo do global.
    assert contato.smtp["username"] == "me@leonardocosta.dev"


@DOMINIOS
def test_remetente_usa_formataddr_com_acento(ambiente_de_aliases):
    ambiente_de_aliases(**{**BASE, "ALIAS_FINANCEIRO_NAME": "Leonardo Matheus de Abreu Costa"})
    alias = alias_por_slug("financeiro")
    assert alias.remetente == (
        "Leonardo Matheus de Abreu Costa <financeiro@leonardocosta.dev>"
    )


@DOMINIOS
def test_alias_sem_nome_usa_so_o_endereco(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    assert alias_por_slug("contato").remetente == "contato@leonardocosta.dev"


@DOMINIOS
def test_dominio_de_fora_e_recusado(ambiente_de_aliases):
    ambiente_de_aliases(**{**BASE, "ALIAS_CONTATO_ADDRESS": "eu@gmail.com"})
    aliases, erros = montar_aliases()
    assert [a.slug for a in aliases] == ["financeiro"]
    assert any("DMARC" in e for e in erros)


@DOMINIOS
def test_endereco_malformado_e_recusado(ambiente_de_aliases):
    ambiente_de_aliases(**{**BASE, "ALIAS_CONTATO_ADDRESS": "isto-nao-e-email"})
    _, erros = montar_aliases()
    assert any("não é um e-mail válido" in e for e in erros)


@DOMINIOS
def test_endereco_ausente_e_recusado(ambiente_de_aliases):
    ambiente = dict(BASE)
    del ambiente["ALIAS_CONTATO_ADDRESS"]
    ambiente_de_aliases(**ambiente)
    _, erros = montar_aliases()
    assert any("falta ALIAS_CONTATO_ADDRESS" in e for e in erros)


@DOMINIOS
def test_slug_duplicado_e_recusado(ambiente_de_aliases):
    ambiente_de_aliases(**{**BASE, "ALIASES": "financeiro,financeiro"})
    aliases, erros = montar_aliases()
    assert len(aliases) == 1
    assert any("duas vezes" in e for e in erros)


@DOMINIOS
def test_lista_vazia_e_recusada(ambiente_de_aliases):
    ambiente_de_aliases(ALIASES="")
    _, erros = montar_aliases()
    assert erros == ["ALIASES está vazia: nenhum alias configurado."]


@DOMINIOS
def test_reply_to_invalido_e_recusado_mas_o_alias_sobrevive(ambiente_de_aliases):
    ambiente_de_aliases(**{**BASE, "ALIAS_FINANCEIRO_REPLY_TO": "quebrado@"})
    aliases, erros = montar_aliases()
    assert any("REPLY_TO" in e for e in erros)
    assert aliases[0].reply_to == ""


@DOMINIOS
def test_carregar_aliases_levanta_quando_ha_erro(ambiente_de_aliases):
    ambiente_de_aliases(**{**BASE, "ALIAS_CONTATO_ADDRESS": "eu@gmail.com"})
    with pytest.raises(ImproperlyConfigured):
        carregar_aliases()


@DOMINIOS
def test_alias_por_slug_desconhecido(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    with pytest.raises(KeyError):
        alias_por_slug("inexistente")
