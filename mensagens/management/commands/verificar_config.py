"""Mostra as contas e os aliases cadastrados, e aponta o que está quebrado.

Não inspeciona senhas: para os campos sensíveis reporta apenas se estão
configurados e se abrem com o `SECRET_KEY` atual.

Com `--json` vira a forma de descobrir o que existe sem ler tela — é o que o
`manage.py enviar` espera que você consulte antes de escolher um `--alias`.
"""

import json

from django.core.management.base import BaseCommand

from mensagens.aliases import carregar_aliases, verificar_aliases
from mensagens.assinaturas import origem_da_assinatura
from mensagens.backup import avisos as avisos_de_backup
from mensagens.backup import idade_do_ultimo
from mensagens.models import ContaEmail, EnvioAgendado


class Command(BaseCommand):
    help = "Lista contas e aliases cadastrados e valida a configuração."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="como_json")

    def handle(self, *args, **options):
        if options["como_json"]:
            self._como_json()
            return
        contas = ContaEmail.objects.all()
        if not contas:
            self.stdout.write(
                "Nenhuma conta cadastrada. Cadastre uma em /admin/mensagens/contaemail/ "
                "ou rode `manage.py importar_aliases_do_env`."
            )

        for conta in contas:
            if conta.usar_ssl:
                cifra = "SSL direto"
            else:
                cifra = "STARTTLS" if conta.usar_tls else "NENHUMA"
            estado = "" if conta.ativa else "  (INATIVA)"
            print(self.style.MIGRATE_HEADING(f"conta: {conta.nome}{estado}"))
            print(f"  servidor ...... {conta.host}:{conta.porta} ({cifra})")
            print(f"  autentica como  {conta.usuario}")
            print(f"  credencial .... {'configurada' if conta.senha_cifrada else 'FALTANDO'}")
            print(f"  domínios ok ... {', '.join(conta.dominios) or '(NENHUM!)'}")
            print(f"  envelope ...... {conta.envelope_from or '(o próprio alias)'}")
            print(f"  timeout ....... {conta.timeout}s")
            recebimento = f"{conta.imap_host}:{conta.imap_porta}" if conta.imap_host else "(não)"
            print(f"  IMAP .......... {recebimento}")
            print()

        for alias in carregar_aliases():
            print(self.style.MIGRATE_HEADING(f"[{alias.slug}]"))
            print(f"  From: ......... {alias.remetente}")
            print(f"  envelope ...... {alias.envelope}")
            print(f"  Reply-To ...... {alias.reply_to or '(nenhum)'}")
            print(f"  Message-ID .... @{alias.dominio_message_id}")
            print(f"  conta ......... {alias.conta.nome}")
            print(f"  assinatura .... {origem_da_assinatura(alias)}")
            print()

        problemas = verificar_aliases()
        if problemas:
            self.stderr.write(self.style.ERROR(f"{len(problemas)} problema(s):"))
            for problema in problemas:
                self.stderr.write(self.style.ERROR(f"  - {problema}"))
            raise SystemExit(1)

        pendentes = EnvioAgendado.objects.filter(status=EnvioAgendado.Status.AGENDADO).count()
        if pendentes:
            self.stdout.write(f"{pendentes} envio(s) agendado(s) esperando despacho.")

        # Avisos, não problemas: não fazem o comando falhar, e por isso não
        # travam o `implantar.sh`, que roda este comando antes de reiniciar.
        for aviso in avisos_de_backup():
            self.stdout.write(self.style.WARNING(f"backup: {aviso}"))

        resumo = f"{contas.count()} conta(s), {len(carregar_aliases())} alias(es) OK."
        self.stdout.write(self.style.SUCCESS(resumo))

    def _como_json(self):
        """O suficiente para escolher um alias e conferir que ele funciona.

        Nada de senha, nem cifrada: o que interessa é se ela abre com o
        `SECRET_KEY` atual, e isso `verificar_aliases()` já responde em texto.
        """
        problemas = verificar_aliases()
        self.stdout.write(json.dumps({
            "ok": not problemas,
            "problemas": problemas,
            "aliases": [
                {
                    "slug": alias.slug,
                    "endereco": alias.endereco,
                    "remetente": alias.remetente,
                    "envelope": alias.envelope,
                    "reply_to": alias.reply_to,
                    "conta": alias.conta.nome,
                    "servidor": f"{alias.conta.host}:{alias.conta.porta}",
                    "cifra": "ssl" if alias.conta.usar_ssl else "starttls",
                    "assinatura": origem_da_assinatura(alias),
                    "imap": (
                        f"{alias.conta.imap_host}:{alias.conta.imap_porta}"
                        if alias.conta.imap_host else None
                    ),
                }
                for alias in carregar_aliases()
            ],
            "agendados_pendentes": EnvioAgendado.objects.filter(
                status=EnvioAgendado.Status.AGENDADO
            ).count(),
            "avisos": avisos_de_backup(),
            "horas_desde_o_backup": (
                round(idade_do_ultimo().total_seconds() / 3600, 1)
                if idade_do_ultimo() else None
            ),
        }, ensure_ascii=False))
        if problemas:
            raise SystemExit(1)
