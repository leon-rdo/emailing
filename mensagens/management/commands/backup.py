"""Cria, confere e rotaciona backups do banco. É isto que o cron chama.

`--conferir` responde a pergunta que só aparece na hora ruim: este arquivo
serve para restaurar? Inclui a checagem que ninguém lembra de fazer — se as
senhas SMTP lá dentro abrem com o `SECRET_KEY` que a máquina tem agora.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from mensagens import backup as mod_backup


class Command(BaseCommand):
    help = "Faz uma cópia verificada do banco, rotacionando as antigas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--conferir", nargs="?", const="", default=None, metavar="ARQUIVO",
            help="não cria nada; diz se um backup serve para restaurar "
                 "(sem argumento, o mais recente).",
        )
        parser.add_argument("--listar", action="store_true", help="lista os backups.")
        parser.add_argument(
            "--manter", type=int, default=None,
            help="sobrepõe BACKUP_MANTER só nesta execução. 0 desliga a rotação.",
        )
        parser.add_argument("--json", action="store_true", dest="como_json")

    def handle(self, *args, **options):
        como_json = options["como_json"]
        try:
            if options["conferir"] is not None:
                self._conferir(options["conferir"], como_json)
            elif options["listar"]:
                self._listar(como_json)
            else:
                self._criar(options["manter"], como_json)
        except mod_backup.ErroBackup as exc:
            raise CommandError(str(exc)) from exc

    def _criar(self, manter, como_json):
        feito = mod_backup.criar()
        apagados = mod_backup.rotacionar(manter)

        if como_json:
            self.stdout.write(json.dumps({
                "ok": True,
                "arquivo": str(feito.caminho),
                "manifesto": feito.manifesto,
                "rotacionados": [c.name for c in apagados],
            }, ensure_ascii=False))
            return

        kib = feito.tamanho / 1024
        self.stdout.write(
            self.style.SUCCESS(f"{feito.caminho.name} — {kib:.0f} KiB, integridade ok")
        )
        conteudo = feito.manifesto["conteudo"]
        self.stdout.write(
            f"  {conteudo['contas']} conta(s), {conteudo['aliases']} alias(es), "
            f"{conteudo['registros']} registro(s), "
            f"{conteudo['agendados_pendentes']} agendado(s) pendente(s)"
        )
        self.stdout.write(f"  em {feito.caminho.parent}")
        for caminho in apagados:
            self.stdout.write(f"  rotacionado: {caminho.name}")

    def _listar(self, como_json):
        caminhos = mod_backup.listar()
        if como_json:
            idade = mod_backup.idade_do_ultimo()
            self.stdout.write(json.dumps({
                "ok": bool(caminhos),
                "pasta": str(mod_backup.pasta()),
                "total": len(caminhos),
                "horas_desde_o_ultimo": (
                    round(idade.total_seconds() / 3600, 1) if idade else None
                ),
                "backups": [
                    {"arquivo": c.name, "tamanho": c.stat().st_size} for c in caminhos
                ],
            }, ensure_ascii=False))
            return

        if not caminhos:
            self.stdout.write(f"Nenhum backup em {mod_backup.pasta()}.")
            return
        for caminho in caminhos:
            self.stdout.write(f"{caminho.name}  {caminho.stat().st_size / 1024:.0f} KiB")
        self.stdout.write(f"{len(caminhos)} backup(s) em {mod_backup.pasta()}.")

    def _conferir(self, alvo, como_json):
        resultado = mod_backup.conferir(Path(alvo) if alvo else None)

        if como_json:
            self.stdout.write(json.dumps(resultado, ensure_ascii=False))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING(Path(resultado["arquivo"]).name))
            self.stdout.write(f"  tamanho ....... {resultado['tamanho'] / 1024:.0f} KiB")
            self.stdout.write(f"  integridade ... {resultado['integridade']}")
            self.stdout.write(f"  SECRET_KEY .... {resultado['secret_key']}")
            manifesto = resultado.get("manifesto") or {}
            if manifesto.get("conteudo"):
                self.stdout.write(f"  conteúdo ...... {manifesto['conteudo']}")
            if manifesto.get("ultima_migracao"):
                self.stdout.write(f"  migração ...... {manifesto['ultima_migracao']}")
            if resultado["restauravel"]:
                self.stdout.write(self.style.SUCCESS("Serve para restaurar."))
            else:
                self.stderr.write(self.style.ERROR("NÃO serve para restaurar."))

        if not resultado["restauravel"]:
            raise SystemExit(1)
