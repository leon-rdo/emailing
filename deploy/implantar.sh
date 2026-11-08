#!/usr/bin/env bash
# Atualiza a implantação. Rodar como root no servidor, DEPOIS de o código novo
# já estar em /var/www/emailing (git pull, rsync ou o que for).
#
#     ssh meu-servidor 'bash /var/www/emailing/deploy/implantar.sh'
#
set -euo pipefail

ALVO="${ALVO:-/var/www/emailing}"
UV="${UV:-/usr/local/bin/uv}"
SERVICO="${SERVICO:-emailing}"
PORTA="${PORTA:-8010}"
# O domínio do smoke test sai do primeiro host do ALLOWED_HOSTS do .env, que é
# o mesmo valor que o Django exige no cabeçalho Host.
DOMINIO="${DOMINIO:-$(grep -E '^ALLOWED_HOSTS=' "$ALVO/.env" 2>/dev/null | head -1 \
    | cut -d= -f2- | tr -d "\"'" | cut -d, -f1 || true)}"
if [ -z "$DOMINIO" ]; then
    echo "defina ALLOWED_HOSTS no $ALVO/.env (ou DOMINIO=… no ambiente)" >&2
    exit 1
fi

# O interpretador que o uv gerencia precisa ficar fora de /root: o serviço roda
# como `emailing`, e mesmo com permissão de leitura o ProtectHome=true do unit
# tornaria /root inacessível. Sem isto o .venv vira um symlink quebrado para o
# processo e o systemd falha com 203/EXEC.
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/opt/uv-python}"

cd "$ALVO"

echo "== dependências =="
# --compile-bytecode: o .venv é de root e só leitura para o `emailing`, então o
# Python do serviço não consegue gravar os .pyc e recompila tudo a cada processo.
# Para o gunicorn é uma vez por boot; para o `manage.py mcp`, que abre um processo
# por sessão do Claude Code, eram ~5 s só para importar o `mcp` (medido).
"$UV" sync --frozen --no-dev --compile-bytecode

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

# O backup mora FORA do $ALVO: o rsync do deploy usa --delete, e fora do
# DATA_DIR, porque é o DATA_DIR que ele existe para proteger. O `.env` aponta
# BACKUP_DIR para cá; se esquecerem, o `verificar_config` avisa.
echo "== diretório de backup =="
install -d -m 750 -o emailing -g www-data /var/backups/emailing

echo "== cron (limpeza + agendados + backup) =="
install -m 644 "$ALVO/deploy/emailing-limpeza.cron" /etc/cron.d/emailing-limpeza
install -m 644 "$ALVO/deploy/emailing-agendados.cron" /etc/cron.d/emailing-agendados
install -m 644 "$ALVO/deploy/emailing-backup.cron" /etc/cron.d/emailing-backup
touch /var/log/emailing-limpeza.log /var/log/emailing-agendados.log \
      /var/log/emailing-backup.log
chown emailing:www-data /var/log/emailing-limpeza.log /var/log/emailing-agendados.log \
      /var/log/emailing-backup.log
systemctl reload cron 2>/dev/null || systemctl restart cron

# Atalho para rodar manage.py como o usuário do serviço — é por aqui que o
# `enviar` é chamado por ssh. Ver deploy/emailing-cli.sh.
echo "== atalho /usr/local/bin/emailing =="
install -m 755 "$ALVO/deploy/emailing-cli.sh" /usr/local/bin/emailing

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
