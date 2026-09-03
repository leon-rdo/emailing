# CLAUDE.md

Orientação para o Claude Code trabalhar neste repositório.

## O que é

App Django de usuário único para enviar e-mail por alias do domínio
`leonardocosta.dev`, hospedado em `emailing.leonardocosta.dev`. **Não tem
relação nenhuma com o Pholium** — só compartilha a VPS.

Tudo — código, comentários, mensagens de UI, docs — em **português**.

## Stack

Django 5.2 renderizado no servidor, **sem DRF** (não existe um segundo cliente;
a UI são três formulários). SQLite em WAL. uv + `pyproject.toml`. ruff.
gunicorn + whitenoise atrás do nginx. Sem npm, sem bundler, sem framework de
CSS: um `estilo.css` escrito à mão e JS inline com nonce de CSP.

Comandos: `uv sync`, `uv run manage.py <cmd>`, `uv run ruff check .`,
`uv run pytest`.

## Arquitetura

- `config/` — `settings.py` (arquivo único, tudo do ambiente), `urls.py`,
  `middleware.py` (nonce de CSP, cabeçalhos, exigência de OTP), `hashers.py`.
- `mensagens/` — o app único.
  - `aliases.py` monta a dataclass congelada `Alias` a partir de `ALIASES` e
    `ALIAS_<SLUG>_*`. `montar_aliases()` nunca levanta exceção (devolve
    `(aliases, erros)`) — é o que permite ao `verificar_config` relatar todos os
    problemas de uma vez; `carregar_aliases()` é a versão em cache que levanta.
  - `checks.py` transforma esses erros em system checks. É por isso que
    `verificar_config` declara `requires_system_checks = []`: ele precisa rodar
    justamente quando a configuração está quebrada.
  - `assinaturas.py` lê o HTML da assinatura **do disco a cada render**, de
    propósito: editar o arquivo por ssh reflete na próxima prévia sem restart.
  - `apps.py:ready()` fixa `DNS_NAME._fqdn`, que conserta de uma vez o domínio
    do `Message-ID` gerado pelo Django e o nome usado no `EHLO` do SMTP.
  - `montagem.py` monta a `EmailMultiAlternatives` (função pura). `envio.py`
    grava o `RegistroEnvio` com `status=ENVIANDO` **antes** da chamada SMTP,
    manda de verdade, e atualiza o status — nunca levanta.
  - `anexos.py` grava/lê/remove arquivos de rascunho em `RASCUNHOS_DIR/<token>`;
    o token é um campo oculto do formulário, não sessão nem modelo.
  - `eml.py` faz o parsing de `.eml`/`.txt` e a reconstrução de `References`
    (`referencias_para_resposta`) — reaproveitada também pelo fluxo "responder a
    algo que eu enviei" em `views.redigir`, para as duas rotas terem a mesma
    lógica de dedup/teto de 20 em vez de duas implementações divergentes.

## Convenções que não devem ser "corrigidas"

- **Nomes de domínio em português, identificadores de protocolo em inglês.**
  `criado_em`, `remetente`, `assunto`, `erro` — mas `message_id` e
  `in_reply_to`, porque são nomes de cabeçalho da RFC 5322.
- **A assinatura não passa pelo sanitizador.** O nh3 limpa o corpo do editor e a
  citação do original; a assinatura é concatenada literal. Ela é conteúdo do
  operador, num arquivo que só quem tem ssh escreve — sanitizá-la não protege de
  nada e destrói o layout em `<table>` e os estilos inline. O sanitizador do
  corpo existe antes de tudo como **normalizador de entregabilidade** (mata
  `<o:p>`, `mso-*` e sopa de classes vinda do Word); segurança é bônus.
- **A prévia não persiste rascunho.** `montar_email()` é função pura e os dois
  botões (`acao=previa` e `acao=enviar`) chamam a mesma função sobre o mesmo
  POST — WYSIWYG por construção, não por fidelidade de armazenamento. O campo
  `hash_previa` fecha o caso de editar depois de pré-visualizar.
- **`SMTP_TIMEOUT` não é opcional.** O padrão do Django é `None`, que bloqueia a
  thread para sempre; com workers `gthread` o `--timeout` do gunicorn não mata
  thread bloqueada. É esse timeout que torna Celery desnecessário aqui.
- **`AXES_IPWARE_PROXY_COUNT=1` em produção.** Sem isso o `REMOTE_ADDR` é sempre
  o nginx, o componente `ip_address` do lockout vira constante e qualquer bot que
  adivinhe o usuário tranca o dono para fora.
- **`FormularioLogin._chosen_device`** existe porque o django-otp 1.7 passou a
  exigir escolha explícita do dispositivo. Com um dispositivo só, o motivo da
  mudança (estrangular dispositivos não usados) não se aplica.
- **Duplo envio não tem trava no servidor, de propósito.** POST-redirect-GET
  tira a URL de envio da barra de endereço assim que termina — um F5 de
  verdade reemite GET. O que sobra (dois cliques quase simultâneos) é
  resolvido desabilitando o botão no clique, no navegador (`redigir.html`).
  Não existe campo nem migração extra para isso — o custo não se paga para
  essa janela de tempo.
- **A importação de `.eml` nunca toca o disco.** `views.importar_eml` força
  `MemoryFileUploadHandler` na view externa (`@csrf_exempt`), antes de
  qualquer leitura de `request.POST` — inclusive a que o `@csrf_protect` da
  view interna faz sozinho para achar o token do CSRF. Mesmo padrão do
  `gloryrics`, pelo mesmo motivo: a correspondência importada é de terceiros.
  O resultado do parsing vai para `request.session` e é lido uma única vez
  (`session.pop`) por `views.redigir` — não é um `Rascunho` persistido.

## Estado

`DATA_DIR` guarda o banco SQLite, as assinaturas e os anexos de rascunho.
**APAGAR `data/` APAGA O HISTÓRICO DE ENVIOS E AS ASSINATURAS.** Não há backup
automático — ver a etapa opcional de `backup_sqlite` no plano.

## Onde roda

VPS Contabo `203.0.113.10` (`ssh leonardo_contabo`), a mesma do Pholium
(`api.leonardocosta.dev`) e do site Nuxt. nginx no host + certbot, processos sob
systemd em `127.0.0.1` (Pholium na 8000, Nuxt na 3000, este na 8010).
**Não há Docker nessa máquina.**
