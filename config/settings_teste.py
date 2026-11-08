"""Configuração dos testes: os padrões do código, mais o modo de desenvolvimento.

Os testes rodavam com o que estivesse no `.env` de quem os rodava, e dependiam
de dois valores que só existem lá: `DEBUG=1` e `OTP_OBRIGATORIO=0`. Num checkout
limpo (CI, outra máquina, uma worktree) 82 deles falhavam, por três motivos que
nada tinham a ver com o código testado:

- sem `DEBUG`, o `SECURE_SSL_REDIRECT` respondia 301 a toda requisição do
  cliente de teste;
- sem `DEBUG`, o estático usa o manifest do whitenoise, que não existe sem
  `collectstatic`;
- com o OTP obrigatório (o padrão), a sessão aberta pela fixture `logado` — que
  entra com o OTP desligado — era derrubada no request seguinte.

Aqui os dois valores são **fixados** (não `setdefault`: nem o shell nem o `.env`
os mudam) e o `.env` não é lido, então o resultado dos testes depende só do
repositório. Teste que exercita o OTP ou o modo produção liga o que precisa com
`override_settings`, como `tests/test_auth.py` já faz.
"""

import os

os.environ["DEBUG"] = "1"
os.environ["OTP_OBRIGATORIO"] = "0"
os.environ["EMAILING_SEM_DOTENV"] = "1"

from .settings import *  # noqa: E402, F403
