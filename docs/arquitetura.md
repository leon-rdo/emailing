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

## Duas outras portas para o mesmo envio

`enviar_email()` tem três chamadores, e o desenho é que os três compartilhem
tudo o que importa — sanitização, assinatura, montagem e `RegistroEnvio`:

```
tela (views.redigir) ─────────────┐
manage.py enviar ─────────────────┼──► enviar_email() ──► RegistroEnvio ──► SMTP
despachar_agendados (cron) ───────┘
```

### `manage.py enviar` — o operador e os agentes

A porta de quem não está na tela: o dono por ssh, ou um agente com acesso ao
servidor. Autentica pela chave ssh, e não por token HTTP — o porquê está em
[decisoes.md](decisoes.md#cli).

Não tem validação própria: monta um `FormularioRedacao` com o que veio nos
argumentos, então endereço, limite de destinatários, alias e formato de data são
julgados pelo mesmo código da tela. `--conferir` é a prévia sem tela, e funciona
pelo mesmo motivo que a prévia funciona: `montar_email()` é pura.

O que ele **não** tem é a trava de `hash_previa` — no terminal não existe o
intervalo humano que ela protege.

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

`referencias_para_resposta()` é compartilhada pelos caminhos 1 e 3: References
do original + `Message-ID` do original por último, sem duplicar, limitado a 20
(mantendo o primeiro da thread).

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
