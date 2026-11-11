# Emailing

Aplicação web de usuário único para redigir e enviar e-mail por **alias** dos
seus domínios. Vários provedores (Titan, Hostinger, GoDaddy…) cobram por caixa
ou à parte pelo envio por alias, mas o SMTP deles aceita `From:` de qualquer
endereço do mesmo domínio quando autenticado com uma caixa real — este app
transforma isso numa ferramenta com editor, assinatura, pré-visualização,
anexos, agendamento, resposta a threads existentes e um servidor MCP para o
Claude Code enviar e ler e-mail.

Feito para rodar numa VPS própria, atrás do nginx, num subdomínio como
`https://emailing.example.com`.

Uma conta serve vários aliases, e contas diferentes podem estar em provedores
diferentes — Titan e Hostinger convivem, cada uma com os seus.

## Documentação

- [docs/arquitetura.md](docs/arquitetura.md) — o caminho de uma mensagem, do
  editor ao SMTP
- [docs/decisoes.md](docs/decisoes.md) — o que parece errado até saber por quê,
  e os bugs que já aconteceram
- [docs/operacao.md](docs/operacao.md) — implantar, diagnosticar, backup
- [docs/entregabilidade.md](docs/entregabilidade.md) — DNS, encoding, CSS em
  cliente de e-mail

## Desenvolvimento

```bash
uv sync
cp .env.example .env      # SECRET_KEY, ALLOWED_HOSTS — nada de e-mail aqui
uv run manage.py migrate
uv run manage.py createsuperuser
uv run manage.py runserver
```

Contas e aliases são cadastrados no admin (`/admin/`), não no `.env`. Depois,
`uv run manage.py verificar_config` mostra o que está cadastrado e o que está
quebrado.

Em desenvolvimento deixe `DEBUG="1"` e `OTP_OBRIGATORIO="0"` — assim o login
não exige segundo fator num banco recém-criado.

Qualidade:

```bash
uv run ruff check .
uv run pytest
```

Os testes usam `config/settings_teste.py`, que **não lê o `.env`**: rodam sobre
os padrões do código, com `DEBUG` e `OTP_OBRIGATORIO` fixados. Passam num
checkout limpo, sem configurar nada.

## Configuração

**Contas e aliases ficam no admin**, em `/admin/`. O `.env` guarda só o que é
de infraestrutura (`SECRET_KEY`, `ALLOWED_HOSTS`, limites) — nada de e-mail.

### Cadastrar uma conta e um alias

1. **Contas de e-mail** → adicionar: servidor, porta, a caixa que autentica, a
   senha, e STARTTLS (587) ou SSL direto (465). Uma conta por provedor.
2. **Aliases** → adicionar: o endereço pelo qual você quer enviar, o nome de
   exibição, e a conta que autentica. A assinatura HTML do alias vai no mesmo
   formulário.

Um alias só pode usar um domínio autorizado pela conta (campo *domínios
permitidos*; vazio = o domínio da própria conta). Essa trava não é burocracia:
um `From:` fora do domínio autenticado quebra o alinhamento do DMARC e a
mensagem cai em spam.

Uma conta serve vários aliases — é o motivo do projeto existir. E contas
diferentes podem estar em provedores diferentes: dá para ter Titan e Hostinger
lado a lado, cada um com seus aliases.

> **A senha SMTP é guardada cifrada com uma chave derivada do `SECRET_KEY`.**
> Trocar o `SECRET_KEY` torna as senhas guardadas ilegíveis — é preciso
> redigitá-las no admin. O `manage.py verificar_config` avisa quando isso
> acontece.

### Vindo da versão que usava `.env`

```bash
uv run manage.py importar_aliases_do_env
```

Lê `ALIASES`/`ALIAS_*`/`SMTP_*` e os arquivos de assinatura, cria a conta e os
aliases no banco. É idempotente. Depois disso essas variáveis podem sair do
`.env` (o `SECRET_KEY` não: é ele que abre as senhas).

### Segundo fator

```bash
uv run manage.py criar_totp <usuário>
```

Mostra o QR no terminal. Com `OTP_OBRIGATORIO="1"`, uma sessão autenticada sem
segundo fator verificado é encerrada — não existe estado intermediário.

## Implantação

Uma VPS Linux (o servidor de referência é Ubuntu 24.04) com nginx no host, TLS
pelo certbot e o processo sob systemd. Não precisa de Docker. Os exemplos usam
`ssh meu-servidor` — um `Host` do seu `~/.ssh/config` — e `emailing.example.com`;
troque pelos seus.

- Código em `/var/www/emailing`, `.env` na raiz com modo `0600`.
- `uv sync --frozen --no-dev && manage.py migrate && manage.py collectstatic`.
- Unit systemd com `EnvironmentFile=/var/www/emailing/.env`, usuário de sistema
  próprio (não `root`: este processo guarda credencial de SMTP) e
  `gunicorn config.wsgi -b 127.0.0.1:8010`.
- vhost nginx com `proxy_pass http://127.0.0.1:8010`, os `X-Forwarded-*` e
  `client_max_body_size 25m` (senão o anexo grande morre com 413 antes de
  chegar ao Django). O estático é servido pelo whitenoise — não crie um
  `location /static/`.
- Um registro DNS do subdomínio apontando para o servidor, e
  `certbot --nginx -d emailing.example.com`. O modelo do vhost está em
  `deploy/nginx-emailing.conf`.
- **Sempre `nginx -t` antes do reload**: um erro de sintaxe derruba todos os
  outros sites do mesmo nginx.

Atualizações depois da primeira vez: sincronize o código e rode
`bash /var/www/emailing/deploy/implantar.sh` como root — ele cuida de
dependências, migrações, estático, permissões e restart, e falha se o serviço
não subir.

### Primeiro acesso

Sem um usuário e um dispositivo TOTP não há como entrar (em produção
`OTP_OBRIGATORIO="1"`):

```bash
ssh meu-servidor
cd /var/www/emailing
uv run --no-dev manage.py createsuperuser
uv run --no-dev manage.py criar_totp <usuário>   # escaneie o QR
chown -R emailing:www-data data                  # o banco acabou de mudar de dono
```

## Uso

Redigir (`/`) tem três entradas independentes para uma resposta: importar um
`.eml`/`.txt` (extrai destinatário, assunto e cita o corpo original,
processado só em memória — nunca toca o disco), digitar um `Message-ID` à mão
quando não há o arquivo, ou clicar em "responder" numa linha do histórico
(`/historico/`) de algo que o próprio app já enviou.

O botão Enviar só existe depois de uma prévia, e só envia se nada mudou desde
então (corpo, anexos, destinatário ou assunto) — editar algo depois de
pré-visualizar volta para uma prévia atualizada em vez de mandar sem conferir.

### Agendar

A caixa *Agendar em vez de enviar agora*, na tela de redação, pede data e hora e
põe a mensagem numa fila em `/agendados/`, de onde dá para cancelar até o
momento de sair. Vale a mesma trava do envio: só vai para a fila o que foi
pré-visualizado.

Quem despacha é um cron de minuto em minuto — não há fila nem broker. A
mensagem é guardada **como você escreveu**: sanitização e marcadores acontecem
na hora da entrega, então `{{ hora }}` num agendamento significa a hora em que
a mensagem sai, que é o que se espera.

### Editar um agendado, rascunhos e detalhes

- **Editar.** Em `/agendados/`, *editar* abre a mesma tela de redação sobre a
  mensagem. *Salvar alterações* exige uma prévia, como agendar (ela já vem
  calculada ao abrir). Se o cron despachar a mensagem enquanto a tela está
  aberta, o salvamento é recusado com um aviso — nada é sobrescrito.
- **Tirar da fila.** *Tirar da fila (rascunho)* devolve o agendado a rascunho
  sem cancelar, para retomar depois.
- **Rascunhos.** *Salvar rascunho* guarda a mensagem como está — sem prévia, sem
  destinatário, sem data. Ficam em `/rascunhos/`, nunca saem sozinhos, e dali se
  abre para enviar ou agendar. Os anexos ficam guardados junto. Rascunho sem
  alteração há `RASCUNHO_SALVO_EXPIRA_DIAS` (padrão 30; `0` = nunca) é apagado
  pela limpeza diária; salvar de novo adia o prazo.
- **Detalhes.** `/agendados/<id>/` mostra tudo sobre uma mensagem guardada em
  qualquer estado, inclusive cancelada: destinatários, cabeçalhos de resposta,
  tentativas, erro, o corpo e a lista de anexos (os arquivos são apagados ao
  cancelar, mas a lista permanece).

Se um envio agendado falhar, ele volta para a fila com espera crescente (5, 10,
20 min). Esgotadas as tentativas, vira `Falhou` com o erro à vista — e manda um
aviso para `AGENDADOS_AVISAR_PARA`, se você tiver preenchido. Vale preencher:
ninguém lê o histórico às 3h da manhã.

### Da linha de comando (e para agentes)

Não existe API HTTP de envio, de propósito. Quem envia de fora da tela usa
`manage.py enviar`, autenticado pela chave ssh:

```bash
# descobrir os aliases, em JSON
uv run manage.py verificar_config --json

# conferir o que sairia, sem enviar nada
uv run manage.py enviar --alias financeiro --para cliente@exemplo.com     --assunto "Proposta" --corpo-arquivo corpo.html --conferir

# enviar (ou --em "2026-09-10 09:00" para agendar)
uv run manage.py enviar --alias financeiro --para cliente@exemplo.com     --assunto "Proposta" --corpo-arquivo corpo.html --anexo proposta.pdf --json
```

O corpo vem de arquivo ou do stdin, nunca por argumento: `argv` aparece no `ps`
e no histórico do shell. A validação é a mesma da tela — endereço, alias,
limites de anexo e de destinatários —, e tudo entra no mesmo `/historico/`.

Em produção há o atalho `emailing`, instalado pelo `implantar.sh`:

```bash
ssh meu-servidor 'emailing verificar_config --json'
```

O repositório traz `.claude/skills/enviar-email/`, que ensina essa sequência ao
Claude Code — foi para isso que o comando ganhou `--conferir` e `--json`.

### Pelo Claude Code (MCP)

`manage.py mcp` é um servidor MCP por stdio que o Claude Code abre por ssh, com
uma chave que só executa esse comando. Ele envia, agenda, guarda rascunho,
**edita agendados e rascunhos** e **lê a caixa de entrada** por IMAP: busca, lê
(sem marcar como lida), responde com o encadeamento certo (`responder_a`), marca
e move. Toda redação aceita `assinatura=false`, para quando o corpo já é um HTML
pronto com a sua — a mesma opção que a tela tem na caixa "Sem assinatura".

```bash
claude mcp add --scope user emailing -- ssh -T emailing-mcp
```

A configuração completa (chave restrita, `~/.ssh/config`, allowlist só das
tools de leitura, servidor IMAP de cada caixa) está em
[docs/operacao.md](docs/operacao.md#mcp-o-claude-code-enviando-e-lendo-e-mail).
As tools de envio pedem aprovação a cada chamada, de propósito.

### Marcadores

Escreva `{{ data }}` no corpo e ele vira a data no momento do envio. A lista
completa fica num painel na própria tela de redação (*Marcadores
disponíveis*), com descrição e exemplo de cada um: `data`, `data_extenso`,
`hora`, `data_hora`, `ano`, `remetente`, `remetente_nome`, `remetente_email`,
`destinatario` e `assunto`.

A lista é **fechada de propósito**. Qualquer outro nome fica literal no
e-mail, e sintaxe de outros motores (`<%= ... %>` do EJS, `{% ... %}` do
Django) também — o app nunca avalia o que está escrito no corpo, só troca
nomes que ele mesmo conhece por valores que ele mesmo produz.

Marcadores são expandidos **no envio**, não na hora em que você escreve: a
prévia mostra o valor já resolvido, mas o que trava o envio (`hash_previa`) é
o texto com os marcadores intactos. Sem isso, `{{ hora }}` mudaria sozinho
entre a prévia e o clique em Enviar e o envio seria recusado.

Diagnóstico e testes manuais:

```bash
uv run manage.py testar_smtp financeiro --para voce@example.com
uv run manage.py limpar_rascunhos            # apaga anexos de rascunhos abandonados
uv run manage.py despachar_agendados --conferir   # o que a fila mandaria agora
```

Em produção os dois cron ficam instalados pelo `implantar.sh`: `limpar_rascunhos`
diário às 4h e `despachar_agendados` de minuto em minuto. Ver
[docs/operacao.md](docs/operacao.md).

## Entregabilidade: o que precisa estar no DNS

O app envia com `From:` diferente da conta que autentica. Para isso não cair em
spam, o **domínio do `From:` precisa estar alinhado** com o que o DMARC vê:

- **SPF** — inclua o provedor no registro do domínio. O envelope sai no próprio
  alias, então o SPF do domínio dele é o que vale.
- **DKIM** — ative no painel do provedor. É a única das duas assinaturas que
  **sobrevive a encaminhamento**: sem DKIM, um e-mail encaminhado quebra o SPF
  e o DMARC falha junto.
- **DMARC** — `p=none` para observar, `p=quarantine`/`p=reject` depois de
  confirmar que SPF e DKIM passam.

Enquanto SPF e DKIM alinharem, aliases do mesmo domínio funcionam sem
configuração adicional — não existe SPF ou DKIM "por caixa", só por domínio.

## Estado

`DATA_DIR` (`data/` em dev, `/var/www/emailing/data` em produção) guarda o
banco SQLite e os anexos ainda não enviados — inclusive os das mensagens
agendadas. Apagar esse diretório apaga o histórico, as contas, os aliases e a
fila de envios que ainda não saíram.

Em produção há backup diário: `manage.py backup` copia o banco com a API de
backup online do SQLite (um `cp` num banco em WAL não é seguro), verifica a
cópia com `PRAGMA integrity_check` antes de rotacionar as antigas, e guarda as
14 mais recentes em `/var/backups/emailing` — fora do `DATA_DIR`, que é o que
ele protege.

```bash
uv run manage.py backup             # faz uma agora
uv run manage.py backup --listar
uv run manage.py backup --conferir  # este arquivo serve para restaurar?
```

`--conferir` responde três perguntas: o arquivo abre, passa no
`integrity_check`, e as senhas SMTP lá dentro abrem com o `SECRET_KEY` **que a
máquina tem agora** — essa última é a que costuma ser esquecida, porque as
senhas são cifradas com chave derivada dele. O procedimento de restauração está
em [docs/operacao.md](docs/operacao.md).

O backup é local: protege de apagar `data/`, de uma migração ruim e de
corrupção, e não protege de perder o disco. Cópia externa continua sendo manual.
