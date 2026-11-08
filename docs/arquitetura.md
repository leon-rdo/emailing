# Arquitetura

O caminho de uma mensagem, do editor até o SMTP. Cada seção diz *o que*
acontece e, onde importa, *por que assim* — as decisões com alternativa
razoável estão em [decisoes.md](decisoes.md).

## Visão de conjunto

```
navegador                          servidor
─────────                          ────────
Trix / textarea HTML bruto
        │  (debounce 600 ms)
        ▼
   POST /previa-ajax/  ──────────►  FormularioPrevia (tolerante)
        ◄──── JSON {html,hash} ───  _previa_de() ─┐
                                                  │  mesma função
   POST /  (acao=enviar)  ────────►  FormularioRedacao (estrito)
                                     _previa_de() ─┘
                                          │ hash confere?
                            ┌─────────────┴─────────────┐
                            ▼                           ▼
                       enviar_email()            EnvioAgendado
                            │                     (acao=agendar)
                       RegistroEnvio (ENVIANDO)         │
                            │                      cron, 1 min
                       SMTP da conta do alias           │
                            │                           │
                       RegistroEnvio (ENVIADO/FALHOU) ◄──┘
```

O ponto central: **prévia e envio passam pela mesma função**. A prévia não é
uma aproximação do que será enviado — é o mesmo cálculo, com o mesmo
sanitizador e a mesma assinatura. Ver [decisoes.md](decisoes.md#previa).

## Contas e aliases

`ContaEmail` é uma caixa real que autentica no SMTP (host, porta, usuário,
senha cifrada, STARTTLS ou SSL). `Alias` é um endereço pelo qual se envia,
apontando para uma conta.

A separação é o produto inteiro: uma conta serve vários aliases (o motivo do
projeto existir, já que o Titan cobra por alias), e contas diferentes vivem em
provedores diferentes — Titan na 587 com STARTTLS e Hostinger na 465 com SSL
convivem sem se saberem.

`Alias` expõe as propriedades que o resto do app consome:

| Propriedade | O que é | Por que existe separada |
|---|---|---|
| `remetente` | cabeçalho `From:`, via `formataddr` | montar `"Nome <addr>"` à mão gera cabeçalho inválido com acento |
| `envelope` | `MAIL FROM` do SMTP | é o que o SPF autentica, e é independente do `From:` |
| `smtp` | kwargs para `get_connection()` | a conexão é da conta, não global |
| `dominio_message_id` | domínio do `Message-ID` e do EHLO | filtros conferem se bate com o `From:` |

Esses nomes são os mesmos de quando os aliases vinham do `.env`. Foi assim que
a migração para o banco não se espalhou por `montagem.py`, `envio.py` e as
views — elas nunca souberam que a origem mudou.

## Preparo do corpo (`saneamento.py`)

Duas etapas, nesta ordem, e a ordem importa:

1. **Embutir o CSS** (`css-inline`). Regras de `<style>` viram `style="…"` em
   cada elemento. O `<style>` original é mantido, porque `@media` não tem como
   virar inline.
2. **Limpar** (`nh3`). Mata `<script>`, `<iframe>`, `<form>`, manipuladores
   `on*`, e tags de `<head>` **com o conteúdo junto** (senão o `<title>` do
   documento vaza como primeira linha do e-mail — já aconteceu).

Sem a etapa 1, a etapa 2 apagaria `<style>` e `class` e o e-mail chegaria sem
formatação nenhuma. Por isso `class` e `<style>` sobrevivem: as media queries
preservadas miram justamente as classes.

O que **não** é filtrado: propriedades CSS individuais (o nh3 é tudo-ou-nada
por tag no `style`). `mso-*` colado do Word passa — feio, inofensivo.

## Montagem (`montagem.py`)

`montar_email()` é função pura: mesmos dados e mesmo alias ⇒ mesma mensagem.

Existem **dois corpos**, e a diferença é sutil mas carrega uma garantia:

- **autoral** (`montar_corpo`) — sanitizado, com os marcadores `{{ … }}`
  intactos. É o que entra no `hash_previa`.
- **final** (`montar_corpo_final`) — com os marcadores expandidos. É o que sai
  no e-mail.

Se o hash fosse do final, `{{ hora }}` mudaria sozinho entre a prévia e o
clique em Enviar, e o envio seria recusado por "o conteúdo mudou".

A **assinatura não passa pelo sanitizador**. É conteúdo do operador, cadastrado
no admin; sanitizá-la não protege de nada e destruiria o layout em `<table>`
com estilo inline.

O corpo sai em **quoted-printable**, não no `8bit` que o Django usa por padrão
— ver [entregabilidade.md](entregabilidade.md#encoding).

## Envio (`envio.py`)

```
message_id = make_msgid(domain=alias.dominio_message_id)
DNS_NAME._fqdn = alias.dominio_message_id      # corrige o EHLO
RegistroEnvio(status=ENVIANDO)                 # ANTES da rede
    ↓
get_connection(**alias.smtp) → send()
    ↓
status = ENVIADO | FALHOU + erro
```

`status=ENVIANDO` é gravado **antes** da chamada SMTP: é o registro de que o
envio foi tentado, e é o que faz o histórico contar a verdade mesmo se o
processo morrer no meio da chamada de rede.

`enviar_email()` **nunca levanta**. O status do retorno é a resposta — falha de
SMTP vira `FALHOU` com o erro guardado, visível no histórico.

`DNS_NAME._fqdn` é ajustado **por envio**, não no boot: com contas em domínios
diferentes, fixar um domínio na inicialização estaria errado para todas as
outras.

## Três outras portas para o mesmo envio

`enviar_email()` tem quatro chamadores, e o desenho é que os quatro compartilhem
tudo o que importa — sanitização, assinatura, montagem e `RegistroEnvio`:

```
tela (views.redigir) ─────────────┐
manage.py enviar ──┐              │
                   ├─ redacao.py ─┼──► enviar_email() ──► RegistroEnvio ──► SMTP
manage.py mcp ─────┘              │
despachar_agendados (cron) ───────┘
```

`redacao.py` é o que impede as duas portas sem tela de terem validação própria:
`preparar()` monta o `FormularioRedacao` (ou o `FormularioRascunho`) com o que
veio, e `descrever_conferencia()` é a prévia sem tela.

### `manage.py enviar` — o operador e os agentes

A porta de quem não está na tela: o dono por ssh, ou um agente com acesso ao
servidor. Autentica pela chave ssh, e não por token HTTP — o porquê está em
[decisoes.md](decisoes.md#cli).

Não tem validação própria: passa por `redacao.preparar()`, que monta um
`FormularioRedacao` com o que veio nos argumentos, então endereço, limite de destinatários, alias e formato de data são
julgados pelo mesmo código da tela. `--conferir` é a prévia sem tela, e funciona
pelo mesmo motivo que a prévia funciona: `montar_email()` é pura.

O que ele **não** tem é a trava de `hash_previa` — no terminal não existe o
intervalo humano que ela protege.

### `manage.py mcp` — o Claude Code

```
Claude Code ──stdio──► ssh -T emailing-mcp ══ chave restrita ══► sshd (root)
                         command="/usr/local/bin/emailing mcp",restrict
                              └─► sudo -u emailing … manage.py mcp
                                    ├─ redacao / envio / agendamento  (o mesmo da CLI)
                                    └─ caixa.py ── IMAP, sob demanda
```

Um processo por sessão do Claude Code, falando JSON-RPC pelo stdin/stdout do
ssh. As tools (`mcp_servidor.py`) são finas: validam por `redacao`, enviam por
`enviar_email()`, agendam e guardam rascunho por `agendamento`, e leem a caixa
por `caixa.py`. Erro de domínio vira `ToolError` com a mensagem em português.

| Leitura (podem ir para a allowlist) | Escrita (aprovação a cada chamada) |
|---|---|
| `listar_aliases`, `listar_pastas`, `buscar_emails`, `ler_email`, `conferir_email`, `listar_agendados`, `historico` | `enviar_email`, `agendar_email`, `salvar_rascunho`, `cancelar_agendado`, `marcar_email`, `mover_email` |

O que o MCP tem e a CLI não: o **teto de envios por sessão** e a leitura da
caixa. O porquê de cada escolha está em [decisoes.md](decisoes.md#mcp).

### `despachar_agendados` — o cron

```
cron (1 min) → flock → despachar_pendentes(limite)
                          │
                          ├─ SELECT status=agendado AND enviar_em <= agora
                          │
                          └─ para cada, em série:
                               reivindicar()  ── UPDATE … WHERE status='agendado'
                                   │ rowcount == 1 → é meu
                                   ▼
                               despachar_um()
                                   ├─ alias/conta inativo → FALHOU
                                   ├─ atraso > tolerância  → FALHOU
                                   └─ enviar_email()
                                        ├─ ENVIADO  → status=enviado
                                        ├─ falhou, tem tentativa → volta para
                                        │    agendado com enviar_em + backoff
                                        └─ falhou, esgotou → FALHOU + aviso
```

Três coisas existem aqui e não no caminho da tela, todas pela mesma razão —
**ninguém está olhando**: a reivindicação atômica (não há POST-redirect-GET nem
dedo no botão), a retentativa com espera crescente, e a tolerância de atraso
(ver [decisoes.md](decisoes.md#tolerancia)).

O `EnvioAgendado` guarda o `DadosRedacao` **como veio do editor**, cru. Por
isso o despacho sanitiza e expande marcador no momento de sair — e é isso que
faz `{{ hora }}` num agendamento significar a hora da entrega.

### Editar, rascunhar, consultar

A mesma linha de `EnvioAgendado` percorre `rascunho → agendado → enviando →
enviado/falhou`, com `cancelado` como saída lateral de `agendado`. Toda mudança
de estado feita pela tela é um `UPDATE … WHERE status IN (…)` conferido pelo
`rowcount` — é assim que a edição e o despacho disputam a linha sem se pisar:

```
GET  /mensagens/<id>/editar/   copia os anexos → token novo (a "cópia")
POST … acao=salvar             reescrever(de=agendado, para=agendado)
POST … acao=salvar_rascunho    reescrever(de=rascunho|agendado, para=rascunho)
POST … acao=agendar            reescrever(de=rascunho, para=agendado)
POST … acao=enviar             enviar_email() e, se saiu, descartar o rascunho
                               (só vale para rascunho; quem está na fila ignora)
```

`reescrever()` só troca a pasta de anexos da mensagem pela cópia **depois** de o
`UPDATE` ganhar; se perde, apaga a cópia. Ver [decisoes.md](decisoes.md#edicao).

`/agendados/<id>/` é só leitura e serve a qualquer estado. Mostra o corpo
*autoral* (marcadores como escritos) e, para os anexos, a foto guardada em
`EnvioAgendado.anexos` quando os arquivos já não existem.

## Anexos (`anexos.py`)

Não existe rota de upload separada: qualquer POST da tela de redação processa
`request.FILES` antes de decidir o que mostrar. O primeiro arquivo gera um
token opaco (campo oculto `rascunho`), e os arquivos daquele token vivem em
`RASCUNHOS_DIR/<token>/`, nomeados `<id>__<nome-original>`.

O arquivo é o único pedaço de estado que não cabe de volta num campo oculto do
formulário — daí o disco. Sobrevive entre prévias até o envio, e
`limpar_rascunhos` (cron diário) apaga os abandonados.

A linha de comando entra pela mesma pasta: `guardar_caminhos()` copia arquivos
do disco local para um token novo, e a partir daí o rascunho é indistinguível de
um vindo do navegador — é o que permite agendar com anexo sem um segundo caminho
de código. As regras de tamanho e extensão vivem em `_validar()`, chamado pelas
duas origens de propósito.

**A limpeza precisa conhecer a fila de agendados e os rascunhos salvos.** Anexo
de mensagem agendada ou salva como rascunho tem que sobreviver ao TTL, e uma pasta que desaparece faz `ler_anexos()`
devolver `[]` — a mensagem sairia sem anexo, em silêncio. Ver
[decisoes.md](decisoes.md#anexos-agendados).

## Resposta a threads (`eml.py`)

Três caminhos chegam ao mesmo lugar:

1. **Importar `.eml`/`.txt`** — `BytesParser(policy=default)` sobre bytes
   limitados, em memória (nunca toca o disco: é correspondência de terceiros).
   `To` prefere `Reply-To` a `From`; a citação sai de `get_body()` e passa pelo
   sanitizador.
2. **`Message-ID` digitado à mão** — quando não há o arquivo.
3. **"Responder" no histórico** — usa o `message_id` que o próprio app gravou.
4. **`responder_a` no MCP** — o servidor baixa o original por IMAP e o passa,
   em memória, pelo mesmo `analisar_eml()` do caminho 1.

`referencias_para_resposta()` é compartilhada pelos caminhos 1, 3 e 4: References
do original + `Message-ID` do original por último, sem duplicar, limitado a 20
(mantendo o primeiro da thread).

## Recebimento (`caixa.py`)

Só para o MCP; a tela não tem caixa de entrada. Cada operação é uma conexão
`IMAP4_SSL` com o `timeout` da conta: login, operação, logout. Nada é guardado.

| Função | IMAP | Muda a caixa? |
|---|---|---|
| `listar_pastas` | `LIST` (nomes em UTF-7 modificado, decodificados) | não |
| `buscar` | `EXAMINE` + `UID SORT (REVERSE DATE)` — ou, sem SORT, `UID SEARCH` + `Date` da janela, ordenado aqui — + `UID FETCH (… BODY.PEEK[HEADER.FIELDS …])` | não |
| `ler` | `EXAMINE` + `UID FETCH (BODY.PEEK[])`, com teto `IMAP_MAX_BYTES` | não |
| `marcar` | `SELECT` + `UID STORE ±FLAGS (\Seen)`/`(\Flagged)` | sim |
| `mover` | `SELECT` + `UID MOVE`, ou `UID COPY` + `\Deleted` + `UID EXPUNGE` | sim |

A mensagem é identificada por `conta:uidvalidity:uid:pasta`; toda operação
confere o UIDVALIDITY antes de agir. `interpretar()` devolve o corpo em texto
(`html_para_texto`, com os links encurtados por `encurtar_links`) ou em HTML
sanitizado (`limpar_html`, links intactos), truncado em `MCP_LIMITE_CORPO`, e os
anexos só como metadados. A ordem da busca é pela data do e-mail — ver
[decisoes.md](decisoes.md#mcp-ordem).

## Segurança

| Camada | O que faz |
|---|---|
| `LoginRequiredMiddleware` | toda URL nasce fechada; só o login tem `@login_not_required` |
| `django-otp` | TOTP obrigatório em produção |
| `ExigirVerificacaoOTPMiddleware` | encerra sessão autenticada sem segundo fator — sem estado intermediário |
| `django-axes` | lockout antes do Argon2 rodar |
| Argon2id perfil OWASP | `m=19456` no lugar dos 100 MiB/hash do padrão do Django |
| CSP com nonce | script inline só com nonce; o iframe da prévia herda o CSP |
| `sandbox=""` no iframe | a prévia não executa nada |
| `cripto.py` | senha SMTP cifrada com chave derivada do `SECRET_KEY` |
| chave ssh restrita | o MCP só abre com `command="emailing mcp",restrict`; sem shell, PTY ou forwarding |
| aprovação no Claude Code | tools de escrita do MCP nunca na allowlist; teto `MCP_MAX_ENVIOS_POR_SESSAO` |
