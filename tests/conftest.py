import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


@pytest.fixture(autouse=True)
def _cache_de_aliases_limpo():
    """Os testes trocam o ambiente entre os casos; o cache não pode vazar."""
    from mensagens import aliases

    aliases.limpar_cache()
    yield
    aliases.limpar_cache()


@pytest.fixture
def ambiente_de_aliases(monkeypatch):
    """Substitui todo o bloco ALIAS_*/SMTP_* do ambiente por um cenário limpo."""

    def aplicar(**variaveis):
        for chave in list(os.environ):
            if chave.startswith(("ALIAS", "SMTP_")):
                monkeypatch.delenv(chave, raising=False)
        for chave, valor in variaveis.items():
            monkeypatch.setenv(chave, valor)

    return aplicar
