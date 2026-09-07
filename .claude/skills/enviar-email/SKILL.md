---
name: enviar-email
description: Enviar, conferir ou agendar e-mail por um alias do Emailing (emailing.leonardocosta.dev), em produção via `ssh leonardo_contabo`. Use quando o pedido for mandar um e-mail, programar um envio, ver o que sairia antes de mandar, listar a fila de agendados ou cancelar um agendamento.
---

# Enviar e-mail pelo Emailing

O envio acontece **em produção**, por `ssh leonardo_contabo`, com o comando
`emailing` (atalho para `manage.py` rodando como o usuário do serviço). A
autenticação é a chave ssh: não existe API HTTP, de propósito — ver
`docs/decisoes.md`.

Toda mensagem entra no mesmo `RegistroEnvio` da tela, visível em
`/historico/`. Não há caminho de envio que não deixe registro.

## Sequência

**1. Descobrir os aliases** (nunca chute o slug):

```bash
ssh leonardo_contabo 'emailing verificar_config --json'
```

Devolve `aliases[]` com `slug`, `endereco`, `remetente`, `conta` e `servidor`, e
`problemas[]` — se vier não-vazio, resolva antes de tentar enviar.

**2. Escrever o corpo num arquivo.** O corpo é HTML e **não entra por
argumento**: `argv` aparece no `ps` de outros usuários da máquina e vai para o
histórico do shell.

```bash
ssh leonardo_contabo 'cat > /tmp/corpo.html' <<'HTML'
<p>Bom dia,</p>
<p>…</p>
HTML
```

**3. Conferir antes de mandar.** `--conferir` mostra o envelope resolvido e o
HTML/texto exatamente como sairiam, sem enviar nada:

```bash
ssh leonardo_contabo 'emailing enviar --alias financeiro \
    --para "cliente@exemplo.com" --assunto "Proposta" \
    --corpo-arquivo /tmp/corpo.html --conferir'
```

Confira aqui a assinatura, os marcadores e o `From:`. Depois de conferido, tire
o `--conferir` para enviar de verdade.

**4. Enviar** (ou agendar, com `--em`):

```bash
ssh leonardo_contabo 'emailing enviar --alias financeiro \
    --para "cliente@exemplo.com" --assunto "Proposta" \
    --corpo-arquivo /tmp/corpo.html --json'
```

`--json` devolve `{"ok", "status", "message_id", "registro", "historico"}`.
Saída 1 e `"status": "falhou"` quando o SMTP recusou — a tentativa fica
registrada no histórico do mesmo jeito.

## Agendar

`--em` põe na fila em vez de enviar. Aceita `"2026-09-10 09:00"`,
`"10/09/2026 09:00"` e `"2026-09-10T09:00"`, no fuso do app.

```bash
ssh leonardo_contabo 'emailing enviar --alias financeiro --para c@x.com \
    --assunto "Lembrete" --corpo-arquivo /tmp/corpo.html --em "2026-09-10 09:00"'
```

Quem despacha é o cron, de minuto em minuto. Ver e cancelar:

```bash
ssh leonardo_contabo 'emailing despachar_agendados --conferir --json'  # o que está vencido
```

A fila completa e o botão de cancelar ficam em `/agendados/` na interface web.

Marcadores como `{{ data }}` e `{{ hora }}` num agendamento são resolvidos **na
hora da entrega**, não na hora de agendar — é o comportamento desejado.

## Flags

| | |
|---|---|
| `--alias SLUG` | obrigatório; veja com `verificar_config --json` |
| `--para`, `--cc`, `--cco` | endereços separados por vírgula |
| `--assunto` | |
| `--corpo-arquivo CAMINHO` | `-` lê do stdin (o padrão quando há stdin) |
| `--anexo CAMINHO` | pode repetir; vale o mesmo limite do formulário (18 MiB no total) |
| `--in-reply-to`, `--referencias` | para encadear resposta |
| `--em "…"` | agenda em vez de enviar |
| `--conferir` | mostra e não envia |
| `--json` | saída legível por máquina |

## Cuidados

- **O arquivo do corpo e os anexos precisam ser legíveis pelo usuário
  `emailing`.** Escreva em `/tmp` (o `cat >` acima já sai com 644).
- Endereço inválido, alias desconhecido e estouro do limite de destinatários
  fazem o comando falhar **antes** de qualquer envio, com a mesma validação do
  formulário da tela.
- Não existe trava de "conferi antes de enviar" na linha de comando, ao
  contrário da tela: aqui é um processo e uma entrada só. Se o conteúdo importa,
  rode `--conferir` primeiro — é para isso que ele existe.
- Não invente endpoints HTTP nem tokens de API para isto. A ausência deles é
  uma decisão registrada, não uma lacuna.
