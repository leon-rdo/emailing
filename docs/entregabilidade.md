# Entregabilidade

O que faz um e-mail deste app chegar na caixa de entrada em vez do spam — e o
que já deu errado na prática.

## Por que enviar por alias funciona

O provedor cobra por caixa, não por endereço de saída. O SMTP aceita `From:`
de qualquer endereço **do mesmo domínio** quando autenticado com uma caixa
real. É nisso que o produto inteiro se apoia.

O que autentica um e-mail não é a caixa, é o **domínio**:

- **SPF** autentica o domínio do *envelope* (`MAIL FROM`), não o do `From:`.
- **DKIM** assina com `d=<domínio>`, usando o seletor que o provedor publica
  para o domínio.

Nenhum dos dois é "por caixa". Por isso `financeiro@` funciona autenticando
como `me@` — e por isso `From:` fora do domínio autenticado **não** funciona:
o DMARC exige que o domínio do `From:` alinhe com o do SPF ou do DKIM.

É essa a razão do campo *domínios permitidos* na conta e da validação no
`Alias.clean()`. Não é burocracia: é a única regra que impede o app de virar
uma arma contra a própria reputação do domínio.

## O que precisa estar no DNS

| Registro | Papel | Sem ele |
|---|---|---|
| SPF | autoriza o servidor de saída | DMARC depende só do DKIM |
| DKIM | assina a mensagem | **encaminhamento quebra o DMARC** |
| DMARC | diz o que fazer quando não alinha | ninguém sabe que você foi falsificado |

**DKIM é o que sobrevive a encaminhamento.** Quando alguém encaminha seu
e-mail, o envelope muda e o SPF quebra; só o DKIM continua válido. Domínio com
`p=quarantine`/`p=reject` e sem DKIM entrega bem no caminho direto e vai para
quarentena assim que for encaminhado.

Para cada domínio dos aliases, confira e anote três coisas (o `CLAUDE.local.md`
de uma implantação é um bom lugar para guardar o estado de cada um):

- **SPF** incluindo o provedor — por exemplo `include:secureserver.net` na
  GoDaddy ou `include:_spf.mail.hostinger.com` na Hostinger;
- **DKIM** publicado no seletor do provedor, confirmado num `.eml` recebido
  (`dkim=pass` no `Authentication-Results`);
- **DMARC** e a política (`p=none`, `p=quarantine`, `p=reject`).

Um domínio com `p=quarantine` e sem DKIM funciona no caminho direto (alinha por
SPF), mas vai para quarentena assim que alguém encaminhar a mensagem.

Verificar rapidamente:

```bash
dig +short <dominio> TXT              # SPF
dig +short _dmarc.<dominio> TXT       # política DMARC
dig +short <seletor>._domainkey.<dominio> TXT
```

E, num e-mail recebido, o cabeçalho `Authentication-Results` diz a verdade
final — é ele que mostra `dkim=pass` / `dmarc=pass`.

## Encoding: quoted-printable, não 8bit {#encoding}

**Já deu errado:** emojis da assinatura chegaram como `ð§` no lugar de 📧.

O Django manda UTF-8 como `Content-Transfer-Encoding: 8bit`, ou seja, os bytes
crus na rede. Basta um salto do caminho não negociar `8BITMIME` (ou tratar o
corpo como Latin-1) para virar mojibake. Ele só troca para quoted-printable
sozinho quando alguma linha passa de 998 caracteres — as de uma assinatura
normal têm ~300, então ficava 8bit.

A mensagem saía daqui íntegra (conferido nos bytes); o estrago era no
transporte. `montagem.py` força quoted-printable: o corpo trafega em **ASCII
puro** e o cliente remonta no destino.

O detalhe que faz funcionar é passar um objeto `Charset` em vez da string
`"utf-8"` — o `SafeMIMEText` do Django só sobrescreve a escolha quando recebe
a string.

## CSS: o que clientes de e-mail realmente suportam

Um template moderno de página **não** é um template de e-mail. Do HTML de
exemplo que passou por aqui:

| Recurso | Situação |
|---|---|
| `style="…"` inline | funciona em todos — é por isso que o CSS é embutido antes de enviar |
| `<style>` com `@media` | Gmail e Apple Mail sim; **Outlook clássico não** |
| `display: grid`, `flex` | **ignorados** — o grid 2×2 vira uma coluna empilhada |
| `border-radius`, `box-shadow` | Outlook clássico ignora (degrada sem quebrar) |
| `transition`, `:hover` | sem efeito na maioria; inofensivo |
| `<table>` para layout | **o único jeito robusto** de fazer colunas |

Layout de e-mail que precisa funcionar no Outlook se faz com `<table>`, não com
grid ou flex. O app não converte isso — e nem deveria: reescrever o layout de
quem cola um template seria adivinhação.

## Outros detalhes que importam

- **`Date` com fuso real.** `EMAIL_USE_LOCALTIME=True` mais `TZ` no ambiente do
  serviço. Sem isso o cabeçalho sai `-0000`, que na RFC 5322 significa "hora
  local desconhecida" e irrita alguns filtros.
- **`Message-ID` no domínio do remetente**, não no hostname da máquina. Sem
  ajustar, o Django usa `socket.getfqdn()` e o id sai como `<…@vmi2934480>`.
  O mesmo valor corrige o nome no `EHLO`.
- **Parte `text/plain` sempre.** E-mail só-HTML tem penalidade mensurável em
  filtro de spam. O `html_para_texto()` gera uma versão legível — não bonita,
  legível.
- **Bounces seguem o envelope.** Com envelope = alias, a DSN cai no alias. Se
  um dia existir alias que não seja endereço entregável, os bounces somem em
  silêncio — para isso servem o `Reply-To` do alias e o *envelope fixo* da
  conta.
- **Nunca definir `Return-Path`.** Quem escreve é o MTA que recebe.
