"""Despacha os envios agendados cuja hora chegou. É isto que o cron chama.

Silencioso quando não há nada a fazer: roda de minuto em minuto, e uma linha
por execução encheria o log de "nada aconteceu". Use `-v 2` para ver as
execuções vazias.

A trava contra despacho duplo mora em `agendamento.reivindicar()`, não aqui — o
`flock` da linha do cron é só o cinto.
"""

import json

from django.core.management.base import BaseCommand
from django.utils import timezone

from mensagens.agendamento import despachar_pendentes
from mensagens.models import EnvioAgendado


class Command(BaseCommand):
    help = "Envia os agendamentos vencidos, respeitando o teto por execução."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limite", type=int, default=None,
            help="sobrepõe AGENDADOS_MAX_POR_EXECUCAO só nesta execução.",
        )
        parser.add_argument(
            "--conferir", action="store_true",
            help="lista o que seria despachado agora e não envia nada.",
        )
        parser.add_argument("--json", action="store_true", dest="como_json")

    def handle(self, *args, **options):
        como_json = options["como_json"]
        agora = timezone.now()

        if options["conferir"]:
            self._conferir(agora, options["limite"], como_json)
            return

        despachados = despachar_pendentes(limite=options["limite"], agora=agora)

        if como_json:
            self.stdout.write(json.dumps({
                "ok": True,
                "total": len(despachados),
                "despachados": [
                    {
                        "id": a.pk,
                        "status": a.status,
                        "alias": a.alias.slug,
                        "tentativas": a.tentativas,
                        "erro": a.erro,
                        "registro": a.registro_id,
                    }
                    for a in despachados
                ],
            }, ensure_ascii=False))
            return

        if not despachados:
            if options["verbosity"] >= 2:
                self.stdout.write("Nada vencido.")
            return

        for agendado in despachados:
            linha = f"#{agendado.pk} [{agendado.alias.slug}] {agendado.get_status_display()}"
            if agendado.status == EnvioAgendado.Status.ENVIADO:
                self.stdout.write(self.style.SUCCESS(linha))
            elif agendado.status == EnvioAgendado.Status.FALHOU:
                self.stderr.write(self.style.ERROR(f"{linha} — {agendado.erro}"))
            else:
                # Voltou para "agendado": falhou e tem retentativa marcada.
                quando = timezone.localtime(agendado.enviar_em).strftime("%d/%m %H:%M")
                self.stdout.write(
                    self.style.WARNING(
                        f"{linha} — tentativa {agendado.tentativas} falhou, "
                        f"tenta de novo às {quando}: {agendado.erro}"
                    )
                )

    def _conferir(self, agora, limite, como_json):
        vencidos = list(
            EnvioAgendado.objects.filter(
                status=EnvioAgendado.Status.AGENDADO, enviar_em__lte=agora
            ).select_related("alias").order_by("enviar_em")[: limite or 100]
        )
        if como_json:
            self.stdout.write(json.dumps({
                "ok": True,
                "acao": "conferir",
                "total": len(vencidos),
                "vencidos": [
                    {
                        "id": a.pk,
                        "alias": a.alias.slug,
                        "para": a.para,
                        "assunto": a.assunto,
                        "enviar_em": a.enviar_em.isoformat(),
                        "tentativas": a.tentativas,
                    }
                    for a in vencidos
                ],
            }, ensure_ascii=False))
            return

        if not vencidos:
            self.stdout.write("Nada vencido.")
            return
        for agendado in vencidos:
            quando = timezone.localtime(agendado.enviar_em).strftime("%d/%m/%Y %H:%M")
            self.stdout.write(
                f"#{agendado.pk} [{agendado.alias.slug}] {quando} → "
                f"{agendado.destinatarios} — {agendado.assunto or '(sem assunto)'}"
            )
        self.stdout.write(self.style.WARNING(f"{len(vencidos)} vencido(s). Nada enviado."))
