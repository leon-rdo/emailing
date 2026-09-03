#!/usr/bin/env bash
# Atualiza a implantação. Rodar como root no servidor, DEPOIS de o código novo
# já estar em /var/www/emailing (git pull, rsync ou o que for).
#
#     ssh leonardo_contabo 'bash /var/www/emailing/deploy/implantar.sh'
#
set -euo pipefail

ALVO="${ALVO:-/var/www/emailing}"
UV="${UV:-/usr/local/bin/uv}"
SERVICO="${SERVICO:-emailing}"
PORTA="${PORTA:-8010}"

cd "$ALVO"

echo "== dependências =="
"$UV" sync --frozen --no-dev

echo "== migrações =="
"$UV" run --no-dev manage.py migrate --noinput

echo "== estático =="
"$UV" run --no-dev manage.py collectstatic --noinput

echo "== configuração =="
"$UV" run --no-dev manage.py verificar_config

# migrate e collectstatic rodam como root; o serviço roda como `emailing` e
# precisa escrever no banco e nos anexos.
chown -R emailing:www-data "$ALVO/data" "$ALVO/staticfiles"
chmod 600 "$ALVO/.env"
chown emailing:www-data "$ALVO/.env"

echo "== reiniciando =="
systemctl restart "$SERVICO"
sleep 2
systemctl is-active --quiet "$SERVICO" || {
    echo "serviço não subiu:" >&2
    journalctl -u "$SERVICO" -n 30 --no-pager >&2
    exit 1
}

curl -fsS -o /dev/null -w 'login local: HTTP %{http_code}\n' \
    "http://127.0.0.1:${PORTA}/entrar/"
echo "ok"
