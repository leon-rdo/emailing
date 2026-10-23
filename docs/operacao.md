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

## Enviar da linha de comando

O `implantar.sh` instala `/usr/local/bin/emailing`, que roda `manage.py` como o
usuário do serviço. É por aqui que se envia sem abrir a tela — e é a única porta
programática que existe, de propósito
([decisoes.md](decisoes.md#cli)).

```bash
# o que existe (é assim que se descobre o slug, sem chutar)
ssh leonardo_contabo 'emailing verificar_config --json'

# o corpo vai por arquivo ou por cano — nunca por argumento
ssh leonardo_contabo 'cat > /tmp/corpo.html' <<'HTML'
<p>Bom dia,</p>
HTML

# conferir o que sairia, sem enviar
ssh leonardo_contabo 'emailing enviar --alias financeiro --para c@x.com \
    --assunto "Proposta" --corpo-arquivo /tmp/corpo.html --conferir'

# enviar
ssh leonardo_contabo 'emailing enviar --alias financeiro --para c@x.com \
    --assunto "Proposta" --corpo-arquivo /tmp/corpo.html --json'
```

O arquivo do corpo e os anexos precisam ser legíveis pelo usuário `emailing` —
`/tmp` com 644 serve. Tudo que sai por aqui aparece em `/historico/` igual ao
que sai pela tela.

## Envio programado

A fila fica em `/agendados/` (listar, editar e cancelar; os rascunhos ficam em
`/rascunhos/`). Quem despacha é o cron, de
minuto em minuto, por `/etc/cron.d/emailing-agendados`.

```bash
# o que está vencido agora, sem despachar
ssh leonardo_contabo 'emailing despachar_agendados --conferir'

# despachar à mão (o flock do cron não protege contra isto — rode uma vez só)
ssh leonardo_contabo 'emailing despachar_agendados -v 2'

# agendar pela linha de comando
ssh leonardo_contabo 'emailing enviar --alias financeiro --para c@x.com \
    --assunto "Lembrete" --corpo-arquivo /tmp/corpo.html --em "2026-09-10 09:00"'

# log do despachante
ssh leonardo_contabo 'tail -50 /var/log/emailing-agendados.log'
```

Os limites ficam no `.env` (`AGENDADOS_*`). Os dois que mais importam:

- `AGENDADOS_AVISAR_PARA` — sem isto, um agendamento que esgota as tentativas
  às 3h da manhã só existe no histórico, e ninguém lê o histórico às 3h da
  manhã. **Vale a pena preencher.**
- `AGENDADOS_TOLERANCIA_HORAS` — depois de o servidor voltar de uma queda
  longa, o que passou desta janela **não** é disparado; vira `FALHOU` com a
  explicação e a decisão de reenviar volta a ser sua.

Nenhum dos dois logs de cron é rotacionado. O despachante é silencioso quando
não há nada vencido, então o crescimento acompanha o uso real.

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
| Despachar agendados | `manage.py despachar_agendados` (cron de minuto, `/etc/cron.d/emailing-agendados`) |
| Backup do banco | `manage.py backup` (cron diário às 3h30, `/etc/cron.d/emailing-backup`) |
| Conferir um backup | `manage.py backup --conferir [arquivo]` |
| Novo dispositivo TOTP | `manage.py criar_totp <usuário> --substituir` |
| Destravar login após lockout | `manage.py axes_reset` |

## Estado e backup

`DATA_DIR` guarda o banco SQLite (contas, aliases, assinaturas, histórico, **a
fila de agendados**) e os anexos ainda não enviados — inclusive os das mensagens
agendadas, que ficam ali até a hora de sair.

> **Apagar `data/` apaga tudo isso** — inclusive mensagens que ainda **iam**
> sair, desde que existe fila de agendados.

Existe backup automático desde 2026-09-07: `manage.py backup`, diário às 03:30
(horário do servidor) por `/etc/cron.d/emailing-backup`, guardando as 14 cópias
mais recentes em `/var/backups/emailing` — **fora do `DATA_DIR`**, que é
justamente o que ele protege, e fora do `$ALVO`, que o `rsync --delete` do
deploy apaga.

```bash
# fazer uma agora (antes de qualquer coisa arriscada)
ssh leonardo_contabo 'emailing backup'

# o que existe, e há quanto tempo
ssh leonardo_contabo 'emailing backup --listar'

# a pergunta que importa: este arquivo serve para restaurar?
ssh leonardo_contabo 'emailing backup --conferir'

ssh leonardo_contabo 'tail -20 /var/log/emailing-backup.log'
```

Não precisa parar o serviço: a cópia usa a API de backup online do SQLite, que
respeita o WAL e tolera escrita concorrente. Cada cópia é verificada com
`PRAGMA integrity_check` **antes** de a rotação encostar nas antigas — uma cópia
boa nunca é apagada para dar lugar a uma ruim. Ao lado de cada arquivo fica um
`.json` com contagens, migração aplicada e a impressão digital do `SECRET_KEY`.

O `verificar_config` avisa (sem falhar) quando não há backup nenhum, quando o
mais recente passou de 48 h — ou seja, quando o cron parou — e quando o
`BACKUP_DIR` ficou dentro do `DATA_DIR`.

### Restaurar

Não há comando de restauração de propósito: escrever por cima do banco vivo é
exatamente o tipo de operação que não deve caber num comando fácil de digitar
por engano. São quatro passos:

```bash
ssh leonardo_contabo
emailing backup --conferir /var/backups/emailing/db-AAAAMMDDTHHMMSSZ.sqlite3
systemctl stop emailing
cp /var/backups/emailing/db-AAAAMMDDTHHMMSSZ.sqlite3 /var/www/emailing/data/db.sqlite3
chown emailing:www-data /var/www/emailing/data/db.sqlite3
rm -f /var/www/emailing/data/db.sqlite3-wal /var/www/emailing/data/db.sqlite3-shm
systemctl start emailing && emailing verificar_config
```

O `--conferir` antes de parar o serviço não é cerimônia: ele diz se o arquivo
abre, se passa no `integrity_check` e se as senhas lá dentro abrem com o
`SECRET_KEY` que a máquina tem agora. Descobrir qualquer um dos três com o
serviço já parado é o pior momento possível.

Apagar o `-wal` e o `-shm` é obrigatório: são o journal do banco **antigo**, e
deixá-los ao lado do banco restaurado corrompe o resultado.

### O que ainda falta: cópia fora da máquina

O backup é local. Ele protege do que é mais provável — apagar `data/`, uma
migração ruim, corrupção de arquivo — e **não protege de perder o disco ou a
VPS**. Uma cópia externa precisa de destino, credencial e cifra em repouso, e a
cifra importa mais aqui do que parece: junto com o `SECRET_KEY`, o banco entrega
as senhas SMTP em claro.

Enquanto não existe, uma cópia manual para a sua máquina:

```bash
scp leonardo_contabo:/var/backups/emailing/db-*.sqlite3 ~/backups-emailing/
```

### O `SECRET_KEY` abre as senhas

As senhas SMTP são cifradas com chave derivada do `SECRET_KEY`. **Trocá-lo
torna as senhas guardadas ilegíveis** — é preciso redigitá-las no admin. O
`verificar_config` avisa quando isso acontece.

Uma cópia do banco levada para fora da máquina **só serve acompanhada do
`SECRET_KEY`**, que mora no `.env` e não entra no backup: guardá-los no mesmo
lugar anularia a cifra das senhas. Guarde os dois, separados, e saiba de qual
par você tem — é para isso que o manifesto grava a impressão digital da chave, e
é o que `backup --conferir` compara.
