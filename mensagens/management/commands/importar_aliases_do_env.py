"""Traz para o banco os aliases que viviam no ambiente.

Ponte de mão única, para rodar uma vez na migração do `.env` para o admin.
Depois disso as variáveis `ALIASES`/`ALIAS_*`/`SMTP_*` e os arquivos de
assinatura em disco podem sair do servidor — quem manda passa a ser o admin.

É idempotente: rodar duas vezes não duplica nada.
"""

import os
import re
from pathlib import Path

from django.core.management.base import BaseCommand

from mensagens.models import Alias, ContaEmail

_NAO_ALFANUM = re.compile(r"[^A-Z0-9]")


def _var(slug: str, sufixo: str) -> str:
    nome = f"ALIAS_{_NAO_ALFANUM.sub('_', slug.upper())}_{sufixo}"
    return os.environ.get(nome, "").strip()


def _bool_do_env(nome: str, padrao: bool) -> bool:
    bruto = os.environ.get(nome, "").strip().lower()
    return bruto in {"1", "true", "yes", "on", "sim"} if bruto else padrao


class Command(BaseCommand):
    help = "Importa ALIASES/ALIAS_*/SMTP_* do ambiente para ContaEmail e Alias."

    def add_arguments(self, parser):
        parser.add_argument(
            "--assinaturas",
            default="",
            help="Diretório dos <slug>.html a importar (padrão: <DATA_DIR>/assinaturas).",
        )

    def handle(self, *args, **options):
        slugs = [s.strip() for s in os.environ.get("ALIASES", "").split(",") if s.strip()]
        if not slugs:
            self.stdout.write("ALIASES está vazia — nada a importar.")
            return

        usuario = os.environ.get("SMTP_USER", "").strip()
        senha = os.environ.get("SMTP_PASSWORD", "").strip()
        host = os.environ.get("SMTP_HOST", "").strip()
        if not usuario or not senha or not host:
            self.stderr.write(
                self.style.ERROR("SMTP_HOST, SMTP_USER e SMTP_PASSWORD são obrigatórios.")
            )
            raise SystemExit(1)

        from django.conf import settings

        dir_assinaturas = Path(
            options["assinaturas"] or getattr(settings, "DATA_DIR", Path(".")) / "assinaturas"
        )

        conta, criada = ContaEmail.objects.get_or_create(
            usuario=usuario,
            host=host,
            defaults={
                "nome": f"Importada do .env ({usuario})",
                "porta": int(os.environ.get("SMTP_PORT", "587")),
                "usar_tls": _bool_do_env("SMTP_USE_TLS", True),
                "usar_ssl": _bool_do_env("SMTP_USE_SSL", False),
                "timeout": int(os.environ.get("SMTP_TIMEOUT", "20")),
                "dominios_permitidos": os.environ.get("ALIAS_ALLOWED_DOMAINS", "").strip(),
                "envelope_from": os.environ.get("SMTP_ENVELOPE_FROM", "").strip(),
            },
        )
        if criada or not conta.senha_cifrada:
            conta.senha = senha
            conta.save()
        self.stdout.write(
            self.style.SUCCESS(f"conta {'criada' if criada else 'reaproveitada'}: {conta.nome}")
        )

        for ordem, slug in enumerate(slugs):
            endereco = _var(slug, "ADDRESS")
            if not endereco:
                self.stderr.write(self.style.WARNING(f"  {slug}: sem ADDRESS, pulando."))
                continue

            assinatura = _var(slug, "SIGNATURE_HTML")
            if not assinatura:
                arquivo = _var(slug, "SIGNATURE_FILE") or f"{slug}.html"
                caminho = dir_assinaturas / arquivo
                if caminho.is_file():
                    assinatura = caminho.read_text(encoding="utf-8").strip()

            alias, criado = Alias.objects.update_or_create(
                slug=slug,
                defaults={
                    "conta": conta,
                    "endereco": endereco,
                    "nome_exibicao": _var(slug, "NAME"),
                    "reply_to": _var(slug, "REPLY_TO"),
                    "assinatura_html": assinatura,
                    "ordem": ordem,
                    "ativo": True,
                },
            )
            marca = "criado" if criado else "atualizado"
            tem_assinatura = f", assinatura de {len(assinatura)} bytes" if assinatura else ""
            self.stdout.write(f"  alias {marca}: {alias.slug} <{alias.endereco}>{tem_assinatura}")

        self.stdout.write(
            self.style.SUCCESS(
                "\nPronto. As variáveis ALIASES/ALIAS_*/SMTP_* já podem sair do .env "
                "(o SECRET_KEY, não: é ele que abre as senhas guardadas)."
            )
        )
