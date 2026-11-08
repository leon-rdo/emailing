# Decisões

Cada item é algo que **parece errado até saber por quê**. Se for mexer em
alguma dessas coisas, leia a entrada primeiro — várias já foram "consertadas"
de volta ao estado ruim em algum momento.

Formato: **decisão** → alternativa óbvia → por que não.

---

## Produto e stack

### Django sem DRF

A UI são três formulários e não existe um segundo cliente. DRF adicionaria
serializers e uma camada de permissão para substituir formulários que já
validam. O único endpoint JSON (`/previa-ajax/`) é uma view de dez linhas.

### Sem Celery, sem broker

**Alternativa:** fila para o envio não bloquear a requisição.
**Por que não:** um broker e um worker num servidor pequeno, para o envio
ocasional de uma pessoa. `SMTP_TIMEOUT` explícito resolve o problema real (o
padrão do Django é `None`, que bloqueia a thread para sempre). Esse timeout
**não é opcional** — com workers `gthread`, o `--timeout` do gunicorn é
heartbeat e não mata thread bloqueada.

### Sem npm, sem bundler, sem framework de CSS

Um `estilo.css` escrito à mão e JS inline com nonce de CSP. O Trix é
vendorizado (UMD, 175 KB) porque é o único JS de terceiros.

---

## E-mail

### A assinatura não passa pelo sanitizador {#assinatura}

**Alternativa:** sanitizar tudo, por uniformidade.
**Por que não:** a assinatura é conteúdo do operador, cadastrado no admin por
quem administra o app. Sanitizá-la não protege de nada e destruiria o layout em
`<table>` com estilo inline. O sanitizador existe para o que é *colado* no
corpo.

Isso precisa continuar sendo um comentário no código: já foi "endurecido" por
engano.

### CSS embutido antes de sanitizar

**Alternativa:** só sanitizar, mantendo `<style>`.
**Por que não:** Outlook ignora boa parte do CSS de folha. Toda ferramenta séria
de e-mail transforma as regras em `style="…"` por elemento antes de mandar.

Consequência aceita: `class` e `<style>` sobrevivem à limpeza (as media queries
preservadas miram as classes), e com eles passa `mso-*` colado do Word — feio,
inofensivo.

### Corpo em quoted-printable

**Alternativa:** deixar o padrão do Django (`8bit`).
**Por que não:** já quebrou. Emojis chegaram como `ð§`. Ver
[entregabilidade.md](entregabilidade.md#encoding).

### Envelope no alias, não na caixa

O `MAIL FROM` é o próprio alias (é o que o SPF autentica e o que alinha o
DMARC). O campo *envelope fixo* da conta existe como escotilha, caso um
provedor passe a recusar envelope de alias.

---

## Prévia e envio

### A prévia e o envio compartilham a mesma função {#previa}

`montar_email()` é pura, e `_previa_de()` é chamada pelas duas rotas. WYSIWYG
**por construção**, não por fidelidade de armazenamento.

**Alternativa:** guardar o rascunho (sessão, modelo `Rascunho`, campo assinado).
**Por que não:** todas guardam uma cópia e torcem para ela bater com o que sai.
Recalcular sobre o mesmo POST elimina a classe inteira de bug.

### A prévia não exige destinatário nem valida endereço

**Alternativa:** usar o mesmo formulário do envio.
**Por que não:** já quebrou duas vezes, com o mesmo sintoma ("a prévia só
funciona no botão"):

1. Exigir "Para" deixava a prévia morta enquanto se escrevia o corpo — que é a
   ordem natural.
2. Validar endereço a cada tecla congelava a prévia no meio de cada digitação:
   todo e-mail passa por `cliente@exe` antes de `cliente@exemplo.com`, e o JS
   não atualiza nada quando a resposta é `ok:false`.

**Nada relacionado a destinatário pode derrubar uma prévia** — ela é do
conteúdo. O envio (`FormularioRedacao`) continua estrito.

> Lição de teste: o primeiro caso passou despercebido porque o teste de
> navegador usava `fill()`, que salta direto para o estado válido. Digitação
> real passa por estados intermediários — teste com `pressSequentially`.

### O `hash_previa` é do conteúdo autoral

Cobre alias, para, cc, cco, assunto, HTML **com os marcadores intactos**, e os
ids dos anexos.

- Cobrir só o HTML deixaria passar trocar o destinatário depois de
  pré-visualizar (já foi assim).
- Cobrir o HTML **expandido** faria `{{ hora }}` mudar sozinho entre a prévia e
  o clique em Enviar, recusando o envio.

### Duplo envio não tem trava no servidor

**Alternativa:** campo de idempotência + migração.
**Por que não:** POST-redirect-GET já tira a URL de envio da barra de endereço,
então um F5 reemite GET. O que sobra são dois cliques quase simultâneos,
resolvido desabilitando o botão no clique. O custo de um campo e uma migração
não se paga para essa janela de tempo.

### A moldura da prévia não vai no e-mail

O iframe não herda estilo, então HTML sem `font-family` cairia na fonte
serifada do navegador — que nenhum cliente de e-mail usa. A prévia vai numa
moldura que imita o padrão deles. Ela existe **só na tela**: o que é enviado, e
o que entra no hash, é o HTML puro. Há teste garantindo.

---

## Frontend

Redesenho de outubro/2026: casca de webmail (menu lateral, lista, modal de escrita),
com a tipografia como identidade. O que parece errado até saber por quê:

### A prévia é um painel fixo, nunca escondido {#previa-fixa}

**Alternativa:** painel `hidden` até o primeiro "Pré-visualizar" (como era), ou
prévia abaixo do formulário.
**Por que não:** o operador só via a prévia depois de clicar, longe do editor — era a
queixa. Agora ela ocupa a coluna direita do modal e `compor.js` a pede ao carregar a
tela, sem esperar tecla.
**O que continua igual:** a trava de `hash_previa`. O que mudou é o botão: nasce
`disabled` (antes, `hidden`) e só libera com a prévia **em dia**; enquanto o
operador digita, volta a `disabled`. Sem JS o servidor continua recusando hash velho.

### Caixa é a conta SMTP, e o filtro é `?caixa=<id>` {#caixas}

O menu lista as caixas (`ContaEmail` ativas) quando há mais de uma, e escolher uma filtra
Enviados, Agendados e Rascunhos. **Sem estado de sessão**: o filtro é um parâmetro de URL que
o menu carrega adiante, então uma aba nunca muda a outra. `RegistroEnvio` guarda o *slug* do
alias, não a conta; por isso a caixa ali é o conjunto de slugs dos aliases dela. A cor do
bloco na lista vem do **domínio** de quem enviou (não do alias), que é o que separa as caixas
a olho: dois aliases do mesmo domínio têm a mesma cor. O seletor "De" agrupa por caixa
(`<optgroup>`) a partir de duas.

### Configurações são telas próprias, e nada apaga {#configuracoes}

Contas SMTP e aliases têm tela no próprio app (`views_configuracoes.py`); o `/admin/` continua
existindo. **Não há botão de excluir**: o histórico guarda o slug do alias e os agendamentos
apontam para ele com `PROTECT`; um alias apagado deixaria mensagens sem saber de onde saíram.
Para parar de usar, desativa-se. O `slug` do alias não muda depois de criado, pelo mesmo
motivo. A senha da conta nunca volta para a tela (campo em branco mantém a atual), e as duas
caixas `usar_tls`/`usar_ssl` do modelo viram uma escolha só, para o estado inválido "as duas"
nem existir.

### "Testar conexão" autentica, mas não envia {#testar-conta}

`POST /configuracoes/contas/testar/` abre a conexão e faz `login`, nada mais. **Não contradiz**
"não existe API HTTP de envio": ele não consegue enviar mensagem nenhuma, só dizer se os dados
da conta funcionam. Senha em branco usa a guardada (ao editar).

### A assinatura é editada como HTML, com prévia pelo caminho do envio {#assinatura-html}

Não há editor visual de propósito: a assinatura é `<table>` com estilo inline, e o Trix
reescreve o HTML que recebe (é o mesmo motivo de ela não passar pelo sanitizador). O editor é
código à esquerda e a prévia à direita; a prévia vem de `/configuracoes/assinatura-previa/`,
que usa `montar_corpo` + `emoldurar_para_previa` (a montagem real do envio) e vai para um
`<iframe sandbox="">`. Imagens só aparecem na prévia se estiverem nos hosts do CSP
(`HOSTS_IMAGENS_ASSINATURA`); o e-mail enviado não depende disso, e a tela avisa.

### No celular o menu é uma gaveta, e as ações da fila ficam à vista {#mobile}

Abaixo de 900px a barra lateral vira uma barra fixa (marca, Escrever, botão de menu) e a
navegação inteira abre numa gaveta; alvos de toque têm 44px. Duas coisas que parecem erro:
**o modal de escrita não foca nenhum campo ao abrir** em tela de toque (focar abriria o
teclado por cima da tela antes de ela ser vista), e **as ações da linha** (editar, cancelar,
descartar) aparecem sempre em tela sem hover, porque no desktop elas só surgem ao passar o
mouse e no celular não existe "passar o mouse".

### O botão Enviar também espera um destinatário, mas a prévia não {#destino-no-botao}

A prévia segue tolerante com o "Para" (ver [acima](#previa)) — exigi-lo já a matou duas
vezes. Quem exige é o **botão**: `compor.js` mantém Enviar/Agendar/Salvar alterações
desabilitados sem algo com `@` no "Para" e diz o motivo. O servidor valida de qualquer
jeito; isto só poupa a ida e volta.

### O `<iframe sandbox="">` fica, e a prévia pisca-menos por troca de iframe {#sandbox}

Para preservar a rolagem da prévia seria preciso `allow-same-origin`, o que enfraquece
a garantia documentada (e testada) de que a prévia não executa nada. Preferiu-se
perder a rolagem entre atualizações e **trocar o iframe só depois de o novo carregar**,
para não piscar em branco. Pelo mesmo motivo a tela de envio (`registro.html`) passa o
corpo pela mesma moldura: sem ela o iframe cai na fonte serifada do navegador.

### Fonte variável servida do próprio domínio

`Bricolage Grotesque` (largura 75–100, peso 200–800) e `Spline Sans Mono` ficam em
`static/mensagens/fontes/` (licença OFL em `LICENSE.txt`). O CSP tem `font-src 'self'`:
fonte de terceiros não carrega. Sem npm, sem pacote: dois `.woff2` baixados uma vez.
A mono é só para dado (datas, contagens, cabeçalhos técnicos), nunca enfeite.

### O assunto condensa ao encher

O campo de assunto é um `<input>` em corpo grande cujo eixo de largura fecha de 100%
para 75% conforme o texto cresce, e depois o corpo diminui. Continua `<input>`, **não
`textarea`**: assunto com quebra de linha vira `BadHeaderError` no Django.

### O modal de escrita é uma tela inteira, não um fragmento

`redigir` renderiza a lista de onde a pessoa veio (só cenário, `inert`) e o `<dialog>`
por cima; fechar navega para a lista. Não é um fragmento carregado por fetch: o POST
de enviar/agendar/salvar continua sendo uma navegação completa com
POST-redirect-GET, e a lista atrás é a real (`views._fundo_do_modal`). Fechar com texto
não salvo pergunta antes (`data-sujo`); a tela reaberta por um POST (anexo, erro de
campo) já nasce "suja".

### O anexo sobe ao escolher o arquivo

A prévia ao vivo (`/previa-ajax/`) não lê `FILES`, e o anexo precisa estar em disco para
entrar na lista e no hash. Então escolher um arquivo dispara um POST completo
(`acao=previa`), o mesmo que o antigo botão "Pré-visualizar". Esse botão ainda existe,
invisível, como **primeiro submit do formulário**: é ele que o Enter num campo aciona,
nunca "Enviar".

### Cor do alias: só matizes que não são vermelho

O bloco de cor de cada alias na lista vem de `crc32(slug)` (não de `hash()`, que muda a
cada processo) sobre uma lista fixa de matizes **sem vermelho**: vermelho é a cor de
"falhou", e um alias vermelho esconderia um envio que deu errado.

---

## Automação e envio programado

### Envio fora da tela é comando de `manage.py`, não API HTTP {#cli}

**Alternativa:** um endpoint autenticado por token (e, sobre ele, um servidor
MCP), para o Claude Code e afins mandarem e-mail.
**Por que não:** o app é fechado por construção —
`LoginRequiredMiddleware`, TOTP obrigatório, `SameSite=Strict`. Abrir uma porta
programática custa isentar a rota de três middlewares, um modelo de token e
rate limit próprio, e o resultado é um endpoint na internet capaz de enviar
como estes domínios. Se o token vazasse seria um relay aberto **com DMARC
alinhado** — o pior cenário possível deste projeto.

O `manage.py enviar` resolve o mesmo problema autenticando pela **chave ssh**,
sem nenhuma superfície nova, e ainda passa pelo mesmo `RegistroEnvio`: uma
trilha de auditoria só, independente de quem redigiu.

MCP entrou na conversa em novembro/2026, e a forma foi a que este parágrafo já
previa: **stdio sobre ssh**, nunca MCP remoto por HTTP, que traria de volta
exatamente o endpoint recusado acima. Ver [MCP](#mcp).

### A linha de comando não tem trava de `hash_previa`

**Alternativa:** exigir um `--hash` conferido, por simetria com a tela.
**Por que não:** na tela a trava protege o intervalo humano entre
pré-visualizar e clicar, no qual o conteúdo pode mudar. No terminal é um
processo e uma entrada, sem intervalo — a trava não protegeria de nada, só
pediria dois comandos onde um basta. Quem quer conferir usa `--conferir`, que
imprime o que sairia e não envia.

### O corpo não entra por argumento

`--corpo-arquivo` ou stdin, nunca `--corpo "<p>…</p>"`. `argv` aparece no `ps`
de qualquer outro usuário da máquina — e esta VPS roda outros serviços — e vai
para o histórico do shell.

### A CLI não tem validação própria

Endereços, limite de destinatários, escolha de alias, formato de data e limites
de anexo saem todos do `FormularioRedacao` e do `anexos._validar`, os mesmos da
tela — por `redacao.preparar`, que o servidor MCP também usa. Duas validações divergem, e o sintoma seria "funciona no navegador e não
no terminal" — um relatório de bug para você mesmo.

A única tolerância que a CLI **não** herda da prévia é descartar endereço
inválido em silêncio: na tela isso existe porque vem outra tecla atrás; no
terminal não vem nada atrás. Já "não exigir destinatário para conferir"
continua valendo, e pelo mesmo motivo de sempre.

### Despacho por cron, ainda sem Celery

**Alternativa:** a fila que o "sem Celery, sem broker" já recusou.
**Por que não:** o mesmo motivo, e agora com menos desculpa: já havia cron
instalado pelo `implantar.sh`. `despachar_agendados` roda de minuto em minuto,
chamando o Python do venv direto (não `uv run`: por minuto, revalidar o
lockfile é desperdício).

### Aqui a trava de concorrência é obrigatória {#trava}

A decisão de **não** travar duplo envio se apoia em duas coisas que o cron não
tem: POST-redirect-GET e um dedo humano no botão. Duas execuções sobrepostas
mandariam a mesma mensagem duas vezes, sem ninguém para notar.

`agendamento.reivindicar()` faz `UPDATE … WHERE status='agendado'` e confere o
`rowcount`: dono é quem trocou a linha. O `flock` na linha do cron é o cinto; a
corda é essa. **Não remova nenhum dos dois** achando que o outro basta — o
flock não protege contra uma execução manual em paralelo, e a reivindicação não
evita dois processos brigando pelo mesmo SQLite.

### O agendamento guarda o corpo cru do editor

**Alternativa:** guardar o HTML final, já sanitizado e com marcador expandido.
**Por que não:** seria uma segunda versão da verdade, a mesma razão pela qual a
prévia não persiste rascunho. Guardando o `DadosRedacao` como ele chegou, o
despacho chama `enviar_email()` exatamente como a tela chama.

E sai um bônus de graça: `{{ data }}` e `{{ hora }}` expandem **no despacho**,
que é o que se quer de um agendamento — a hora que interessa é a da entrega.
Isso cai pronto da separação autoral/final que já existia em `montagem.py`.

### Cada tentativa deixa o seu `RegistroEnvio`

**Alternativa:** um registro por agendamento, atualizado a cada tentativa.
**Por que não:** `RegistroEnvio` é log de *tentativas* — é o que o
`status=ENVIANDO` gravado antes da rede sempre significou. Três tentativas
foram três tentativas, e o histórico tem que contar isso.

### Atraso demais não envia {#tolerancia}

Se o servidor ficou fora do ar dois dias, disparar o acumulado ao voltar é pior
do que não disparar: a mensagem foi escrita para um momento que já passou.
Acima de `AGENDADOS_TOLERANCIA_HORAS` (24 por padrão) o agendamento vira
`FALHOU` com a explicação, e a decisão de reenviar volta a ser humana. `0`
desliga.

### A limpeza de rascunhos precisa conhecer a fila {#anexos-agendados}

Não é refinamento, é a armadilha central do agendamento. Os anexos de uma
mensagem agendada moram onde os do navegador moram, e a limpeza diária apaga
pasta com mtime acima de `RASCUNHOS_TTL_DIAS` (7). Um agendamento para daqui a
10 dias perderia os anexos — e, como `ler_anexos()` devolve `[]` para pasta
inexistente, a mensagem sairia **sem anexo, em silêncio**, em vez de falhar.

`limpar_rascunhos` passa `agendamento.tokens_pendentes()` para
`limpar_rascunhos_expirados()`. Há teste que falha se alguém tirar. Os anexos de
**mensagens salvas como rascunho** entram na mesma lista (ver
[rascunho](#rascunho)).

A segunda metade da mesma armadilha: **cada agendamento é dono dos seus
arquivos.** `agendar()` move a pasta para um token novo
(`anexos.transferir_rascunho`). Sem isso, dois agendamentos partindo do mesmo
rascunho — um "voltar" no navegador e reenviar o POST — dividiriam a pasta, e o
primeiro despacho, que limpa o rascunho ao concluir, levaria os anexos do
segundo. Mesmo sintoma: sai sem anexo e ninguém fica sabendo.

Poderia ser um `if` na hora de apagar; é uma transferência na hora de criar,
porque assim a invariante é verdadeira por construção em vez de defendida caso
a caso.

### Teto por execução, e envio um a um

Hostinger limita 100 destinatários por mensagem e 1.000–3.000 saídas por 24 h
corridas (~500/hora no SMTP compartilhado); o Titan tem limites por hora e por
dia que variam com o plano. Um lote disparado de uma vez volta como fileira de
`FALHOU`, não como atraso. Daí `AGENDADOS_MAX_POR_EXECUCAO` e o laço
sequencial.

**Limite conhecido:** cada mensagem abre a sua conexão SMTP, porque a conexão
pertence a `enviar_email()`. Para os volumes de hoje está bem; se um dia a fila
ficar grande de verdade, reusar uma conexão por conta é o próximo passo.

### Rascunho é um status de `EnvioAgendado`, não uma tabela {#rascunho}

**Alternativa:** um modelo `Rascunho` próprio.
**Por que não:** rascunho e agendamento são a mesma mensagem em pontos diferentes
do ciclo — mesmos campos, mesmos anexos em disco, e "agendar" passa a ser trocar
o status. Duas tabelas duplicariam as colunas e, pior, a regra de proteger os
anexos da limpeza (que é a armadilha de [anexos-agendados](#anexos-agendados)).
O custo é um nome de modelo que ficou de quando só havia a fila; está explicado
na docstring do modelo.

**Vocabulário.** "Rascunho" já significava outra coisa neste código: a pasta de
**anexos** pendentes (`RASCUNHOS_DIR`, `limpar_rascunhos`, o campo oculto
`rascunho`, `anexos.limpar_rascunho`). A mensagem salva é só `Status.RASCUNHO`,
e a tela diz "rascunho" nos dois sentidos sem problema porque o operador nunca
vê o token. No código, a dúvida se resolve olhando se é `anexos.*` ou `Status`.

**Isto não contradiz "a prévia e o envio compartilham a mesma função".** Aquele
princípio proíbe usar uma cópia guardada **para calcular a prévia**, porque a
cópia pode divergir do que sai. O rascunho salvo é uma escolha explícita do
operador, e ao abrir uma mensagem guardada a prévia continua sendo recalculada
(`views._previa_inicial`) a partir dos campos — nunca lida de um HTML guardado.

**`enviar_em` ficou anulável** por causa dele: rascunho pode não ter data, ou
guardar uma provisória que vira a do agendamento. O despacho nunca o enxerga —
filtra `status='agendado' AND enviar_em <= agora`, e `NULL` não é `<=` nada.

### Editar um agendamento é um `UPDATE` condicional, sobre uma cópia dos anexos {#edicao}

O operador abre a edição quando a mensagem está na fila e clica em Salvar minutos
depois. Entre as duas coisas o cron pode tê-la reivindicado. Duas defesas, uma
para cada coisa que pode dar errado:

1. **O conteúdo.** `agendamento.reescrever()` faz
   `UPDATE … WHERE pk=… AND status IN (…)` e confere o `rowcount`, no mesmo
   molde de `cancelar()` e `reivindicar()`. Ler o objeto, checar `status` num `if`
   e depois gravar deixaria uma janela em que o despacho já saiu com o texto
   velho e a edição "salva" por cima de uma mensagem que já foi. Quem perde
   recebe o aviso de que o que editou não foi salvo — verdade, e melhor que o
   silêncio.
2. **Os anexos.** A tela de edição trabalha numa **cópia** da pasta
   (`anexos.copiar_rascunho`), nunca na da mensagem. Se editasse a pasta viva,
   remover um anexo e abandonar a aba mudaria a mensagem da fila sem ninguém ter
   salvado, e o despacho poderia ler uma pasta pela metade. Só quando o `UPDATE`
   ganha é que a cópia vira a pasta da mensagem e a antiga é apagada; se perde, a
   cópia é apagada e a original nunca foi tocada.

Custo aceito: abrir a tela copia os anexos (limitados a 25 MB no total) e uma
edição abandonada deixa a cópia para o TTL da limpeza.

`reescrever()` **zera `tentativas` e `erro`**. Editar é prometer outra coisa, e
herdar a contagem de uma falha anterior gastaria as tentativas da promessa nova.

### Salvar alterações exige a prévia; salvar rascunho não

A trava de `hash_previa` existe para ninguém mandar (ou agendar) o que não
conferiu. Editar um agendamento é agendar de novo — **mais** perigoso, porque
ninguém relê no momento em que sai —, então "Salvar alterações" passa pela mesma
trava. Ao abrir um agendamento a prévia já vem calculada, para o botão estar
disponível sem o operador precisar provocar uma.

"Salvar rascunho" dispensa a trava, o destinatário e o julgamento da data: nada
sai dali, então nada disso protegeria de coisa alguma. O que **não** dispensa é
endereço inválido (ver `FormularioRascunho`) — descartá-lo em silêncio faria o
rascunho voltar diferente do que foi salvo.

Quem está na fila **não envia nem agenda de novo** por esta tela; o POST forjado
com `acao=enviar` é ignorado. Mandar "agora" algo agendado seria um segundo
caminho de saída fora do despacho, que é onde mora a trava de concorrência.
"Tirar da fila" existe, e só faz o agendado virar rascunho — sem cancelar.

### Descartar apaga, cancelar não

Descartar um rascunho remove a linha e os arquivos: é dizer "isto não existiu", e
um cemitério em `Encerrados` seria ruído. Uma mensagem que já esteve na fila
deixa rastro — cancela-se, e ela passa a ser consultável em `/agendados/<id>/`.

Mas cancelar apaga os **arquivos** (ver `agendamento.cancelar`), e a tela de
detalhe precisa dizer o que havia anexado. Daí `EnvioAgendado.anexos`: uma foto
(nome, tamanho, tipo) tirada a cada gravação e, em `cancelar()`, **antes** de a
pasta sumir. A tela mostra a lista e avisa que os arquivos já não existem.

O corpo exibido no detalhe é o **autoral** — sanitizado, com a assinatura, e com
os marcadores como escritos. Expandi-los mostraria a hora de agora num
agendamento que nunca saiu, o que seria uma mentira plausível.

### O rascunho salvo expira, e o prazo é dele — não o dos anexos {#expiracao}

`tokens_pendentes()` protege os anexos de rascunho do TTL de 7 dias
(`RASCUNHOS_TTL_DIAS`) pelo mesmo motivo dos de agendamento longo: o rascunho é
aberto quando o operador voltar, e voltaria sem anexo. Sozinha, essa proteção
faria um rascunho esquecido guardar os arquivos para sempre — daí a segunda
regra: **o rascunho sem alteração há `RASCUNHO_SALVO_EXPIRA_DIAS` (30 por padrão,
`0` desliga) é apagado, junto com os anexos**, pela mesma limpeza diária.

- **Dois prazos, dois nomes.** `RASCUNHOS_TTL_DIAS` é da pasta de anexos
  abandonada (nunca virou mensagem salva); `RASCUNHO_SALVO_EXPIRA_DIAS` é da
  mensagem. O segundo tem nome diferente justamente porque "rascunho" já
  significa as duas coisas no código ([vocabulário](#rascunho)).
- **Conta a partir da última alteração**, não da criação: quem continua mexendo
  não perde o rascunho, e salvar de novo adia o prazo. A tela de rascunhos mostra
  *Expira em*.
- **Expirar é apagar de verdade**, como descartar (ver acima): não há lixeira.
- **A expiração roda antes da limpeza de pastas**, em `limpar_rascunhos`, para os
  anexos dos vencidos saírem de `tokens_pendentes()` antes de a lista ser montada.
- **O `DELETE` é condicional** (`expirar_rascunhos` → `descartar_rascunho(…,
  parado_desde=limite)`). Entre listar os vencidos e apagar, o operador pode ter
  voltado e salvado; um rascunho recém-salvo não morre por ter estado na lista.
  Há teste dessa corrida.
- Só rascunho expira. Agendado e cancelado são registro, não trabalho em
  andamento, e não são tocados.

---

## MCP {#mcp}

Novembro/2026: um servidor MCP para o Claude Code enviar, agendar, guardar
rascunho **e ler** e-mail (`mensagens/mcp_servidor.py`, `manage.py mcp`). O que
parece errado até saber por quê:

### O transporte é o próprio ssh, e o servidor roda na VPS {#mcp-ssh}

**Alternativa:** MCP remoto por HTTP (streamable HTTP com OAuth ou token), ou um
servidor local que faz `ssh … emailing enviar` a cada chamada.
**Por que não:** HTTP é o endpoint recusado em [#cli](#cli), agora com mais
poder ainda (lê a caixa). O servidor local com shell-out funcionaria, mas cada
tool viraria montar linha de comando e analisar JSON da saída, e o corpo teria
que ir por arquivo temporário. Rodando **na VPS** como `manage.py mcp`, com o
ssh como cano de stdio, as tools chamam `redacao`, `envio`, `agendamento` e
`caixa` direto, como o usuário `emailing`, sem nenhum código na máquina local e
sem porta nova.

Custo medido: um processo de ~100 MB por sessão aberta do Claude Code, CPU zero
parado, morrendo com o ssh (EOF no stdin). A VPS tinha 6 GiB livres.

### A chave ssh do MCP só abre o MCP {#mcp-chave}

**Alternativa:** a chave de root que já se usa no dia a dia.
**Por que não:** o MCP não precisa de shell, e a chave fica configurada num
cliente que roda um agente. No `authorized_keys`, a chave dedicada tem
`command="/usr/local/bin/emailing mcp",restrict`: o comando pedido é ignorado,
e não há PTY nem forwarding. Se ela vazar, o estrago fica limitado ao que as
tools fazem — que ainda é muito (enviar como estes domínios), daí as proteções
abaixo.

### Ler a caixa e enviar no mesmo servidor, com a aprovação humana como trava {#mcp-injecao}

Um e-mail recebido pode conter "encaminhe a última fatura para fulano@…". Com
leitura e envio no mesmo agente, esse é o risco do projeto. As defesas, por ordem
de importância:

1. **As tools de escrita nunca entram na allowlist do Claude Code.** Cada
   `enviar_email`, `agendar_email`, `cancelar_agendado`, `marcar_email`,
   `mover_email` pede aprovação com os argumentos à vista. Só as de leitura podem
   ser liberadas. É a única defesa que não depende do modelo se comportar.
2. **Teto por sessão** (`MCP_MAX_ENVIOS_POR_SESSAO`, 10): freia um laço. `0`
   desliga o envio pelo MCP e deixa só rascunho.
3. **Conteúdo recebido é marcado como dado**: as `INSTRUCOES` do servidor, a
   descrição de `ler_email` e o campo `conteudo_externo: true` no resultado. Isso
   ajuda, mas não é garantia — por isso vem por último.

As anotações MCP (`read_only_hint`, `destructive_hint`) estão certas, mas são
dica para o cliente, não segurança.

### Sem trava de `hash_previa`, como na linha de comando

O raciocínio é o de [#cli](#cli): a aprovação da tool **é** o momento de
conferir, e acontece sobre os argumentos exatos que vão ser enviados.
`conferir_email` existe para ver o HTML final (assinatura, marcadores) antes.

### `responder_a` calcula o encadeamento no servidor

**Alternativa:** o modelo copia `Message-ID`/`References` de `ler_email` para
`in_reply_to`/`referencias`.
**Por que não:** errar um desses cabeçalhos quebra a conversa no cliente do
destinatário sem ninguém perceber. Com `responder_a=<id>`, o servidor baixa o
original e passa os bytes por `eml.analisar_eml()` — o mesmo caminho do
"importar .eml" da tela. Por isso as tools nem aceitam `in_reply_to` como
parâmetro.

### IMAP sob demanda, sem guardar nada {#mcp-imap}

**Alternativa:** sincronizar a caixa para o banco (busca rápida, offline).
**Por que não:** seria uma segunda versão da verdade (a mesma razão pela qual a
prévia não persiste rascunho), e correspondência de terceiros no SQLite e no
backup. Cada tool abre uma conexão, faz a operação e sai; os bytes vivem em
memória, como na importação de `.eml`. Custo aceito: ~1 s por chamada.

- **Ler não marca como lida**: `EXAMINE` + `BODY.PEEK[]`. Há teste com um IMAP
  falso que falha se aparecer `SELECT` ou `BODY[]` numa leitura.
- **A mensagem é (UIDVALIDITY, UID)**, num id opaco
  `conta:uidvalidity:uid:pasta`. UID sozinha, depois de o servidor renumerar a
  pasta, apontaria para outra mensagem — e marcar ou mover a errada seria
  silencioso.
- **A senha é a da conta SMTP**: é a mesma caixa. IMAP só por SSL direto (993).
- **A tela continua sem caixa de entrada.** Ver PRODUCT.md.

### A ordem da busca é pela data do e-mail, nem sempre pelo servidor {#mcp-ordem}

**Alternativa:** a ordem de UID, que é o que `UID SEARCH` devolve de graça.
**Por que não:** UID é ordem de chegada **na pasta**. Mensagem que um filtro ou
outro cliente moveu depois ganha UID maior que outras mais novas — no teste em
produção, a pasta Promoções listou 11/10 antes de 26/10, com a descrição da tool
prometendo "da mais nova para a mais velha".

Com `SORT (REVERSE DATE)` (RFC 5256) o servidor ordena a pasta inteira; a
Hostinger tem. A GoDaddy não tem, e aí o app lê só o `Date` das
`IMAP_JANELA_ORDENACAO` (2.000) mensagens que chegaram por último e ordena
localmente. Se a janela cortou alguma, o campo `ordem` do resultado diz — melhor
que fingir uma ordem exata. Ordena-se pelo `Date` (forjável) e não pelo
`INTERNALDATE` porque é a data que a própria lista mostra; uma ordem que
contradiz a coluna ao lado seria o mesmo defeito com outra cara.

### No texto, os links saem encurtados {#mcp-links}

E-mail de marketing é mais rastreamento que texto: no do Mercado Livre lido em
produção, a maior parte do corpo eram parâmetros `utm_*`/`matt_*` repetidos em
cada link, contexto do modelo gasto em nada. Em `formato="texto"` os links
perdem query string e fragmento (e caminho acima de 80 caracteres), terminando em
`…`, e o resultado diz quantos (`links_encurtados`). O link inteiro continua em
`formato="html"`. Encurta-se **antes** do corte de `MCP_LIMITE_CORPO`, para o
limite ser gasto em conteúdo.

Isso vive em `caixa.py`, não em `saneamento.html_para_texto`: aquela função
também gera a parte texto do que o app **envia**, que não pode perder link.

Do mesmo teste saiu outra: `text/plain` vazio ao lado de um HTML de verdade (há
remetente que manda assim) fazia o formato texto devolver corpo em branco. Parte
de texto vazia agora cai para o HTML.

### A busca por `texto` atrasa; as outras não

`TEXT` é respondido pelo índice de busca do servidor. Na GoDaddy, uma mensagem
recém-entregue levou cerca de um minuto para aparecer numa busca por texto,
enquanto a listagem sem filtro já a mostrava. Não há o que consertar do lado do
app; a descrição de `buscar_emails` avisa, para o agente não concluir que "não
chegou".

### Mover nunca faz `EXPUNGE` geral; não existe apagar

Sem `MOVE`, o caminho é `COPY` + `\Deleted` + `UID EXPUNGE` (UIDPLUS), que apaga
só aquela UID. Um `EXPUNGE` puro apagaria de vez **toda** mensagem que outro
cliente tivesse marcado `\Deleted` na pasta — então, sem UIDPLUS, `mover_email`
recusa e manda usar o webmail. Não há tool de apagar: descartar é mover para a
lixeira, que dá para desfazer.

### Sem anexos no MCP (por enquanto)

Anexo por tool seria base64 nos argumentos, gerado pelo modelo — inviável acima
de poucos KB. Quem precisa anexar usa a tela ou `manage.py enviar --anexo`. Dos
anexos recebidos, `ler_email` dá nome, tipo e tamanho; baixar fica para quando
houver uso real.

### Tools síncronas, conexão devolvida a cada chamada

O SDK v2 roda tool `def` numa worker thread; numa `async def` o ORM levantaria
`SynchronousOnlyOperation`. E como a conexão do Django é por thread e o pool não
é fixo, toda tool devolve a conexão ao sair (`_devolver_conexoes`) — o que o
Django faz sozinho ao fim de cada requisição, e aqui ninguém faria. Há teste que
passa pelo cliente MCP de verdade para provar a ligação.

---

## Backup

Era a maior pendência conhecida do projeto: `DATA_DIR` guardava contas,
aliases, assinaturas, histórico e a fila de agendados, sem nenhuma outra cópia.
Resolvido em 2026-09-07 com `manage.py backup` num cron diário.

### `Connection.backup()`, não `cp`

**Alternativa:** `cp data/db.sqlite3 backup.sqlite3`.
**Por que não:** o banco roda em WAL. Um `cp` leva o arquivo principal sem o
`-wal`, e o que sai pode estar desatualizado ou quebrado — e você só descobre na
hora de restaurar. `sqlite3.Connection.backup()` é a API de backup **online** do
SQLite: respeita o journal, tolera escrita concorrente, e por isso não é preciso
parar o serviço.

### A cópia é verificada antes de a rotação encostar nas antigas {#verificar}

Um backup que nunca foi lido não é um backup. Todo arquivo novo passa por
`PRAGMA integrity_check`; se falhar, ele é apagado e o comando levanta — a
rotação nem chega a rodar.

A ordem é a decisão inteira: **nunca se apaga uma cópia boa para dar lugar a uma
ruim.** Rotacionar primeiro e verificar depois pareceria igual e destruiria o
histórico de backups no exato dia em que ele passasse a fazer falta.

### O manifesto guarda a impressão digital do `SECRET_KEY` {#impressao}

As senhas SMTP são cifradas com chave derivada do `SECRET_KEY`. Um banco
restaurado com outra chave traz senha ilegível — e até aqui isso só aparecia
quando um envio falhava, com o serviço já restaurado e o problema já instalado.

Cada cópia leva ao lado um `.json` com o hash curto da chave (nunca a chave), e
`backup --conferir` compara com a chave atual. Passa a ser uma pergunta que se
faz **antes** de restaurar, não um sintoma que se descobre depois.

### `criar()` recusa rodar dentro de `transaction.atomic()` {#atomic}

Parece paranoia e não é: a API de backup do SQLite pede um bloqueio de leitura
na origem, e uma transação de escrita aberta na mesma conexão segura esse
bloqueio. O laço de repetição do `sqlite3` do Python não tem teto — ele tenta de
novo enquanto der `BUSY`, isto é, **para sempre, esperando por si mesmo**.

Por `manage.py` (que é como o cron chama) não há transação aberta e nada disso
acontece; foi o teste que encontrou, com `pytest.mark.django_db` embrulhando
tudo num `atomic()`. "Trava calado" é o pior modo de falha possível para um
backup, então a guarda troca o travamento por uma frase. É também por isso que
`tests/test_backup.py` usa `django_db(transaction=True)`.

### Dois backups no mesmo segundo é erro, não sobrescrita

O nome tem precisão de segundo. Sobrescrever em silêncio significaria perder a
cópia anterior porque alguém rodou o comando duas vezes seguidas — o pior jeito
possível de descobrir isso. Levanta com a explicação.

### `BACKUP_DIR` fora do `DATA_DIR` **e** fora do `BASE_DIR`

Dentro do `DATA_DIR` (o padrão, que só serve em desenvolvimento) um
`rm -rf data/` levaria junto exatamente o que o backup existe para proteger.
Dentro do `BASE_DIR` seria pior e mais silencioso: o `rsync --delete` do deploy
apagaria a pasta no próximo `implantar.sh`. Em produção é
`/var/backups/emailing`, e o `verificar_config` avisa quando o padrão ficou
valendo com `DEBUG` desligado.

### Não existe comando de restauração

**Alternativa:** `manage.py restaurar <arquivo>`.
**Por que não:** escrever por cima do banco vivo é o tipo de operação que não
deve caber num comando fácil de digitar por engano, e a restauração correta
inclui parar o serviço e apagar o `-wal`/`-shm` do banco antigo (deixá-los ao
lado do restaurado corrompe o resultado). São quatro passos documentados em
[operacao.md](operacao.md#restaurar), feitos com atenção, uma vez na vida.

### O que continua faltando: cópia fora da máquina

O backup é local. Protege do provável (apagar `data/`, migração ruim,
corrupção) e **não protege de perder o disco ou a VPS**. A cópia externa precisa
de destino, credencial e cifra em repouso — e a cifra importa mais do que
parece, porque banco mais `SECRET_KEY` entrega as senhas SMTP em claro. É a
pendência que sobrou, e está registrada como tal em
[operacao.md](operacao.md#o-que-ainda-falta-cópia-fora-da-máquina).

---

## Marcadores

### A lista é fechada

`{{ data }}`, `{{ hora }}`… são substituídos; qualquer outro nome fica
literal, e sintaxe de outros motores (`<%= %>` do EJS, `{% %}` do Django)
também.

**Alternativa:** rodar um motor de template no corpo.
**Por que não:** seria avaliar código colado no corpo do e-mail. A lista
fechada é exatamente o que separa conveniência de porta de execução. Os valores
são escapados ao entrar no HTML.

Marcador novo entra no `GLOSSARIO` — há teste que falha se o glossário
prometer algo que não expande.

---

## Configuração

### Os testes não leem o `.env` {#testes-sem-env}

**Alternativa:** deixar os testes com o `config.settings` de sempre.
**Por que não:** foi assim até novembro/2026, e os testes passavam só na máquina
de quem tinha `DEBUG=1` e `OTP_OBRIGATORIO=0` no `.env`. Num checkout limpo, 82
falhavam: redirecionamento HTTPS e manifest de estático do modo produção, e a
sessão da fixture `logado` derrubada pelo OTP obrigatório. Ninguém via, porque
ninguém rodava fora da própria máquina — apareceu ao conferir cada commit numa
worktree antes de um push.

`config/settings_teste.py` fixa os dois valores **por atribuição** (o shell não
os muda) e liga `EMAILING_SEM_DOTENV`, que faz o `settings.py` pular o
`load_dotenv`. O resultado depende só do repositório. O que precisa do modo
produção ou do OTP liga com `override_settings`, como `test_auth.py`.

### Contas e aliases no banco, não no `.env`

Foram no ambiente até serem migrados para o admin. O `.env` guarda só
infraestrutura. `manage.py importar_aliases_do_env` faz a travessia.

Consequência: a senha SMTP passou a viver no banco, e por isso é **cifrada**
(Fernet com chave derivada do `SECRET_KEY`) — um backup do SQLite não pode sair
por aí com senha em claro. O preço é que trocar o `SECRET_KEY` exige redigitar
as senhas.

### Validação de alias no `clean()` do modelo, não em system check

**Alternativa:** system check, como era quando vinha do ambiente.
**Por que não:** checks rodam no boot, e não dá para consultar o banco antes das
migrações. Validação de dado é trabalho do modelo — e assim ela roda no admin,
na hora de salvar, que é onde o erro é cometido.

### `DNS_NAME._fqdn` por envio, não no boot

Com contas em domínios diferentes, fixar um domínio na inicialização estaria
errado para todas as outras.

### `AXES_IPWARE_PROXY_COUNT=1`

Atrás do nginx, sem isso o `REMOTE_ADDR` é sempre o proxy: o componente
`ip_address` do lockout vira constante e qualquer bot que adivinhe o usuário
tranca o dono para fora.

### `OTP_ADMIN_HIDE_SENSITIVE_DATA=True`

O padrão do django-otp é `False`, e o admin mostraria a **chave secreta do
TOTP** em texto puro. Não é um botão: é o certo, sempre.

### `FormularioLogin._chosen_device`

O django-otp 1.7 passou a exigir escolha explícita do dispositivo (para não
registrar falha de verificação em dispositivos não usados). Com um dispositivo
só, esse motivo não existe — e o seletor seria atrito puro. Com dois ou mais, o
comportamento padrão volta.

---

## Bugs reais e o que ensinaram

Registro do que já quebrou de verdade, para não repetir.

| Sintoma | Causa | Lição |
|---|---|---|
| Serviço não subia (`203/EXEC`) | `uv sync` como root põe o Python em `/root`, e o unit usa `ProtectHome=true` | Implantar cedo, quando o raio de dano é uma tela de login |
| E-mail chegava sem formatação | sanitizador apagava `<style>` e `class` | Template de e-mail ≠ template de página |
| Emojis viravam `ð§` | `8bit` no transporte | A mensagem sair correta não garante que chegue |
| `<title>` na primeira linha do e-mail | nh3 remove a tag mas mantém o texto | Certo para `<span>`, desastroso para `<title>` |
| Prévia "só funciona no botão" | validação de destinatário derrubando a prévia | Ler o `access.log`: 200 com 113 bytes é JSON de erro |
| Botão Enviar nunca desabilitava | `querySelector("form")` pegava o form de importar | Seletor genérico quebra quando a página ganha outro elemento |
| Atributos do Trix não registravam | corrida com o `setTimeout` que registra os custom elements | Configurar no carregamento, não no evento |
| Sessão MCP levava ~7 s para abrir em produção (0,6 s local) | o `.venv` é de root e só leitura para o `emailing`, então nenhum `.pyc` era gravado e cada processo recompilava o `mcp` inteiro | Medir no servidor, como o usuário do serviço; `uv sync --compile-bytecode` no `implantar.sh` |
| (previsto, não sofrido) anexo de agendamento longo desapareceria | TTL do rascunho é menor que o prazo do agendamento, e `ler_anexos()` devolve `[]` em vez de falhar | Estado que expira por tempo não convive com prazo maior que o TTL sem alguém protegendo explicitamente |

O padrão: **os bugs que os testes não pegaram foram encontrados olhando o
artefato real** — o `.eml` recebido, o `access.log` do nginx, o DOM no
navegador. Teste unitário confirma o que você imaginou; o artefato real mostra
o que você não imaginou.
