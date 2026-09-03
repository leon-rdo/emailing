"""Aliases de envio, carregados 100% do ambiente.

Formato (ver `.env.example`):

    ALIASES="financeiro,contato"
    ALIAS_FINANCEIRO_ADDRESS="financeiro@leonardocosta.dev"
    ALIAS_FINANCEIRO_NAME="Leonardo Costa"

`<SLUG>` é o slug em maiúsculas com todo caractere não-alfanumérico virando `_`.
Como ninguém precisa lembrar essa regra, `manage.py verificar_config` imprime o
nome exato que foi procurado para cada campo.

A trava mais importante daqui é `ALIAS_ALLOWED_DOMAINS`: um `From:` fora do
domínio autenticado não fica alinhado ao DMARC e vai direto para spam. Um alias
com domínio de fora é erro de configuração, não aviso.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from email.utils import formataddr
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email

_NAO_ALFANUM = re.compile(r"[^A-Z0-9]")

_cache: list[Alias] | None = None


def nome_variavel(slug: str, sufixo: str) -> str:
    """`("financeiro", "ADDRESS")` → `"ALIAS_FINANCEIRO_ADDRESS"`."""
    return f"ALIAS_{_NAO_ALFANUM.sub('_', slug.upper())}_{sufixo}"


@dataclass(frozen=True)
class Alias:
    slug: str
    endereco: str
    nome: str
    reply_to: str
    smtp: dict
    assinatura_html: str
    assinatura_arquivo: Path | None

    @property
    def dominio(self) -> str:
        return self.endereco.rpartition("@")[2]

    @property
    def remetente(self) -> str:
        """O valor do cabeçalho `From:`.

        Sempre via `formataddr`: montar `"Nome <addr>"` à mão produz cabeçalho
        inválido quando o nome tem acento.
        """
        return formataddr((self.nome, self.endereco)) if self.nome else self.endereco

    @property
    def envelope(self) -> str:
        """O `MAIL FROM` do SMTP — independente do cabeçalho `From:`."""
        return settings.SMTP_ENVELOPE_FROM or self.endereco

    @property
    def dominio_message_id(self) -> str:
        """Vários filtros conferem se o domínio do Message-ID bate com o From."""
        return settings.MESSAGE_ID_DOMAIN or self.dominio

    def __str__(self) -> str:
        return f"{self.slug} <{self.endereco}>"


def _smtp_do_alias(slug: str) -> dict:
    """SMTP do alias: cada campo cai no valor global quando não é sobrescrito."""
    padrao = settings.SMTP_PADRAO
    bruto = {
        sufixo: os.environ.get(nome_variavel(slug, f"SMTP_{sufixo.upper()}"), "").strip()
        for sufixo in ("host", "port", "username", "password", "use_tls", "use_ssl")
    }
    verdadeiros = {"1", "true", "yes", "on", "sim"}
    return {
        "host": bruto["host"] or padrao["host"],
        "port": int(bruto["port"]) if bruto["port"] else padrao["port"],
        "username": bruto["username"] or padrao["username"],
        "password": bruto["password"] or padrao["password"],
        "use_tls": bruto["use_tls"].lower() in verdadeiros if bruto["use_tls"]
        else padrao["use_tls"],
        "use_ssl": bruto["use_ssl"].lower() in verdadeiros if bruto["use_ssl"]
        else padrao["use_ssl"],
        "timeout": padrao["timeout"],
    }


def montar_aliases() -> tuple[list[Alias], list[str]]:
    """Lê o ambiente e devolve `(aliases, erros)`. Não levanta exceção.

    É a forma usada pelos system checks e pelo `verificar_config`, que precisam
    relatar todos os problemas de uma vez em vez de morrer no primeiro.
    """
    erros: list[str] = []
    aliases: list[Alias] = []

    slugs = [s.strip() for s in os.environ.get("ALIASES", "").split(",") if s.strip()]
    if not slugs:
        return [], ["ALIASES está vazia: nenhum alias configurado."]

    vistos: set[str] = set()
    dominios_ok = settings.ALIAS_ALLOWED_DOMAINS

    for slug in slugs:
        if slug in vistos:
            erros.append(f"Alias '{slug}' aparece duas vezes em ALIASES.")
            continue
        vistos.add(slug)

        var_endereco = nome_variavel(slug, "ADDRESS")
        endereco = os.environ.get(var_endereco, "").strip()
        if not endereco:
            erros.append(f"Alias '{slug}': falta {var_endereco}.")
            continue
        try:
            validate_email(endereco)
        except ValidationError:
            erros.append(f"Alias '{slug}': {var_endereco}='{endereco}' não é um e-mail válido.")
            continue

        dominio = endereco.rpartition("@")[2].lower()
        if dominios_ok and dominio not in dominios_ok:
            erros.append(
                f"Alias '{slug}': domínio '{dominio}' não está em ALIAS_ALLOWED_DOMAINS "
                f"({', '.join(dominios_ok)}). Enviar com From: fora do domínio autenticado "
                "quebra o alinhamento do DMARC e a mensagem vai para spam."
            )
            continue

        smtp = _smtp_do_alias(slug)
        if not smtp["username"]:
            erros.append(f"Alias '{slug}': sem usuário SMTP (defina SMTP_USER).")
        if not smtp["password"]:
            erros.append(
                f"Alias '{slug}': sem senha SMTP (defina SMTP_PASSWORD ou "
                f"{nome_variavel(slug, 'SMTP_PASSWORD')})."
            )
        if smtp["use_tls"] and smtp["use_ssl"]:
            erros.append(f"Alias '{slug}': USE_TLS e USE_SSL são mutuamente exclusivos.")

        reply_to = os.environ.get(nome_variavel(slug, "REPLY_TO"), "").strip()
        if reply_to:
            try:
                validate_email(reply_to)
            except ValidationError:
                erros.append(f"Alias '{slug}': REPLY_TO='{reply_to}' não é um e-mail válido.")
                reply_to = ""

        arquivo = os.environ.get(nome_variavel(slug, "SIGNATURE_FILE"), "").strip()
        aliases.append(
            Alias(
                slug=slug,
                endereco=endereco,
                nome=os.environ.get(nome_variavel(slug, "NAME"), "").strip(),
                reply_to=reply_to,
                smtp=smtp,
                assinatura_html=os.environ.get(
                    nome_variavel(slug, "SIGNATURE_HTML"), ""
                ).strip(),
                assinatura_arquivo=Path(settings.SIGNATURES_DIR) / (arquivo or f"{slug}.html"),
            )
        )

    return aliases, erros


def carregar_aliases() -> list[Alias]:
    """Aliases válidos, em cache. Levanta `ImproperlyConfigured` se houver erro."""
    global _cache
    if _cache is None:
        aliases, erros = montar_aliases()
        if erros:
            raise ImproperlyConfigured(
                "Configuração de aliases inválida:\n  - " + "\n  - ".join(erros)
            )
        _cache = aliases
    return _cache


def alias_por_slug(slug: str) -> Alias:
    for alias in carregar_aliases():
        if alias.slug == slug:
            return alias
    raise KeyError(f"Alias desconhecido: {slug!r}")


def limpar_cache() -> None:
    """Usado nos testes, que trocam o ambiente entre os casos."""
    global _cache
    _cache = None
