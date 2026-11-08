# CLAUDE.md

Orientação para o Claude Code trabalhar neste repositório.

## O que é

App Django de usuário único para enviar e-mail por **alias**, feito para rodar
numa VPS própria, num subdomínio como `emailing.example.com`. O provedor cobra
por caixa, não por endereço de saída: o app autentica com uma caixa real e põe o
alias no `From:`.

**Os detalhes da implantação em uso** — servidor, domínio, host ssh, o que mais
roda na máquina, o estado do DNS de cada domínio — ficam no `CLAUDE.local.md`,
fora do git. Leia-o se existir; o repositório em si é genérico de propósito.

Tudo — código, comentários, mensagens de UI, docs — em **português**.

## Documentação

| Documento | Quando ler |
|---|---|
| [docs/arquitetura.md](docs/arquitetura.md) | antes de mexer no caminho de uma mensagem |
| [docs/decisoes.md](docs/decisoes.md) | **antes de "consertar" qualquer coisa que pareça errada** |
| [docs/operacao.md](docs/operacao.md) | implantar, diagnosticar, backup |
| [docs/entregabilidade.md](docs/entregabilidade.md) | DNS, encoding, CSS em cliente de e-mail |
| [README.md](README.md) | rodar local, configurar, usar |

`docs/decisoes.md` é o mais importante dos quatro: lista o que **parece errado
até saber por quê**, e várias dessas coisas já foram "consertadas" de volta ao
estado ruim uma vez.

## Stack

Django 5.2 renderizado no servidor, **sem DRF**. SQLite em WAL. uv +
`pyproject.toml`. ruff. gunicorn + whitenoise atrás do nginx. Sem npm, sem
bundler, sem framework de CSS: um `estilo.css` à mão e JS inline com nonce de
CSP. Trix vendorizado como único JS de terceiros.

```bash
uv sync
uv run manage.py <cmd>
uv run ruff check .
uv run pytest
```

## Mapa do código

- `config/` — `settings.py` (arquivo único, tudo do ambiente), `urls.py`,
  `middleware.py` (nonce de CSP, cabeçalhos, exigência de OTP), `hashers.py`.
- `mensagens/` — o app único:
  - `models.py` — `ContaEmail`, `Alias`, `RegistroEnvio`, `EnvioAgendado` (a fila
    **e** os rascunhos: é o status que separa)
  - `cripto.py` — cifra a senha SMTP
  - `redacao.py` — valida e descreve a redação que não veio da tela (CLI e MCP)
  - `caixa.py` — IMAP sob demanda (buscar, ler, marcar, mover); só o MCP usa
  - `aliases.py` — consulta ao banco + `verificar_aliases()`
  - `backup.py` — cópia verificada do banco, rotação e manifesto
  - `agendamento.py` — fila do envio programado: criar, editar, cancelar,
    reivindicar, despachar; e os rascunhos salvos
  - `saneamento.py` — embutir CSS, limpar HTML, HTML→texto
  - `montagem.py` — monta a mensagem (função pura)
  - `marcadores.py` — `{{ … }}` e o glossário
  - `envio.py` — conexão SMTP e o `RegistroEnvio`
  - `anexos.py` — rascunhos em disco
  - `eml.py` — importar `.eml` e reconstruir `References`
  - `views.py` — redigir/editar/prévia/envio/agendar/rascunho, importar,
    histórico, fila, detalhe de agendado
  - `views_configuracoes.py` — contas SMTP, aliases e o editor de assinatura
    (telas próprias; nada apaga, ver [decisoes.md](docs/decisoes.md#configuracoes))
  - `contexto.py` + `templatetags/mensagens_ui.py` — caixas e contadores do menu
    lateral (`?caixa=<id>`) e filtros só de apresentação (cor, trecho, data curta)
  - `static/mensagens/` — `estilo.css` (tokens no topo), `compor.js` (modal de escrita e
    prévia ao vivo), `app.js`, `editor.js` (Trix), `fontes/` (woff2 próprios)
  - `mcp_servidor.py` — as tools MCP, finas sobre `redacao`/`envio`/`agendamento`/`caixa`
  - `management/commands/mcp.py` — o servidor MCP por stdio (o que a chave ssh restrita abre)
  - `management/commands/enviar.py` — a porta do operador e de agentes (ssh)
  - `management/commands/despachar_agendados.py` — o que o cron chama

## Convenções que não devem ser "corrigidas"

O racional completo está em [docs/decisoes.md](docs/decisoes.md). Em resumo:

- **Nomes de domínio em português, identificadores de protocolo em inglês.**
  `criado_em`, `remetente`, `assunto` — mas `message_id` e `in_reply_to`,
  porque são nomes de cabeçalho da RFC 5322.
- **A assinatura não passa pelo sanitizador.** É conteúdo do operador.
- **O CSS é embutido antes de sanitizar**, e por isso `class`/`<style>`
  sobrevivem.
- **A prévia não exige destinatário nem valida endereço.** Já quebrou duas
  vezes por isso. (O *botão* Enviar é que espera um destinatário — ver
  [decisoes.md](docs/decisoes.md#destino-no-botao).)
- **O `hash_previa` é do conteúdo autoral**, com os marcadores intactos.
- **A lista de marcadores é fechada.**
- **A prévia não persiste rascunho** — recalcula sobre o mesmo POST. Isso é
  sobre a *prévia*; o rascunho **salvo** pelo operador existe (status
  `rascunho` de `EnvioAgendado`) e a prévia dele também é recalculada. "Rascunho"
  no código é também a pasta de **anexos** — ver
  [decisoes.md](docs/decisoes.md#rascunho).
- **Editar um agendado é `UPDATE … WHERE status`, sobre uma cópia dos anexos.**
  Nunca `if` + `save()`, nunca editar a pasta viva — o cron concorre pela linha.
  Ver [decisoes.md](docs/decisoes.md#edicao).
- **`SMTP_TIMEOUT` não é opcional.**
- **Corpo em quoted-printable**, não no `8bit` do Django.
- **A importação de `.eml` nunca toca o disco.**
- **Duplo envio não tem trava no servidor**, de propósito — **menos no
  despacho de agendados**, que é o único lugar com trava de concorrência de
  verdade, porque lá não há humano nem POST-redirect-GET.
- **Não existe API HTTP de envio**, e não é lacuna: quem envia por fora da tela
  usa `manage.py enviar` ou o MCP (`manage.py mcp`), os dois por ssh. Um
  endpoint autenticado por token capaz de enviar como estes domínios seria um
  relay aberto com DMARC alinhado se o token vazasse. **O MCP é stdio sobre ssh,
  com chave restrita; nunca transforme em MCP por HTTP.**
- **Tools de escrita do MCP nunca entram na allowlist**, e o teto
  `MCP_MAX_ENVIOS_POR_SESSAO` existe. O MCP lê a caixa: um e-mail recebido pode
  "pedir" para encaminhar algo, e a aprovação humana é a trava. Ver
  [decisoes.md](docs/decisoes.md#mcp-injecao).
- **Ler pelo IMAP não marca como lida** (`EXAMINE` + `BODY.PEEK[]`), e **mover
  nunca faz `EXPUNGE` geral**. A caixa não é copiada para o banco.
- **A linha de comando (e o MCP) não têm trava de `hash_previa`** — lá não existe o
  intervalo humano que a trava protege. Quem quer conferir usa `--conferir`.
- **Agendamento guarda o corpo cru do editor**, não o HTML pronto: sanitizar e
  expandir marcador acontecem no despacho, pelo mesmo caminho da tela.

## Ao investigar um bug

Os defeitos que os testes não pegaram foram todos encontrados **no artefato
real**, não no código:

- `.eml` recebido → encoding, DKIM/DMARC, o que o destinatário viu de fato
- `/var/log/nginx/emailing_access.log` → o status e **o tamanho** das respostas
  (200 com 113 bytes é JSON de erro)
- navegador de verdade → digitação tecla a tecla passa por estados que
  `fill()` pula

## Estado

`DATA_DIR` guarda o banco SQLite (contas, aliases, assinaturas, histórico, **a
fila de agendados e os rascunhos**) e os anexos pendentes — inclusive os das
mensagens agendadas e dos rascunhos, que precisam sobreviver ao TTL (o rascunho
salvo tem prazo próprio: `RASCUNHO_SALVO_EXPIRA_DIAS`, 30 dias sem alteração). **Apagar `data/` apaga
tudo isso.**

Há backup diário (`manage.py backup`, cron instalado pelo `implantar.sh`, 14
cópias em `/var/backups/emailing`), verificado antes de rotacionar. **Continua sem cópia
fora da máquina** — é a pendência que sobrou (ver
[docs/operacao.md](docs/operacao.md#estado-e-backup)).

O `SECRET_KEY` abre as senhas SMTP cifradas: perdê-lo exige redigitar todas.

## Onde roda

Uma VPS Linux com nginx no host + certbot, este app sob systemd em
`127.0.0.1:8010`, com usuário de sistema próprio. Sem Docker. Os documentos usam
`ssh meu-servidor` e `emailing.example.com` como exemplo; os valores reais da
implantação estão no `CLAUDE.local.md`. **Nunca escreva IP, host ssh ou domínio
de uma implantação real em arquivo versionado** — o repositório é público.
