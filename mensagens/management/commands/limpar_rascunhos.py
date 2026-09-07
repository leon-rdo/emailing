"""Apaga pastas de rascunho (anexos pendentes) abandonadas.

Menos as de mensagem agendada: aqueles anexos precisam sobreviver até a hora do
despacho, que pode ser depois do TTL. Ver `anexos.limpar_rascunhos_expirados`.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from mensagens.agendamento import tokens_pendentes
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
        protegidos = tokens_pendentes()
        apagados = limpar_rascunhos_expirados(ttl, protegidos)
        self.stdout.write(
            self.style.SUCCESS(f"{apagados} rascunho(s) com mais de {ttl} dia(s) apagado(s).")
        )
        if protegidos:
            self.stdout.write(f"{len(protegidos)} preservado(s) por envio agendado pendente.")
