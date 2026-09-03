"""Assinatura HTML de cada alias.

Mora no próprio alias, editável no admin. Antes era um arquivo em disco que só
quem tinha ssh conseguia trocar — o que fazia sentido enquanto a configuração
inteira vivia no `.env`, e deixou de fazer quando as contas foram para o admin.

A assinatura **não passa pelo sanitizador** — ver `montagem.py`.
"""

from __future__ import annotations

from .models import Alias


def assinatura_de(alias: Alias) -> str:
    """HTML da assinatura, ou string vazia se o alias não tiver uma."""
    return (alias.assinatura_html or "").strip()


def origem_da_assinatura(alias: Alias) -> str:
    """Descrição legível — usada no `verificar_config`."""
    assinatura = assinatura_de(alias)
    return f"{len(assinatura)} bytes" if assinatura else "nenhuma"
