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
DOMINIO="${DOMINIO:-emailing.leonardocosta.dev}"

# O interpretador que o uv gerencia precisa ficar fora de /root: o serviço roda
# como `emailing`, e mesmo com permissão de leitura o ProtectHome=true do unit
# tornaria /root inacessível. Sem isto o .venv vira um symlink quebrado para o
# processo e o systemd falha com 203/EXEC.
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/opt/uv-python}"

cd "$ALVO"

echo "== dependências =="
"$UV" sync --frozen --no-dev

echo "== migrações =="
"$UV" run --no-dev manage.py migrate --noinput

echo "== estático =="
"$UV" run --no-dev manage.py collectstatic --noinput

echo "== configuração =="
"$UV" run --no-dev manage.py verificar_config

# O código é de root e só de leitura para o serviço; o estado é do serviço.
chown -R root:www-data "$ALVO/config" "$ALVO/mensagens" "$ALVO/deploy" "$ALVO/manage.py"
chown -R emailing:www-data "$ALVO/data" "$ALVO/staticfiles"
chown emailing:www-data "$ALVO/.env"
chmod 600 "$ALVO/.env"
chmod -R a+rX "$UV_PYTHON_INSTALL_DIR" "$ALVO/.venv"

mkdir -p "$ALVO/data/.uv-cache"
chown emailing:www-data "$ALVO/data/.uv-cache"

echo "== cron de limpeza de rascunhos =="
install -m 644 "$ALVO/deploy/emailing-limpeza.cron" /etc/cron.d/emailing-limpeza
touch /var/log/emailing-limpeza.log
chown emailing:www-data /var/log/emailing-limpeza.log
systemctl reload cron 2>/dev/null || systemctl restart cron

echo "== reiniciando =="
systemctl restart "$SERVICO"
sleep 2
systemctl is-active --quiet "$SERVICO" || {
    echo "serviço não subiu:" >&2
    journalctl -u "$SERVICO" -n 30 --no-pager >&2
    exit 1
}

# O Host precisa bater com ALLOWED_HOSTS (senão 400) e o X-Forwarded-Proto
# precisa dizer https (senão o SECURE_SSL_REDIRECT responde 301) — exatamente o
# que o nginx envia.
curl -fsS -o /dev/null -w 'login local: HTTP %{http_code}\n' \
    -H "Host: ${DOMINIO}" -H 'X-Forwarded-Proto: https' \
    "http://127.0.0.1:${PORTA}/entrar/"
echo "ok"
