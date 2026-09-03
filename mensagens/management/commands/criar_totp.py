"""Matrícula do segundo fator.

Gera um dispositivo TOTP para o usuário e mostra o QR na própria janela do
terminal — assim a matrícula acontece dentro do servidor, que é onde o
dispositivo é criado, sem passar por lugar nenhum no caminho.

Uso:

    manage.py criar_totp leonardo
    manage.py criar_totp leonardo --substituir   # descarta os anteriores
"""

import qrcode
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Cria um dispositivo TOTP e mostra o QR para escanear no autenticador."

    def add_arguments(self, parser):
        parser.add_argument("usuario", help="username do dono da conta")
        parser.add_argument(
            "--substituir",
            action="store_true",
            help="apaga os dispositivos existentes antes de criar o novo",
        )
        parser.add_argument("--nome", default="principal", help="nome do dispositivo")

    def handle(self, *args, **options):
        Usuario = get_user_model()
        try:
            usuario = Usuario.objects.get(username=options["usuario"])
        except Usuario.DoesNotExist as exc:
            raise CommandError(f"Usuário {options['usuario']!r} não existe.") from exc

        existentes = TOTPDevice.objects.filter(user=usuario)
        if existentes.exists():
            if not options["substituir"]:
                raise CommandError(
                    f"{usuario.username} já tem {existentes.count()} dispositivo(s). "
                    "Use --substituir para trocar."
                )
            existentes.delete()

        dispositivo = TOTPDevice.objects.create(
            user=usuario, name=options["nome"], confirmed=True
        )

        qr = qrcode.QRCode(border=1)
        qr.add_data(dispositivo.config_url)
        qr.print_ascii(invert=True)

        print()
        print(f"Dispositivo '{dispositivo.name}' criado para {usuario.username}.")
        print("Escaneie o QR acima no seu autenticador (ou abra o link que o comando")
        print("acabou de codificar). Confira se o código de 6 dígitos entra no login")
        print("antes de fechar este terminal — o segredo não é exibido de novo.")
