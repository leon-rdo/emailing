"""Servidor MCP por stdio — o que a chave ssh restrita executa.

Não se chama à mão: o Claude Code abre `ssh -T emailing-mcp`, e o
`authorized_keys` força `command="/usr/local/bin/emailing mcp",restrict`. O
processo dura a sessão do Claude Code e morre com o ssh (EOF no stdin).

**Nada aqui escreve no stdout**: ele é o fio do protocolo, e qualquer byte fora
do JSON-RPC corrompe a sessão. Log vai para o stderr (o Claude Code o mostra nos
logs do MCP) e, para as ações que mudam algo, também para o syslog com a
etiqueta `emailing-mcp` (`journalctl -t emailing-mcp`) — a trilha que fica na
máquina, independente do cliente.
"""

import logging
from logging.handlers import SysLogHandler

from django.core.management.base import BaseCommand


def _ligar_syslog() -> None:
    try:
        handler = SysLogHandler(address="/dev/log")
    except OSError:
        return  # sem syslog (contêiner, macOS): o stderr continua
    handler.ident = "emailing-mcp: "
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    for nome in ("mensagens.mcp_servidor", "mensagens.caixa"):
        logging.getLogger(nome).addHandler(handler)


class Command(BaseCommand):
    help = "Servidor MCP (stdio) para o Claude Code enviar e ler e-mail. Ver docs/operacao.md."

    # Os checks escreveriam avisos e atrasariam cada abertura de sessão.
    requires_system_checks = []

    def handle(self, *args, **options):
        _ligar_syslog()
        from mensagens.mcp_servidor import servidor

        servidor.run(transport="stdio")
