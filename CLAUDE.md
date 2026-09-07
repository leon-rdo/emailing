# CLAUDE.md

Orientação para o Claude Code trabalhar neste repositório.

## O que é

App Django de usuário único para enviar e-mail por **alias**, hospedado em
`emailing.leonardocosta.dev`. O provedor cobra por caixa, não por endereço de
saída: o app autentica com uma caixa real e põe o alias no `From:`.

**Não tem relação nenhuma com o Pholium** — só compartilha a VPS.

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
  - `models.py` — `ContaEmail`, `Alias`, `RegistroEnvio`
  - `cripto.py` — cifra a senha SMTP
  - `aliases.py` — consulta ao banco + `verificar_aliases()`
  - `agendamento.py` — fila do envio programado: criar, reivindicar, despachar
  - `saneamento.py` — embutir CSS, limpar HTML, HTML→texto
  - `montagem.py` — monta a mensagem (função pura)
  - `marcadores.py` — `{{ … }}` e o glossário
  - `envio.py` — conexão SMTP e o `RegistroEnvio`
  - `anexos.py` — rascunhos em disco
  - `eml.py` — importar `.eml` e reconstruir `References`
  - `views.py` — redigir/prévia/envio/agendar, importar, histórico, fila
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
  vezes por isso.
- **O `hash_previa` é do conteúdo autoral**, com os marcadores intactos.
- **A lista de marcadores é fechada.**
- **A prévia não persiste rascunho** — recalcula sobre o mesmo POST.
- **`SMTP_TIMEOUT` não é opcional.**
- **Corpo em quoted-printable**, não no `8bit` do Django.
- **A importação de `.eml` nunca toca o disco.**
- **Duplo envio não tem trava no servidor**, de propósito — **menos no
  despacho de agendados**, que é o único lugar com trava de concorrência de
  verdade, porque lá não há humano nem POST-redirect-GET.
- **Não existe API HTTP de envio**, e não é lacuna: quem envia por fora da tela
  usa `manage.py enviar` por ssh. Um endpoint autenticado por token capaz de
  enviar como estes domínios seria um relay aberto com DMARC alinhado se o
  token vazasse.
- **A linha de comando não tem trava de `hash_previa`** — lá não existe o
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
fila de agendados**) e os anexos pendentes — inclusive os das mensagens
agendadas, que precisam sobreviver ao TTL do rascunho. **Apagar `data/` apaga
tudo isso** — e **não há backup automático**, a maior pendência conhecida do
projeto, agravada desde que existe fila (ver
[docs/operacao.md](docs/operacao.md#estado-e-backup)).

O `SECRET_KEY` abre as senhas SMTP cifradas: perdê-lo exige redigitar todas.

## Onde roda

VPS Contabo `203.0.113.10` (`ssh leonardo_contabo`), a mesma do Pholium
(`api.leonardocosta.dev`, porta 8000) e do site Nuxt (porta 3000). nginx no
host + certbot, este app sob systemd em `127.0.0.1:8010`, com usuário de
sistema próprio. **Não há Docker nessa máquina.**
