"""Envia um e-mail de teste real por um alias — valida a configuração de SMTP
fim a fim, incluindo o que só se descobre na rede: credencial, TLS, o Titan
aceitando o envelope do alias."""

from django.core.management.base import BaseCommand, CommandError

from mensagens.aliases import alias_por_slug
from mensagens.envio import enviar_email
from mensagens.models import RegistroEnvio
from mensagens.montagem import DadosRedacao


class Command(BaseCommand):
    help = "Envia um e-mail de teste real por um alias."

    def add_arguments(self, parser):
        parser.add_argument("alias", help="slug do alias, ex.: financeiro")
        parser.add_argument("--para", required=True, help="destinatário do teste")

    def handle(self, *args, **options):
        try:
            alias = alias_por_slug(options["alias"])
        except KeyError as exc:
            raise CommandError(str(exc)) from exc

        dados = DadosRedacao(
            para=[options["para"]],
            assunto="Teste de envio — Emailing",
            corpo_html="<p>Mensagem de teste enviada por <code>manage.py testar_smtp</code>.</p>",
        )
        registro = enviar_email(alias, dados)

        if registro.status == RegistroEnvio.Status.ENVIADO:
            self.stdout.write(self.style.SUCCESS(f"Enviado. Message-ID: {registro.message_id}"))
        else:
            self.stderr.write(self.style.ERROR(f"Falha: {registro.erro}"))
            raise SystemExit(1)
