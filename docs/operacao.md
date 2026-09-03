# Operação

Runbook: implantar, diagnosticar, e as tarefas que aparecem de vez em quando.

## Onde roda

| | |
|---|---|
| Servidor | Contabo `203.0.113.10`, `ssh leonardo_contabo` (usuário root) |
| Código | `/var/www/emailing` |
| Estado | `/var/www/emailing/data` (banco, anexos pendentes) |
| Serviço | `systemd`, unit `emailing`, gunicorn em `127.0.0.1:8010` |
| Usuário | `emailing` (de sistema, sem shell) — **não** roda como root |
| Proxy | nginx no host, vhost `emailing.leonardocosta.dev`, TLS pelo certbot |
| Toolchain | uv em `/usr/local/bin/uv`, Python gerenciado em `/opt/uv-python` |

Na mesma máquina: Pholium (`api.leonardocosta.dev`, porta 8000) e o site Nuxt
(`leonardocosta.dev`, porta 3000). **Não há Docker.**

## Implantar

```bash
# do repositório local
rsync -az --delete \
  --exclude '.venv' --exclude 'data' --exclude 'staticfiles' \
  --exclude '.git' --exclude '__pycache__' --exclude '.env' \
  --exclude '.pytest_cache' \
  ./ leonardo_contabo:/var/www/emailing/

ssh leonardo_contabo 'sudo bash /var/www/emailing/deploy/implantar.sh'
```

O `implantar.sh` faz dependências → migrações → estático → `verificar_config`
→ permissões → cron → restart → smoke test, e **falha se o serviço não subir**
ou se a configuração estiver quebrada (ele para antes de reiniciar).

> **Nunca recarregue o nginx sem `nginx -t` antes.** Um erro de sintaxe derruba
> `api.leonardocosta.dev` e `leonardocosta.dev` junto.

### Se precisar mexer no nginx

O vhost modelo está em `deploy/nginx-emailing.conf`. Depois do certbot o
arquivo em produção fica diferente (o certbot reescreve com o bloco 443).
`client_max_body_size 25m` precisa acomodar o teto de anexos, senão o 413
acontece no nginx e o usuário vê erro de proxy em vez da validação do
formulário.

## Primeiro acesso num servidor novo

```bash
cd /var/www/emailing
uv run --no-dev manage.py createsuperuser
uv run --no-dev manage.py criar_totp <usuário>   # mostra o QR no terminal
chown -R emailing:www-data data                  # o banco mudou de dono
```

Sem TOTP não há como entrar em produção (`OTP_OBRIGATORIO="1"`).

## Cadastrar conta e alias

Pelo admin, em `/admin/`:

1. **Contas de e-mail** → servidor, porta, a caixa que autentica, senha, e
   STARTTLS (587) **ou** SSL direto (465).
2. **Aliases** → endereço, nome de exibição, conta, e a assinatura HTML.

O alias só aceita domínio autorizado pela conta (campo *domínios permitidos*;
vazio = o domínio da própria conta). Não é burocracia: `From:` fora do domínio
autenticado quebra o DMARC e a mensagem cai em spam.

## Diagnóstico

```bash
# o que está cadastrado e o que está quebrado
uv run --no-dev manage.py verificar_config

# envio real por um alias, ponta a ponta
uv run --no-dev manage.py testar_smtp <alias> --para voce@exemplo.com

# logs
journalctl -u emailing -n 100 --no-pager
tail -50 /var/log/nginx/emailing_error.log
tail -50 /var/log/nginx/emailing_access.log
```

O `access.log` do nginx já resolveu um bug que o teste automatizado não pegou:
requisições a `/previa-ajax/` respondiam 200 com 113 bytes — tamanho de JSON de
erro — revelando que a prévia congelava em silêncio. **Quando o sintoma é "não
atualiza", olhe o tamanho das respostas no access log.**

Rodar comandos como o usuário do serviço (o `uv` precisa de cache gravável):

```bash
cd /var/www/emailing && sudo -u emailing env \
  UV_PYTHON_INSTALL_DIR=/opt/uv-python \
  UV_CACHE_DIR=/var/www/emailing/data/.uv-cache \
  HOME=/var/www/emailing \
  /usr/local/bin/uv run --no-dev manage.py <comando>
```

## Manutenção

| Tarefa | Comando |
|---|---|
| Limpar rascunhos abandonados | `manage.py limpar_rascunhos` (cron diário às 4h, `/etc/cron.d/emailing-limpeza`) |
| Novo dispositivo TOTP | `manage.py criar_totp <usuário> --substituir` |
| Destravar login após lockout | `manage.py axes_reset` |

## Estado e backup

`DATA_DIR` guarda o banco SQLite (contas, aliases, assinaturas, histórico) e os
anexos ainda não enviados.

> **Apagar `data/` apaga tudo isso.** Não há outra cópia.

**Não existe backup automático — é a maior pendência conhecida do projeto.** Um
`cp` do SQLite em WAL não é seguro; o certo é `sqlite3.Connection.backup()`,
que respeita o journal. Enquanto não existe, um backup manual antes de
qualquer coisa arriscada:

```bash
ssh leonardo_contabo "cd /var/www/emailing && sudo -u emailing \
  python3 -c \"import sqlite3; o=sqlite3.connect('data/db.sqlite3'); \
  d=sqlite3.connect('data/backup.sqlite3'); o.backup(d); d.close(); o.close()\""
```

### O `SECRET_KEY` abre as senhas

As senhas SMTP são cifradas com chave derivada do `SECRET_KEY`. **Trocá-lo
torna as senhas guardadas ilegíveis** — é preciso redigitá-las no admin. O
`verificar_config` avisa quando isso acontece. Guarde o `SECRET_KEY` junto com
o backup do banco, ou o backup não serve para nada.
