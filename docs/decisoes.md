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

MCP entra na conversa só se um dia o cliente não for o terminal. Aí a forma
importa: stdio local fazendo shell-out para o ssh é aceitável; MCP remoto por
HTTP traz de volta exatamente o endpoint recusado acima.

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
tela. Duas validações divergem, e o sintoma seria "funciona no navegador e não
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
`limpar_rascunhos_expirados()`. Há teste que falha se alguém tirar.

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
| (previsto, não sofrido) anexo de agendamento longo desapareceria | TTL do rascunho é menor que o prazo do agendamento, e `ler_anexos()` devolve `[]` em vez de falhar | Estado que expira por tempo não convive com prazo maior que o TTL sem alguém protegendo explicitamente |

O padrão: **os bugs que os testes não pegaram foram encontrados olhando o
artefato real** — o `.eml` recebido, o `access.log` do nginx, o DOM no
navegador. Teste unitário confirma o que você imaginou; o artefato real mostra
o que você não imaginou.
