"""Contas e aliases: cifragem da senha, validação de domínio, consultas."""

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from mensagens.aliases import alias_por_slug, carregar_aliases, verificar_aliases
from mensagens.cripto import SenhaIlegivel, cifrar, decifrar
from mensagens.models import Alias, ContaEmail

pytestmark = pytest.mark.django_db


# --- cifragem da senha SMTP -------------------------------------------


def test_senha_vai_e_volta():
    assert decifrar(cifrar("minha-senha")) == "minha-senha"


def test_senha_cifrada_nao_contem_o_texto_claro():
    cifrada = cifrar("minha-senha")
    assert "minha-senha" not in cifrada


def test_senha_vazia_continua_vazia():
    assert cifrar("") == ""
    assert decifrar("") == ""


def test_secret_key_trocado_torna_a_senha_ilegivel():
    """O aviso do README em forma de teste: trocar o SECRET_KEY exige
    redigitar as senhas das contas."""
    cifrada = cifrar("minha-senha")
    with override_settings(SECRET_KEY="outra-chave-completamente-diferente"):
        with pytest.raises(SenhaIlegivel):
            decifrar(cifrada)


def test_conta_guarda_a_senha_cifrada(conta_de_teste):
    conta = ContaEmail.objects.get(pk=conta_de_teste.pk)
    assert conta.senha == "segredo-de-teste"
    assert "segredo-de-teste" not in conta.senha_cifrada


# --- consultas --------------------------------------------------------


def test_carregar_aliases_respeita_ordem_e_ativo(criar_alias):
    criar_alias("segundo", ordem=2)
    criar_alias("primeiro", ordem=1)
    criar_alias("desligado", ordem=0, ativo=False)
    assert [a.slug for a in carregar_aliases()] == ["primeiro", "segundo"]


def test_alias_por_slug(alias_de_teste):
    assert alias_por_slug("financeiro").pk == alias_de_teste.pk


def test_alias_por_slug_desconhecido(alias_de_teste):
    with pytest.raises(KeyError):
        alias_por_slug("nao-existe")


def test_alias_inativo_nao_e_encontrado(criar_alias):
    criar_alias("oculto", ativo=False)
    with pytest.raises(KeyError):
        alias_por_slug("oculto")


# --- a interface que o resto do app consome ---------------------------


def test_remetente_usa_formataddr(alias_de_teste):
    assert alias_de_teste.remetente == "Leonardo Costa <financeiro@leonardocosta.dev>"


def test_remetente_sem_nome_e_so_o_endereco(criar_alias):
    assert criar_alias("contato").remetente == "contato@leonardocosta.dev"


def test_envelope_e_o_proprio_alias(alias_de_teste):
    assert alias_de_teste.envelope == "financeiro@leonardocosta.dev"


def test_envelope_fixo_da_conta_vence(conta_de_teste, criar_alias):
    conta_de_teste.envelope_from = "bounces@leonardocosta.dev"
    conta_de_teste.save()
    alias = criar_alias("x")
    assert alias.envelope == "bounces@leonardocosta.dev"


def test_smtp_monta_os_kwargs_da_conexao(alias_de_teste):
    smtp = alias_de_teste.smtp
    assert smtp["host"] == "smtp.exemplo.test"
    assert smtp["port"] == 587
    assert smtp["username"] == "me@leonardocosta.dev"
    assert smtp["password"] == "segredo-de-teste"
    assert smtp["use_tls"] is True
    assert smtp["timeout"] == 20


def test_dominio_do_message_id_e_o_do_alias(alias_de_teste):
    assert alias_de_teste.dominio_message_id == "leonardocosta.dev"


# --- validação --------------------------------------------------------


def test_alias_fora_do_dominio_da_conta_e_recusado(conta_de_teste):
    alias = Alias(conta=conta_de_teste, slug="fora", endereco="eu@gmail.com")
    with pytest.raises(ValidationError, match="DMARC"):
        alias.full_clean()


def test_dominios_derivam_da_conta_quando_nao_declarados(conta_de_teste):
    conta_de_teste.dominios_permitidos = ""
    conta_de_teste.save()
    assert conta_de_teste.dominios == ["leonardocosta.dev"]


def test_conta_com_varios_dominios(conta_de_teste, criar_alias):
    conta_de_teste.dominios_permitidos = "leonardocosta.dev, altaris.love"
    conta_de_teste.save()
    alias = Alias(conta=conta_de_teste, slug="outro", endereco="no-reply@altaris.love")
    alias.full_clean()  # não levanta


def test_tls_e_ssl_juntos_sao_recusados(conta_de_teste):
    conta_de_teste.usar_ssl = True
    with pytest.raises(ValidationError, match="mutuamente exclusiv"):
        conta_de_teste.full_clean()


def test_sem_cifra_nenhuma_e_recusado(conta_de_teste):
    conta_de_teste.usar_tls = False
    conta_de_teste.usar_ssl = False
    with pytest.raises(ValidationError, match="STARTTLS"):
        conta_de_teste.full_clean()


# --- diagnóstico ------------------------------------------------------


def test_verificar_aliases_sem_nenhum_cadastrado():
    problemas = verificar_aliases()
    assert len(problemas) == 1
    assert "Nenhum alias ativo" in problemas[0]


def test_verificar_aliases_tudo_certo(alias_de_teste):
    assert verificar_aliases() == []


def test_verificar_aliases_aponta_conta_sem_senha(conta_de_teste, criar_alias):
    criar_alias("x")
    conta_de_teste.senha_cifrada = ""
    conta_de_teste.save()
    assert any("sem senha" in p for p in verificar_aliases())


def test_verificar_aliases_aponta_conta_inativa(conta_de_teste, criar_alias):
    criar_alias("x")
    conta_de_teste.ativa = False
    conta_de_teste.save()
    assert any("inativa" in p for p in verificar_aliases())
