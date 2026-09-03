# Emailing

Aplicação web de usuário único para redigir e enviar e-mail por **alias** do
domínio `leonardocosta.dev`. O Titan Mail cobra à parte pelo envio por alias,
mas o SMTP dele aceita `From:` de qualquer endereço do mesmo domínio quando
autenticado com uma caixa real — este app transforma isso numa ferramenta com
editor, assinatura, pré-visualização, anexos e resposta a threads existentes.

Roda em `https://emailing.leonardocosta.dev`.

## Desenvolvimento

```bash
uv sync
cp .env.example .env      # preencha SMTP_USER, SMTP_PASSWORD e os aliases
uv run manage.py migrate
uv run manage.py verificar_config    # confere aliases, servidor e assinaturas
uv run manage.py createsuperuser
uv run manage.py runserver
```

Em desenvolvimento deixe `DEBUG="1"` e `OTP_OBRIGATORIO="0"` — assim o login
não exige segundo fator num banco recém-criado.

Qualidade:

```bash
uv run ruff check .
uv run pytest
```

## Configuração

Tudo vem de variável de ambiente; `.env.example` lista cada uma com descrição.
Em produção quem injeta é o `EnvironmentFile=` do systemd, e é por isso que
**não existe valor multilinha**: a assinatura HTML de cada alias mora num
arquivo cujo caminho é que vai na variável.

### Cadastrar um alias

```dotenv
ALIASES="financeiro,contato"
ALIAS_FINANCEIRO_ADDRESS="financeiro@leonardocosta.dev"
ALIAS_FINANCEIRO_NAME="Leonardo Costa"
```

O `<SLUG>` é o nome do alias em maiúsculas com todo caractere não-alfanumérico
virando `_` (`nota-fiscal` → `ALIAS_NOTA_FISCAL_*`). Se ficar em dúvida, rode
`manage.py verificar_config`: ele imprime o prefixo exato de cada alias.

A assinatura vai em `<DATA_DIR>/assinaturas/<slug>.html` e é lida do disco a
cada pré-visualização — editar o arquivo não exige reiniciar o serviço.

`ALIAS_ALLOWED_DOMAINS` é a trava importante: um `From:` fora do domínio
autenticado não fica alinhado ao DMARC e a mensagem vai para spam, então o app
se recusa a subir com um alias de domínio de fora.

### Segundo fator

```bash
uv run manage.py criar_totp leonardo
```

Mostra o QR no terminal. Com `OTP_OBRIGATORIO="1"`, uma sessão autenticada sem
segundo fator verificado é encerrada — não existe estado intermediário.

## Implantação

VPS Contabo (`ssh leonardo_contabo`), ao lado do Pholium: nginx no host, TLS
pelo certbot, processo sob systemd. Não há Docker nessa máquina.

- Código em `/var/www/emailing`, `.env` na raiz com modo `0600`.
- `uv sync --frozen --no-dev && manage.py migrate && manage.py collectstatic`.
- Unit systemd com `EnvironmentFile=/var/www/emailing/.env`, usuário de sistema
  próprio (não `root`: este processo guarda credencial de SMTP) e
  `gunicorn config.wsgi -b 127.0.0.1:8010`.
- vhost nginx com `proxy_pass http://127.0.0.1:8010`, os `X-Forwarded-*` e
  `client_max_body_size 25m` (senão o anexo grande morre com 413 antes de
  chegar ao Django). O estático é servido pelo whitenoise — não crie um
  `location /static/`.
- `certbot --nginx -d emailing.leonardocosta.dev`. O DNS já resolve por
  wildcard, não há registro a criar.
- **Sempre `nginx -t` antes do reload**: um erro de sintaxe derruba
  `api.leonardocosta.dev` e `leonardocosta.dev` junto.

## Estado

`DATA_DIR` (`data/` em dev, `/var/www/emailing/data` em produção) guarda o
banco SQLite, as assinaturas e os anexos ainda não enviados. **Apagar esse
diretório apaga o histórico de envios e as assinaturas** — não há outra cópia.
