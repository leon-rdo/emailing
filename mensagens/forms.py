"""Formulários do app."""

from django_otp import devices_for_user
from django_otp.forms import OTPAuthenticationForm


class FormularioLogin(OTPAuthenticationForm):
    """Login numa etapa só: usuário, senha e código no mesmo envio.

    O django-otp 1.7 passou a exigir que o dispositivo seja escolhido
    explicitamente: antes ele tentava todos com `match_token()`, o que
    registrava falha de verificação em dispositivos que nem estavam sendo
    usados e podia estrangular, por exemplo, os códigos de recuperação.

    Esse motivo não existe quando o usuário tem um dispositivo só — não há
    outro para estrangular. Então, se nada foi escolhido e existe exatamente um
    disponível, é ele. Com dois ou mais o comportamento padrão volta a valer e o
    seletor aparece, que é o certo: aí a escolha importa.
    """

    def _chosen_device(self, user):
        dispositivo = super()._chosen_device(user)
        if dispositivo is None:
            disponiveis = list(devices_for_user(user, for_verify=True))
            if len(disponiveis) == 1:
                dispositivo = disponiveis[0]
        return dispositivo
