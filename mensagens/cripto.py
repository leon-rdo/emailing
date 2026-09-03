"""Cifra as senhas SMTP guardadas no banco.

Antes as senhas viviam no `.env`, onde só quem tinha ssh as via. Passando as
contas para o admin, elas passam a viver no SQLite — e um backup do banco não
pode sair por aí com senha de e-mail em claro.

A chave é derivada do `SECRET_KEY` (HKDF-SHA256), então o arquivo do banco
sozinho não entrega nada. O preço: **trocar o `SECRET_KEY` torna as senhas
guardadas ilegíveis** e é preciso redigitá-las no admin. Está no README.
"""

from __future__ import annotations

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings


class SenhaIlegivel(Exception):
    """A senha guardada não abre com a chave atual (SECRET_KEY trocada?)."""


def _fernet() -> Fernet:
    # Sem cache de propósito: o SECRET_KEY muda entre testes (override_settings)
    # e um cache global devolveria a chave errada. HKDF é barato.
    derivada = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"emailing.senhas.smtp.v1",
        info=b"fernet",
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(derivada))


def cifrar(texto: str) -> str:
    return _fernet().encrypt(texto.encode()).decode() if texto else ""


def decifrar(cifrado: str) -> str:
    if not cifrado:
        return ""
    try:
        return _fernet().decrypt(cifrado.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise SenhaIlegivel(
            "A senha guardada não abre com o SECRET_KEY atual. Se ele foi "
            "trocado, redigite a senha da conta no admin."
        ) from exc
