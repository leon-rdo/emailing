#!/usr/bin/env bash
# Instalado em /usr/local/bin/emailing pelo deploy/implantar.sh.
#
# Roda um comando de manage.py como o usuário do serviço — que é quem tem acesso
# ao banco, aos rascunhos e ao .env. Existe porque a alternativa é digitar (ou
# pedir para um agente digitar) o prefixo inteiro de sudo mais variáveis de
# ambiente a cada vez, e errar uma delas dá "permission denied" ou, pior, um
# banco vazio que parece só não ter alias nenhum.
#
#     ssh leonardo_contabo 'emailing verificar_config --json'
#     ssh leonardo_contabo 'emailing enviar --alias financeiro --para c@x.com \
#         --assunto "Oi" --corpo-arquivo /tmp/corpo.html --conferir'
#
# O stdin passa por aqui, então o corpo também pode vir por cano:
#
#     cat corpo.html | ssh leonardo_contabo 'emailing enviar --alias financeiro …'
#
# Chama o Python do venv direto, sem `uv run`: o uv revalida o lockfile a cada
# invocação e exigiria HOME e cache graváveis para nada.
set -euo pipefail

ALVO="${ALVO:-/var/www/emailing}"

exec sudo -u emailing "$ALVO/.venv/bin/python" "$ALVO/manage.py" "$@"
