"""Diagnóstico da configuração de aliases e do servidor de saída.

Imprime, por alias, tudo que foi resolvido do ambiente — inclusive o nome exato
da variável procurada para cada campo, para nunca ser preciso lembrar como o
slug vira nome de variável.

Nenhum valor de credencial é lido nem impresso: para os campos sensíveis o
comando reporta apenas `configurado` ou `faltando`.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

from mensagens.aliases import montar_aliases, nome_variavel
from mensagens.assinaturas import origem_da_assinatura


def _presenca(valor) -> str:
    return "configurado" if valor else "faltando"


class Command(BaseCommand):
    help = "Valida os aliases e mostra o que foi resolvido do ambiente."

    # Os system checks reprovam justamente quando a configuração está quebrada;
    # este comando precisa rodar nessa hora para dizer o porquê.
    requires_system_checks = []
    requires_migrations_checks = False

    def handle(self, *args, **options):
        aliases, erros = montar_aliases()
        padrao = settings.SMTP_PADRAO

        print(self.style.MIGRATE_HEADING("Servidor de saída (global)"))
        print(f"  host .......... {padrao['host']}:{padrao['port']}")
        print(f"  conta ......... {padrao['username'] or '(vazia)'}   [SMTP_USER]")
        print(f"  credencial .... {_presenca(padrao['password'])}   [SMTP_PASSWORD]")
        print(f"  tls / ssl ..... use_tls={padrao['use_tls']}  use_ssl={padrao['use_ssl']}")
        print(f"  timeout ....... {padrao['timeout']}s")
        print(f"  envelope ...... {settings.SMTP_ENVELOPE_FROM or '(usa o endereço do alias)'}")
        print(f"  domínios ok ... {', '.join(settings.ALIAS_ALLOWED_DOMAINS) or '(NENHUM!)'}")
        print(f"  assinaturas ... {settings.SIGNATURES_DIR}")
        print()

        for alias in aliases:
            var = nome_variavel(alias.slug, "SMTP_PASSWORD")
            propria = bool(os.environ.get(var, "").strip())
            print(self.style.MIGRATE_HEADING(f"[{alias.slug}]"))
            print(f"  From: ......... {alias.remetente}")
            print(f"  envelope ...... {alias.envelope}")
            print(f"  Reply-To ...... {alias.reply_to or '(nenhum)'}")
            print(f"  Message-ID .... @{alias.dominio_message_id}")
            print(f"  conta ......... {alias.smtp['username']} "
                  f"em {alias.smtp['host']}:{alias.smtp['port']} "
                  f"(tls={alias.smtp['use_tls']})")
            print(f"  credencial .... {'própria' if propria else 'herdada do global'} "
                  f"— procurei por {var}")
            print(f"  assinatura .... {origem_da_assinatura(alias)}")
            print(f"  variáveis ..... {nome_variavel(alias.slug, '*')}")
            print()

        if erros:
            self.stderr.write(self.style.ERROR(f"{len(erros)} problema(s):"))
            for erro in erros:
                self.stderr.write(self.style.ERROR(f"  - {erro}"))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(f"{len(aliases)} alias(es) OK."))
