"""Assinatura HTML de cada alias.

Mora num arquivo, não numa variável de ambiente, porque `EnvironmentFile` do
systemd não aceita valor multilinha e uma assinatura real tem alguns KB de HTML
com aspas e quebras de linha. O que vai na variável é o *caminho*.

Lida do disco a cada render, de propósito: são poucos KB e um usuário só, e
assim você edita o arquivo por ssh e vê o resultado na próxima pré-visualização,
sem reiniciar o serviço.

A assinatura **não passa pelo sanitizador** — ver `montagem.py`.
"""

from __future__ import annotations

from .aliases import Alias


def assinatura_de(alias: Alias) -> str:
    """HTML da assinatura, ou string vazia se o alias não tiver uma."""
    if alias.assinatura_html:
        return alias.assinatura_html
    caminho = alias.assinatura_arquivo
    if caminho and caminho.is_file():
        return caminho.read_text(encoding="utf-8").strip()
    return ""


def origem_da_assinatura(alias: Alias) -> str:
    """Descrição legível de onde a assinatura veio — usada no verificar_config."""
    if alias.assinatura_html:
        return f"inline ({len(alias.assinatura_html)} bytes)"
    caminho = alias.assinatura_arquivo
    if caminho and caminho.is_file():
        return f"{caminho} ({caminho.stat().st_size} bytes)"
    return f"AUSENTE (esperado em {caminho})"
