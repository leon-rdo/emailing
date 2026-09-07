"""Backup do banco: cópia consistente, verificada e rotacionada.

Era a maior pendência conhecida do projeto. O `DATA_DIR` guarda contas, aliases,
assinaturas, histórico e a fila de agendados — mensagens que ainda **vão** sair —
e até aqui não existia nenhuma outra cópia.

Três coisas que este módulo faz e um `cp` não faz:

1. **Cópia consistente.** O banco roda em WAL: um `cp` do `.sqlite3` leva o
   arquivo principal sem o `-wal`, e o resultado pode estar velho ou quebrado.
   `sqlite3.Connection.backup()` é a API de backup online do SQLite — respeita o
   journal e tolera escrita concorrente, então não é preciso parar o serviço.
2. **Verificação.** Um backup que nunca foi lido não é um backup. Todo arquivo
   novo passa por `PRAGMA integrity_check` **antes** de a rotação encostar nos
   antigos: nunca se apaga uma cópia boa porque chegou uma ruim.
3. **Manifesto.** Ao lado de cada cópia vai um JSON com o que se quer saber antes
   de restaurar: contagens, migração aplicada e a **impressão digital do
   `SECRET_KEY`**. Essa última resolve um problema real e já documentado: as
   senhas SMTP são cifradas com chave derivada do `SECRET_KEY`, então um backup
   restaurado com outra chave traz senha ilegível — e hoje isso só se descobre
   quando um envio falha. Guarda-se o hash da chave, nunca a chave.

O que este módulo **não** faz: cópia fora da máquina. Backup local protege do que
é mais provável (apagar `data/`, uma migração ruim, corrupção de arquivo) e não
protege de perder o disco. Cópia externa precisa de destino, credencial e cifra
— é decisão de operação, e está descrita em docs/operacao.md.

A origem é a **conexão viva do Django**, não um `sqlite3.connect()` no caminho do
arquivo: assim se copia o banco que o app realmente está usando, e o mesmo código
serve para o teste (onde o banco é outro) sem um segundo caminho.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.db import connection

from .models import Alias, ContaEmail, EnvioAgendado, RegistroEnvio

logger = logging.getLogger(__name__)

SUFIXO_BANCO = ".sqlite3"
SUFIXO_MANIFESTO = ".json"


class ErroBackup(Exception):
    """A mensagem já é o texto pronto para mostrar a quem chamou."""


@dataclass(frozen=True)
class Backup:
    caminho: Path
    manifesto: dict

    @property
    def caminho_manifesto(self) -> Path:
        return self.caminho.with_suffix(SUFIXO_MANIFESTO)

    @property
    def tamanho(self) -> int:
        return self.caminho.stat().st_size


def pasta() -> Path:
    destino = Path(settings.BACKUP_DIR)
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def impressao_da_chave(chave: str = "") -> str:
    """Hash curto do `SECRET_KEY` — o suficiente para comparar, inútil para abrir."""
    return hashlib.sha256((chave or settings.SECRET_KEY).encode()).hexdigest()[:16]


def _agora_utc() -> datetime:
    return datetime.now(UTC)


def _nome(momento: datetime) -> str:
    # UTC, e ordenável como texto: a rotação é por ordem de nome, e horário
    # local com horário de verão produziria nomes fora de ordem (ou repetidos).
    return f"db-{momento.strftime('%Y%m%dT%H%M%SZ')}{SUFIXO_BANCO}"


def _origem() -> sqlite3.Connection:
    if "sqlite3" not in settings.DATABASES["default"]["ENGINE"]:
        raise ErroBackup(
            "Este backup usa a API do SQLite. Com outro banco, use a ferramenta dele."
        )
    # Sem esta guarda o backup **trava para sempre**, e não é hipótese: a API de
    # backup do SQLite pede um bloqueio de leitura na origem, e uma transação de
    # escrita aberta nesta mesma conexão segura esse bloqueio. O laço de repetição
    # do sqlite3 do Python não tem teto — ele tenta de novo enquanto der BUSY, ou
    # seja, para sempre, esperando por si mesmo.
    #
    # Rodando por `manage.py` (que é como o cron chama) não há transação aberta e
    # nada disso acontece. A guarda existe porque "trava calado" é o pior modo de
    # falha possível para um backup, e porque a próxima pessoa a chamar `criar()`
    # de dentro de um `atomic()` merece uma frase em vez de um processo pendurado.
    if connection.in_atomic_block:
        raise ErroBackup(
            "Backup dentro de uma transação aberta: a API do SQLite esperaria por "
            "um bloqueio que esta mesma conexão está segurando, e a espera não tem "
            "fim. Rode fora de `transaction.atomic()`."
        )
    connection.ensure_connection()
    return connection.connection


def _contagens() -> dict:
    return {
        "contas": ContaEmail.objects.count(),
        "aliases": Alias.objects.count(),
        "registros": RegistroEnvio.objects.count(),
        "agendados_pendentes": EnvioAgendado.objects.filter(
            status=EnvioAgendado.Status.AGENDADO
        ).count(),
    }


def _ultima_migracao() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations ORDER BY id DESC LIMIT 1")
        linha = cursor.fetchone()
    return f"{linha[0]}.{linha[1]}" if linha else "(nenhuma)"


def integridade(caminho: Path) -> str:
    """`"ok"` ou a explicação do SQLite. Abre o arquivo do backup, não o banco vivo."""
    if not caminho.is_file():
        return f"arquivo não encontrado: {caminho}"
    try:
        conexao = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return f"não abriu: {exc}"
    try:
        resultado = conexao.execute("PRAGMA integrity_check").fetchone()
        return resultado[0] if resultado else "sem resposta do integrity_check"
    except sqlite3.DatabaseError as exc:
        return f"ilegível: {exc}"
    finally:
        conexao.close()


def criar() -> Backup:
    """Faz a cópia, verifica, escreve o manifesto. Levanta `ErroBackup` se falhar.

    Não rotaciona: quem chama decide, e a ordem importa — ver `rotacionar()`.
    """
    origem = _origem()
    momento = _agora_utc()
    destino = pasta() / _nome(momento)

    if destino.exists():
        raise ErroBackup(f"Já existe um backup deste segundo: {destino.name}")

    copia = sqlite3.connect(destino)
    try:
        origem.backup(copia)
    except sqlite3.Error as exc:
        destino.unlink(missing_ok=True)
        raise ErroBackup(f"O SQLite recusou a cópia: {exc}") from exc
    finally:
        copia.close()

    veredito = integridade(destino)
    if veredito != "ok":
        destino.unlink(missing_ok=True)
        raise ErroBackup(f"A cópia saiu corrompida e foi descartada: {veredito}")

    manifesto = {
        "criado_em": momento.isoformat(),
        "arquivo": destino.name,
        "tamanho": destino.stat().st_size,
        "integridade": veredito,
        # As senhas SMTP são cifradas com chave derivada do SECRET_KEY. Sem esta
        # impressão, um backup restaurado com outra chave só se revela inútil na
        # hora de enviar. Guarda o hash, nunca a chave.
        "secret_key": impressao_da_chave(),
        "ultima_migracao": _ultima_migracao(),
        "conteudo": _contagens(),
    }
    destino.with_suffix(SUFIXO_MANIFESTO).write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logger.info("Backup criado: %s (%s bytes)", destino.name, manifesto["tamanho"])
    return Backup(caminho=destino, manifesto=manifesto)


def listar() -> list[Path]:
    """Do mais novo para o mais velho. O nome é UTC, então ordem de nome serve."""
    return sorted(pasta().glob(f"db-*{SUFIXO_BANCO}"), reverse=True)


def mais_recente() -> Path | None:
    encontrados = listar()
    return encontrados[0] if encontrados else None


def idade_do_ultimo() -> timedelta | None:
    """Quanto tempo desde o backup mais novo. `None` se não há nenhum.

    Serve para o `verificar_config` responder a pergunta que importa — "o cron
    está rodando?" — em vez de "o cron está instalado?".
    """
    ultimo = mais_recente()
    if ultimo is None:
        return None
    return _agora_utc() - datetime.fromtimestamp(ultimo.stat().st_mtime, tz=UTC)


def rotacionar(manter: int | None = None) -> list[Path]:
    """Apaga os mais velhos além de `manter`, e devolve o que foi apagado.

    Chamado **depois** de `criar()` ter verificado a cópia nova. Se a nova não
    presta, `criar()` levanta e a rotação não acontece: uma cópia boa nunca é
    apagada para dar lugar a uma ruim.
    """
    manter = settings.BACKUP_MANTER if manter is None else manter
    if manter <= 0:
        return []
    apagados = []
    for caminho in listar()[manter:]:
        caminho.with_suffix(SUFIXO_MANIFESTO).unlink(missing_ok=True)
        caminho.unlink(missing_ok=True)
        apagados.append(caminho)
    return apagados


def conferir(caminho: Path | None = None) -> dict:
    """Diz se um backup serve para restaurar. Sem argumento, confere o mais novo.

    Três perguntas, e a terceira é a que ninguém lembra de fazer: o arquivo abre,
    o `integrity_check` passa, e as senhas cifradas lá dentro abrem com o
    `SECRET_KEY` **que você tem agora**.
    """
    caminho = caminho or mais_recente()
    if caminho is None:
        raise ErroBackup(f"Nenhum backup em {pasta()}.")
    caminho = Path(caminho)

    manifesto_arquivo = caminho.with_suffix(SUFIXO_MANIFESTO)
    manifesto = {}
    if manifesto_arquivo.is_file():
        try:
            manifesto = json.loads(manifesto_arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            manifesto = {"erro": f"manifesto ilegível: {exc}"}

    veredito = integridade(caminho)
    chave_gravada = manifesto.get("secret_key")
    chave_atual = impressao_da_chave()
    if chave_gravada is None:
        chave = "desconhecida (backup sem manifesto)"
        chave_bate = None
    else:
        chave_bate = chave_gravada == chave_atual
        chave = "a mesma de agora" if chave_bate else (
            "OUTRA — as senhas SMTP deste backup não abrem com o SECRET_KEY atual "
            "e terão que ser redigitadas no admin"
        )

    return {
        "arquivo": str(caminho),
        "existe": caminho.is_file(),
        "tamanho": caminho.stat().st_size if caminho.is_file() else 0,
        "integridade": veredito,
        "secret_key": chave,
        "secret_key_bate": chave_bate,
        "restauravel": veredito == "ok",
        "manifesto": manifesto,
    }


def avisos() -> list[str]:
    """Problemas de backup em linguagem de gente. Lista vazia = tudo certo.

    Não levanta e não é fatal: o `verificar_config` mostra isto junto com o
    resto, e o `implantar.sh` não deve falhar por causa de backup. A pergunta que
    estas linhas respondem é "o cron está **rodando**?", que é diferente de "o
    cron está instalado?" — e é a única que importa.
    """
    recados = []

    destino = Path(settings.BACKUP_DIR).resolve()
    dados = Path(settings.DATA_DIR).resolve()
    if not settings.DEBUG and (destino == dados or dados in destino.parents):
        recados.append(
            f"BACKUP_DIR ({destino}) está dentro do DATA_DIR: apagar `data/` levaria "
            "os backups junto. Aponte para fora, ex.: /var/backups/emailing."
        )

    idade = idade_do_ultimo()
    if idade is None:
        recados.append(f"Nenhum backup em {pasta()}. Rode `manage.py backup`.")
    elif idade > timedelta(hours=48):
        recados.append(
            f"O backup mais recente tem {int(idade.total_seconds() // 3600)}h. "
            "O cron diário pode não estar rodando — veja /var/log/emailing-backup.log."
        )
    return recados
