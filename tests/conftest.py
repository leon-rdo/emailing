import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_teste")


@pytest.fixture
def conta_de_teste(db):
    """Uma conta SMTP fictícia, já com senha cifrada."""
    from mensagens.models import ContaEmail

    conta = ContaEmail(
        nome="Conta de teste",
        host="smtp.exemplo.test",
        porta=587,
        usuario="me@empresa.example",
        usar_tls=True,
        dominios_permitidos="empresa.example",
    )
    conta.senha = "segredo-de-teste"
    conta.save()
    return conta


@pytest.fixture
def alias_de_teste(conta_de_teste):
    """O alias usado pela maior parte dos testes: `financeiro`, com nome."""
    from mensagens.models import Alias

    return Alias.objects.create(
        conta=conta_de_teste,
        slug="financeiro",
        endereco="financeiro@empresa.example",
        nome_exibicao="Ana Souza",
    )


@pytest.fixture
def criar_alias(conta_de_teste):
    """Fábrica para os testes que precisam de mais de um alias."""
    from mensagens.models import Alias

    def fabricar(slug: str, endereco: str = "", **extra):
        return Alias.objects.create(
            conta=extra.pop("conta", conta_de_teste),
            slug=slug,
            endereco=endereco or f"{slug}@empresa.example",
            **extra,
        )

    return fabricar


@pytest.fixture
def imap(conta_de_teste, monkeypatch):
    """Um servidor IMAP falso no lugar do `imaplib.IMAP4_SSL`, e a conta de
    teste com recebimento ligado. Ver `tests/imap_falso.py`."""
    from imap_falso import ServidorFalso

    import mensagens.caixa

    servidor = ServidorFalso()
    monkeypatch.setattr(mensagens.caixa.imaplib, "IMAP4_SSL", servidor.conexao)
    conta_de_teste.imap_host = "imap.exemplo.test"
    conta_de_teste.save()
    return servidor
