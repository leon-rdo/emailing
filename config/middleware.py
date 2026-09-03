"""Cabeçalhos de segurança e CSP com nonce por requisição.

Todo script inline das páginas carrega `nonce="{{ request.csp_nonce }}"`, então
qualquer outro script inline — um eventual XSS vindo de um `.eml` importado ou
de HTML colado no editor — é bloqueado pelo navegador.

Duas observações que ditam a política:

- `style-src` precisa de `'unsafe-inline'`: o Trix injeta um `<style>` em
  runtime e, sem isso, o editor perde o estilo em silêncio. Injeção de CSS não é
  vetor relevante num app de usuário único.
- O iframe `srcdoc` da pré-visualização **herda este CSP**. É o `img-src` daqui
  que decide se a foto da assinatura aparece na prévia — daí
  `HOSTS_IMAGENS_ASSINATURA`.
"""

import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

_CSP_MODELO = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: {imagens}; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class CabecalhosSegurancaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            _CSP_MODELO.format(
                nonce=request.csp_nonce, imagens=settings.HOSTS_IMAGENS_ASSINATURA
            ),
        )
        # Isto nunca deve aparecer em buscador. (Obscuridade não faz parte do
        # modelo de ameaça: o Certificate Transparency publica o subdomínio de
        # qualquer jeito. Quem protege é o TOTP e o lockout.)
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response


class ExigirVerificacaoOTPMiddleware:
    """Com `OTP_OBRIGATORIO`, sessão autenticada sem segundo fator não vale.

    O `OTPAuthenticationForm` só cobra o token de quem já tem um dispositivo
    cadastrado — um usuário sem dispositivo entraria só com a senha. Aqui a
    sessão meio-autenticada é encerrada em vez de tolerada: não existe estado
    intermediário para alguém explorar.
    """

    ISENTAS = ("/entrar/", "/sair/", "/static/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.OTP_OBRIGATORIO
            and request.user.is_authenticated
            and not request.user.is_verified()
            and not request.path.startswith(self.ISENTAS)
        ):
            logout(request)
            messages.error(
                request,
                "Esta conta não tem segundo fator cadastrado. Rode "
                "`manage.py criar_totp <usuário>` no servidor antes de entrar.",
            )
            return redirect(settings.LOGIN_URL)
        return self.get_response(request)
