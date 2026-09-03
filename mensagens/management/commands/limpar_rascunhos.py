"""Apaga pastas de rascunho (anexos pendentes) abandonadas."""

from django.conf import settings
from django.core.management.base import BaseCommand

from mensagens.anexos import limpar_rascunhos_expirados


class Command(BaseCommand):
    help = "Apaga rascunhos de anexos mais velhos que RASCUNHOS_TTL_DIAS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias", type=int, default=None,
            help="sobrepõe RASCUNHOS_TTL_DIAS só nesta execução",
        )

    def handle(self, *args, **options):
        ttl = options["dias"] if options["dias"] is not None else settings.RASCUNHOS_TTL_DIAS
        apagados = limpar_rascunhos_expirados(ttl)
        self.stdout.write(
            self.style.SUCCESS(f"{apagados} rascunho(s) com mais de {ttl} dia(s) apagado(s).")
        )
