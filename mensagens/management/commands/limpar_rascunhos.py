"""Apaga pastas de rascunho (anexos pendentes) abandonadas.

Menos as de mensagem agendada ou salva como rascunho: aqueles anexos precisam
sobreviver até a hora do despacho (ou até o operador voltar), que pode ser depois
do TTL. Ver `anexos.limpar_rascunhos_expirados`.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from mensagens.agendamento import expirar_rascunhos, tokens_pendentes
from mensagens.anexos import limpar_rascunhos_expirados


class Command(BaseCommand):
    help = (
        "Apaga pastas de anexos mais velhas que RASCUNHOS_TTL_DIAS e rascunhos salvos "
        "parados há mais de RASCUNHO_SALVO_EXPIRA_DIAS."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias", type=int, default=None,
            help="sobrepõe RASCUNHOS_TTL_DIAS só nesta execução",
        )

    def handle(self, *args, **options):
        ttl = options["dias"] if options["dias"] is not None else settings.RASCUNHOS_TTL_DIAS
        # Primeiro os rascunhos salvos vencidos, para os anexos deles saírem de
        # `tokens_pendentes()` antes de a lista ser montada.
        expirados = expirar_rascunhos(settings.RASCUNHO_SALVO_EXPIRA_DIAS)
        if expirados:
            self.stdout.write(
                f"{expirados} rascunho(s) salvo(s) sem alteração há mais de "
                f"{settings.RASCUNHO_SALVO_EXPIRA_DIAS} dia(s) apagado(s)."
            )
        protegidos = tokens_pendentes()
        apagados = limpar_rascunhos_expirados(ttl, protegidos)
        self.stdout.write(
            self.style.SUCCESS(f"{apagados} rascunho(s) com mais de {ttl} dia(s) apagado(s).")
        )
        if protegidos:
            self.stdout.write(
                f"{len(protegidos)} preservado(s) por agendamento pendente ou rascunho salvo."
            )
