"""Views do app."""

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import render
from django.utils.decorators import method_decorator

from .aliases import carregar_aliases
from .forms import FormularioLogin


@method_decorator(login_not_required, name="dispatch")
class Entrar(LoginView):
    """Login de página única: usuário, senha e código TOTP no mesmo formulário.

    O `OTPAuthenticationForm` do django-otp já faz a verificação do token com
    janela de drift e prevenção de replay (`TOTPDevice.last_t`) — é exatamente a
    roda que não vale a pena reinventar.
    """

    template_name = "mensagens/login.html"
    redirect_authenticated_user = True

    def get_form_class(self):
        return FormularioLogin if settings.OTP_OBRIGATORIO else AuthenticationForm


class Sair(LogoutView):
    pass


def inicio(request):
    """Provisório: some quando a tela de redação entrar (Etapa 5)."""
    return render(request, "mensagens/inicio.html", {"aliases": carregar_aliases()})
