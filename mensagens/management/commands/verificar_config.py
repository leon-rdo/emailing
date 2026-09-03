"""Mostra as contas e os aliases cadastrados, e aponta o que está quebrado.

Não inspeciona senhas: para os campos sensíveis reporta apenas se estão
configurados e se abrem com o `SECRET_KEY` atual.
"""

from django.core.management.base import BaseCommand

from mensagens.aliases import carregar_aliases, verificar_aliases
from mensagens.assinaturas import origem_da_assinatura
from mensagens.models import ContaEmail


class Command(BaseCommand):
    help = "Lista contas e aliases cadastrados e valida a configuração."

    def handle(self, *args, **options):
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

        resumo = f"{contas.count()} conta(s), {len(carregar_aliases())} alias(es) OK."
        self.stdout.write(self.style.SUCCESS(resumo))
