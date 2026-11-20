# Emailing no webmail — extensão de navegador

Escreva no webmail da caixa (Titan, Hostinger) e envie **por um alias, pelo seu
Emailing**. A extensão leva o rascunho até a tela de redação do Emailing; a
prévia, a trava de conferência e o envio são os de lá.

Ela não é um segundo jeito de enviar: é um jeito de **preencher a tela**. Não
há requisição da extensão para o servidor, não há token e não há endpoint novo
(ver [docs/decisoes.md](../docs/decisoes.md#extensao)).

## Instalar

Chrome, Edge, Brave ou outro navegador baseado no Chromium, versão 111 ou mais
nova. Não está em loja nenhuma: carrega-se a pasta.

1. Abra `chrome://extensions` e ligue o **Modo do desenvolvedor**.
2. **Carregar sem compactação** → escolha esta pasta (`extensao/`).
3. A página de opções abre sozinha. Informe o endereço do seu Emailing
   (`https://emailing.example.com`) e salve. O Chrome pede permissão para a
   extensão agir **nesse endereço** — é lá que ela preenche o formulário.
4. Recarregue as abas do webmail que já estavam abertas.

Entre no Emailing normalmente, no mesmo navegador. A extensão não guarda senha
nem código: usa a sessão que já existe.

## Usar

Em qualquer janela de escrita (mensagem nova, resposta, encaminhamento):

- **Titan** — escolha um alias no “De:”. Em vez do aviso de upgrade, o alias
  fica marcado (“via Emailing”) e o **Enviar** passa a abrir a confirmação. O
  `×` da marca volta ao envio normal pela caixa. O botão **Emailing**, ao lado
  do Enviar, faz o mesmo sem escolher alias antes.
- **Hostinger** — clique em **Emailing**, na linha do “De”. O endereço
  escolhido no “De” vai junto. O Enviar da Hostinger continua sendo o dela.

Abre uma janela com a tela de redação do Emailing já preenchida: remetente,
destinatários, assunto, corpo, anexos e o encadeamento da resposta. Confira a
prévia e envie. Quando a mensagem sai, a janela fecha e o rascunho do webmail é
descartado. Se você fechar a janela sem enviar, nada muda no webmail.

Na confirmação também dá para **agendar** ou **salvar como rascunho** do
Emailing. Agendar descarta o rascunho do webmail; salvar rascunho não.

## O que vai e o que não vai

| | |
|---|---|
| Remetente | O alias do Emailing com o mesmo endereço do “De”. Sem um, entra o primeiro alias do mesmo domínio e a janela avisa. |
| Corpo | O HTML do editor do webmail, sem a assinatura de lá: a do alias entra pelo Emailing. Passa pelo mesmo sanitizador de sempre. |
| Citação da resposta | Vai dentro do corpo. Na Hostinger, enquanto a citação está recolhida (“…”), só o texto simples dela está disponível. |
| `In-Reply-To` / `References` | O `Message-ID` da mensagem respondida. No Titan, também os das mensagens anteriores da conversa aberta. |
| Anexos | Os que você anexou nesta sessão do navegador. Anexo herdado (de um encaminhamento, de um rascunho antigo) não acompanha: a janela avisa, e você anexa lá. |
| Imagens coladas no corpo | Não acompanham: moram no servidor do webmail. A janela avisa. |

## Quando o webmail mudar

A extensão lê o estado interno das duas telas (React no Titan, Vue na
Hostinger) e se apoia nos marcadores `data-testid` / `data-qa` delas. Uma
atualização do webmail pode quebrar isso. Os sintomas e onde olhar:

| Sintoma | Onde |
|---|---|
| O botão **Emailing** sumiu | `seletorCompositor` e `ancora` do adaptador (`webmail/titan.js`, `webmail/hostinger.js`) |
| “O Titan mudou: não achei o rascunho” | `webmail/titan-pagina.js` (a subida pela árvore do React) |
| “A Hostinger mudou: não achei o rascunho” | `webmail/hostinger-pagina.js` (o componente `MessageComposer`) |
| No Titan, escolher o alias abre o aviso de upgrade | `ITEM_DE` e a classe `titan-max-wrapper`, em `webmail/titan.js` |
| A assinatura do webmail veio junto | os seletores removidos em `corpo()` de cada adaptador |
| O rascunho do webmail não foi descartado | `descartar` de cada adaptador |

**Se o modo alias do Titan parar de interceptar o Enviar, a mensagem sai pelo
Titan com o endereço da caixa.** É o defeito que mais importa: depois de uma
atualização visível do Titan, faça o primeiro envio para você mesmo.

## Como é feita

```
manifest.json            o que roda onde
config.js                o endereço do Emailing (o único dado guardado)
fundo.js                 service worker: abre a confirmação, guarda a carga, repassa anexos
opcoes/                  a página de opções
webmail/comum.js         núcleo no webmail: botão, ponte, anexos, avisos
webmail/titan.js         adaptador do Titan (modo alias, interceptação do Enviar)
webmail/titan-pagina.js  leitura do rascunho no mundo da página (só lê)
webmail/hostinger*.js    o mesmo par para a Hostinger
emailing/preencher.js    preenche a tela de redação e acompanha o desfecho
```

Sem dependência, sem etapa de build: o que está na pasta é o que o navegador
carrega.

## Testar

Não há teste automatizado da extensão no repositório (o projeto não tem npm).
O que foi exercitado antes de ela entrar está em
[docs/decisoes.md](../docs/decisoes.md#extensao-testes); para repetir à mão:

1. Emailing local (`uv run manage.py runserver`), com `http://localhost:8000`
   nas opções da extensão.
2. No webmail, uma mensagem para você mesmo com formatação, um anexo e uma
   resposta a outra mensagem.
3. Conferir na janela: remetente, destinatários, prévia, anexo, a nota “Em
   resposta à mensagem”.
4. Enviar e conferir o `.eml` recebido: `From`, `In-Reply-To`, `References`.
