"""Configuração do Emailing.

Tudo vem do ambiente. Em produção quem injeta é o `EnvironmentFile` do systemd;
em desenvolvimento o python-dotenv lê o `.env` da raiz do projeto.

Atenção ao formato: `EnvironmentFile` do systemd NÃO suporta valor multilinha.
Por isso a assinatura HTML de cada alias mora num arquivo cujo caminho é que vai
na variável de ambiente — ver `mensagens/assinaturas.py`.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Helpers de leitura do ambiente
# ---------------------------------------------------------------------------

_VERDADEIROS = {"1", "true", "yes", "on", "sim"}


def env_bool(nome: str, padrao: bool = False) -> bool:
    bruto = os.environ.get(nome, "").strip().lower()
    return bruto in _VERDADEIROS if bruto else padrao


def env_int(nome: str, padrao: int) -> int:
    bruto = os.environ.get(nome, "").strip()
    return int(bruto) if bruto else padrao


def env_lista(nome: str, padrao: str = "") -> list[str]:
    return [x.strip() for x in os.environ.get(nome, padrao).split(",") if x.strip()]


# ---------------------------------------------------------------------------
# Básico
# ---------------------------------------------------------------------------

DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "chave-insegura-apenas-para-desenvolvimento"
    else:
        raise ImproperlyConfigured("SECRET_KEY é obrigatória quando DEBUG está desligado.")

ALLOWED_HOSTS = env_lista("ALLOWED_HOSTS", "localhost,127.0.0.1")

# Vazia → deriva https://<host> de cada host que não seja local.
CSRF_TRUSTED_ORIGINS = env_lista("CSRF_TRUSTED_ORIGINS") or [
    f"https://{h}" for h in ALLOWED_HOSTS if h not in {"localhost", "127.0.0.1", "*", "[::1]"}
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Uma língua só, para sempre. Não vale uma variável de ambiente.
LANGUAGE_CODE = "pt-br"
TIME_ZONE = os.environ.get("TIME_ZONE", "America/Belem")
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Diretórios de estado (fora da árvore de código)
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
RASCUNHOS_DIR = Path(os.environ.get("RASCUNHOS_DIR", DATA_DIR / "rascunhos"))

# As assinaturas já moraram aqui, uma por arquivo; hoje vivem no próprio alias,
# no banco. O diretório continua sendo criado só porque o
# `importar_aliases_do_env` ainda lê dele na migração.
SIGNATURES_DIR = Path(os.environ.get("SIGNATURES_DIR", DATA_DIR / "assinaturas"))

for _dir in (DATA_DIR, SIGNATURES_DIR, RASCUNHOS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Apps e middleware
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "axes",
    "mensagens",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "config.middleware.CabecalhosSegurancaMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # OTPMiddleware precisa vir depois da autenticação e antes de qualquer
    # coisa que consulte request.user.is_verified().
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Depois do MessageMiddleware porque usa messages.error().
    "config.middleware.ExigirVerificacaoOTPMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # AxesMiddleware tem que ser o último.
    "axes.middleware.AxesMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "mensagens.contexto.navegacao",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Banco — SQLite com WAL
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DATA_DIR / "db.sqlite3",
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;",
            # Sem IMMEDIATE aparece o clássico "database is locked" quando uma
            # transação que começou lendo tenta escrever.
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }
}


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    # Precisa vir primeiro: corta a tentativa antes do hash Argon2 rodar.
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "config.hashers.Argon2PerfilOWASP",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/entrar/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/entrar/"

# `0` só em desenvolvimento, para um banco local novo não exigir matrícula de celular.
OTP_OBRIGATORIO = env_bool("OTP_OBRIGATORIO", True)
OTP_TOTP_ISSUER = "Emailing leonardocosta.dev"
# O padrão do django-otp é False — o admin mostraria a chave secreta do TOTP
# (e o link do QR, que revela a mesma chave) em texto puro no formulário do
# TOTPDevice. Não é um botão: é o certo, sempre.
OTP_ADMIN_HIDE_SENSITIVE_DATA = True

SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 43_200)  # 12 h
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# django-axes
AXES_FAILURE_LIMIT = env_int("AXES_FAILURE_LIMIT", 5)
AXES_COOLOFF_TIME = env_int("AXES_COOLOFF_HORAS", 1)
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]
AXES_LOCKOUT_TEMPLATE = "mensagens/bloqueado.html"
AXES_RESET_ON_SUCCESS = True
# Obrigatório atrás do nginx: sem isto o REMOTE_ADDR é sempre o proxy, o
# componente ip_address vira constante e qualquer bot que adivinhe o usuário
# tranca o dono para fora.
AXES_IPWARE_PROXY_COUNT = 0 if DEBUG else 1
AXES_IPWARE_META_PRECEDENCE_ORDER = ("HTTP_X_FORWARDED_FOR", "REMOTE_ADDR")

# Perfil OWASP do Argon2id (m=19456, t=2, p=1). O padrão do Django são 100 MiB
# por hash — com 2 workers × 4 threads isso é 800 MB só na tela de login.
ARGON2_MEMORY_KIB = env_int("ARGON2_MEMORY_KIB", 19_456)


# ---------------------------------------------------------------------------
# Segurança (fixos de propósito — não são botões)
# ---------------------------------------------------------------------------

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SAMESITE = "Strict"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Hosts somados ao img-src do CSP para as imagens das assinaturas aparecerem na
# prévia (o iframe srcdoc herda o CSP da página que o contém).
HOSTS_IMAGENS_ASSINATURA = os.environ.get(
    "HOSTS_IMAGENS_ASSINATURA", "https://gravatar.com https://cdn.jsdelivr.net"
)


# ---------------------------------------------------------------------------
# Estático
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}


# ---------------------------------------------------------------------------
# E-mail
# ---------------------------------------------------------------------------
#
# Contas e aliases moram no banco, gerenciados pelo admin (mensagens/models.py):
# host, porta, credencial, cifra e domínios permitidos são por conta. Aqui
# ficam só os padrões que não pertencem a nenhuma conta em particular.
#
# As variáveis SMTP_*/ALIAS_* do ambiente sobrevivem apenas como fonte para o
# `manage.py importar_aliases_do_env`, que lê direto de os.environ.

# Rede: o padrão do Django é None, que bloqueia a thread para sempre. Cada
# conta tem o seu (ContaEmail.timeout); este é a rede de segurança de qualquer
# envio que não passe por uma conta.
EMAIL_TIMEOUT = env_int("SMTP_TIMEOUT", 20)

# Sem isto o Date: sai "-0000", que na RFC 5322 significa "hora local
# desconhecida" e irrita alguns filtros.
EMAIL_USE_LOCALTIME = True


# ---------------------------------------------------------------------------
# Limites de composição e anexos
# ---------------------------------------------------------------------------

EML_MAX_BYTES = env_int("EML_MAX_BYTES", 5 * 1024 * 1024)
MAX_DESTINATARIOS = env_int("MAX_DESTINATARIOS", 50)
CITACAO_MAX_BYTES = env_int("CITACAO_MAX_BYTES", 100 * 1024)

ANEXOS_MAX_ARQUIVOS = env_int("ANEXOS_MAX_ARQUIVOS", 10)
ANEXO_MAX_BYTES = env_int("ANEXO_MAX_BYTES", 15 * 1024 * 1024)
# 18 MiB crus ≈ 24 MiB em base64, abaixo do teto usual de 25 MiB dos provedores.
ANEXOS_MAX_TOTAL_BYTES = env_int("ANEXOS_MAX_TOTAL_BYTES", 18 * 1024 * 1024)
ANEXOS_EXTENSOES_BLOQUEADAS = env_lista(
    "ANEXOS_EXTENSOES_BLOQUEADAS", "exe,bat,cmd,com,scr,js,vbs,jar,msi,ps1"
)
RASCUNHOS_TTL_DIAS = env_int("RASCUNHOS_TTL_DIAS", 7)

# Dias sem alteração até um **rascunho salvo** (a mensagem, não a pasta de
# anexos acima) ser apagado pela limpeza diária, junto com os anexos dele. `0`
# desliga: o rascunho nunca expira. O nome é diferente de `RASCUNHOS_TTL_DIAS`
# de propósito — são coisas diferentes que o código chama de "rascunho".
RASCUNHO_SALVO_EXPIRA_DIAS = env_int("RASCUNHO_SALVO_EXPIRA_DIAS", 30)

GUARDAR_CORPO_ENVIADO = env_bool("GUARDAR_CORPO_ENVIADO", True)

DATA_UPLOAD_MAX_NUMBER_FILES = ANEXOS_MAX_ARQUIVOS + 5
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_TEMP_DIR = str(DATA_DIR / "tmp")
Path(FILE_UPLOAD_TEMP_DIR).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
#
# Em produção isto tem que apontar para FORA do DATA_DIR: o que o backup protege
# é justamente o DATA_DIR, e um `rm -rf data/` levaria as duas cópias juntas
# (`/var/backups/emailing`, no `.env`).
#
# O padrão cai dentro do DATA_DIR porque em desenvolvimento não há o que
# proteger, e porque a alternativa seria pior: uma pasta no BASE_DIR seria
# apagada pelo `rsync --delete` do deploy. O `verificar_config` avisa quando o
# padrão ficou valendo com DEBUG desligado.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", DATA_DIR / "backups"))
BACKUP_MANTER = env_int("BACKUP_MANTER", 14)


# ---------------------------------------------------------------------------
# Envio programado
# ---------------------------------------------------------------------------
#
# O despachante é um `manage.py despachar_agendados` rodando por cron, não uma
# fila — continua valendo o "sem Celery, sem broker" (docs/decisoes.md). O que
# muda em relação ao envio pela tela é que ninguém está olhando, e é disso que
# saem estes limites.

# Teto por execução. Hostinger e Titan limitam saída por hora e por dia: um
# lote grande de uma vez viraria uma fila de FALHOU em vez de atraso.
AGENDADOS_MAX_POR_EXECUCAO = env_int("AGENDADOS_MAX_POR_EXECUCAO", 20)

AGENDADOS_MAX_TENTATIVAS = env_int("AGENDADOS_MAX_TENTATIVAS", 3)
# Espera antes de tentar de novo, dobrando a cada tentativa (5, 10, 20 min).
AGENDADOS_BACKOFF_MINUTOS = env_int("AGENDADOS_BACKOFF_MINUTOS", 5)

# Atraso máximo tolerado entre a hora marcada e o despacho de fato. Se o
# servidor ficou fora do ar dois dias, disparar o acumulado ao voltar é pior do
# que não disparar: a mensagem foi escrita para um momento que já passou. `0`
# desliga a checagem e manda de qualquer jeito.
AGENDADOS_TOLERANCIA_HORAS = env_int("AGENDADOS_TOLERANCIA_HORAS", 24)

# Para onde avisar quando um agendamento esgota as tentativas. Vazio = não
# avisa (o histórico registra de todo jeito, mas ninguém lê às 3h da manhã).
AGENDADOS_AVISAR_PARA = os.environ.get("AGENDADOS_AVISAR_PARA", "").strip()
# Alias que manda o aviso. Vazio = o alias do próprio agendamento — que pode
# ser justamente o que está com credencial quebrada; daí a escotilha.
AGENDADOS_AVISAR_ALIAS = os.environ.get("AGENDADOS_AVISAR_ALIAS", "").strip()


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simples": {"format": "{levelname} {asctime} {name} {message}", "style": "{"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simples"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "mensagens": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # O django-axes anuncia "AXES: BEGIN version…" em INFO a cada
        # inicialização do app. No serviço web é uma linha por worker; no cron
        # de minuto do `despachar_agendados` seria uma linha por minuto, para
        # sempre — e o log do despachante existe para mostrar o que ele fez, não
        # para provar que rodou. WARNING preserva o que interessa (lockout).
        "axes": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
