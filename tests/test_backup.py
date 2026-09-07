"""Backup do banco: cópia consistente, verificada, rotacionada.

A propriedade que estes testes existem para fixar não é "o arquivo aparece" —
é que uma cópia ruim nunca substitui uma boa, e que a pergunta "isto serve para
restaurar?" tem resposta antes da hora ruim.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from mensagens import backup

# `transaction=True`: o `django_db` normal embrulha o teste num `atomic()`, e a
# API de backup do SQLite não copia de uma conexão com transação de escrita
# aberta — esperaria por um bloqueio que ela mesma segura. É a mesma razão pela
# qual `_origem()` recusa rodar dentro de `atomic()`; ver `test_recusa_dentro_de_transacao`.
pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def pasta_de_backup(tmp_path, settings):
    settings.BACKUP_DIR = tmp_path / "backups"
    return settings.BACKUP_DIR


@pytest.fixture
def relogio(monkeypatch):
    """Deixa o teste escolher o instante — o nome do arquivo tem precisão de
    segundo, e `criar()` se recusa a sobrescrever um backup do mesmo segundo."""
    estado = {"agora": datetime(2026, 9, 7, 3, 0, 0, tzinfo=UTC)}

    def agora():
        return estado["agora"]

    monkeypatch.setattr(backup, "_agora_utc", agora)

    def avancar(minutos=1):
        estado["agora"] += timedelta(minutes=minutos)

    return avancar


# ---------------------------------------------------------------------------
# A cópia
# ---------------------------------------------------------------------------


def test_cria_copia_verificada_com_manifesto(alias_de_teste, pasta_de_backup):
    feito = backup.criar()

    assert feito.caminho.is_file()
    assert feito.manifesto["integridade"] == "ok"
    assert feito.caminho_manifesto.is_file()
    gravado = json.loads(feito.caminho_manifesto.read_text())
    assert gravado == feito.manifesto


def test_a_copia_contem_os_dados_de_verdade(alias_de_teste, pasta_de_backup):
    """O teste que separa "gerou um arquivo" de "gerou um backup"."""
    feito = backup.criar()

    conexao = sqlite3.connect(f"file:{feito.caminho}?mode=ro", uri=True)
    try:
        slugs = [linha[0] for linha in conexao.execute("SELECT slug FROM mensagens_alias")]
    finally:
        conexao.close()

    assert slugs == ["financeiro"]


def test_manifesto_conta_o_que_foi_salvo(alias_de_teste, pasta_de_backup):
    conteudo = backup.criar().manifesto["conteudo"]
    assert conteudo["aliases"] == 1
    assert conteudo["contas"] == 1
    assert conteudo["agendados_pendentes"] == 0


def test_manifesto_guarda_a_impressao_da_chave_e_nao_a_chave(alias_de_teste, pasta_de_backup,
                                                             settings):
    settings.SECRET_KEY = "uma-chave-bem-especifica-de-teste"
    manifesto = backup.criar().manifesto

    assert manifesto["secret_key"] == backup.impressao_da_chave()
    assert settings.SECRET_KEY not in json.dumps(manifesto)
    assert len(manifesto["secret_key"]) == 16


# ---------------------------------------------------------------------------
# Conferir: a pergunta é "serve para restaurar?"
# ---------------------------------------------------------------------------


def test_conferir_aprova_backup_bom(alias_de_teste, pasta_de_backup):
    feito = backup.criar()
    resultado = backup.conferir(feito.caminho)

    assert resultado["restauravel"] is True
    assert resultado["integridade"] == "ok"
    assert resultado["secret_key_bate"] is True


def test_conferir_sem_argumento_pega_o_mais_recente(alias_de_teste, pasta_de_backup, relogio):
    backup.criar()
    relogio()
    novo = backup.criar()

    assert backup.conferir()["arquivo"] == str(novo.caminho)


def test_conferir_reprova_arquivo_que_nao_e_banco(pasta_de_backup):
    pasta_de_backup.mkdir(parents=True, exist_ok=True)
    lixo = pasta_de_backup / "db-20260101T000000Z.sqlite3"
    lixo.write_bytes(b"isto nao e um banco de dados")

    resultado = backup.conferir(lixo)

    assert resultado["restauravel"] is False
    assert resultado["integridade"] != "ok"


def test_conferir_avisa_que_o_secret_key_mudou(alias_de_teste, pasta_de_backup, settings):
    """O modo de falha que hoje só aparece quando um envio falha: banco
    restaurado com outra chave traz senha SMTP ilegível."""
    settings.SECRET_KEY = "a-chave-de-quando-o-backup-foi-feito"
    feito = backup.criar()

    settings.SECRET_KEY = "a-chave-de-agora-que-e-outra"
    resultado = backup.conferir(feito.caminho)

    assert resultado["secret_key_bate"] is False
    assert "redigitadas" in resultado["secret_key"]
    # O arquivo continua íntegro — o problema não é o banco, é a chave.
    assert resultado["integridade"] == "ok"


def test_conferir_sem_backup_nenhum_levanta(pasta_de_backup):
    with pytest.raises(backup.ErroBackup):
        backup.conferir()


def test_recusa_dentro_de_transacao(alias_de_teste, pasta_de_backup):
    """Sem a guarda isto não falharia — ficaria pendurado para sempre, esperando
    por um bloqueio que a própria conexão segura."""
    from django.db import transaction

    with transaction.atomic(), pytest.raises(backup.ErroBackup, match="transação aberta"):
        backup.criar()


# ---------------------------------------------------------------------------
# Rotação: nunca apagar uma cópia boa por causa de uma ruim
# ---------------------------------------------------------------------------


def test_rotacao_guarda_os_mais_novos(alias_de_teste, pasta_de_backup, relogio):
    for _ in range(5):
        backup.criar()
        relogio()

    apagados = backup.rotacionar(manter=2)

    assert len(apagados) == 3
    restantes = backup.listar()
    assert len(restantes) == 2
    # e os manifestos dos apagados foram junto
    assert len(list(pasta_de_backup.glob("*.json"))) == 2


def test_rotacao_desligada_com_zero(alias_de_teste, pasta_de_backup, relogio):
    backup.criar()
    relogio()
    backup.criar()

    assert backup.rotacionar(manter=0) == []
    assert len(backup.listar()) == 2


def test_copia_corrompida_e_descartada_e_nao_rotaciona(alias_de_teste, pasta_de_backup,
                                                       relogio, monkeypatch):
    """A propriedade que mais importa neste módulo: se a cópia nova saiu ruim,
    ela é jogada fora e as antigas ficam onde estão."""
    boa = backup.criar()
    relogio()

    monkeypatch.setattr(backup, "integridade", lambda caminho: "*** in database main")

    with pytest.raises(backup.ErroBackup, match="corrompida"):
        backup.criar()

    assert backup.listar() == [boa.caminho]  # a ruim não ficou, a boa não saiu


def test_recusa_dois_backups_no_mesmo_segundo(alias_de_teste, pasta_de_backup, relogio):
    """Explícito em vez de sobrescrever: perder o backup anterior porque alguém
    rodou o comando duas vezes seria o pior jeito de descobrir isso."""
    backup.criar()
    with pytest.raises(backup.ErroBackup, match="deste segundo"):
        backup.criar()


# ---------------------------------------------------------------------------
# Avisos: "o cron está rodando?" ≠ "o cron está instalado?"
# ---------------------------------------------------------------------------


def test_avisa_quando_nao_ha_backup(pasta_de_backup):
    assert any("Nenhum backup" in a for a in backup.avisos())


def test_nao_reclama_de_backup_recente(alias_de_teste, pasta_de_backup):
    backup.criar()
    assert backup.avisos() == []


def test_avisa_quando_o_backup_esta_velho(alias_de_teste, pasta_de_backup, monkeypatch):
    backup.criar()
    monkeypatch.setattr(backup, "idade_do_ultimo", lambda: timedelta(hours=72))

    assert any("72h" in a for a in backup.avisos())


def test_avisa_quando_os_backups_moram_dentro_do_data_dir(alias_de_teste, settings, tmp_path):
    """Um `rm -rf data/` levaria as duas cópias — e é justamente disso que o
    backup deveria proteger."""
    settings.DEBUG = False
    settings.DATA_DIR = tmp_path
    settings.BACKUP_DIR = tmp_path / "backups"
    backup.criar()

    assert any("dentro do DATA_DIR" in a for a in backup.avisos())


def test_em_desenvolvimento_nao_reclama_do_lugar(alias_de_teste, settings, tmp_path):
    settings.DEBUG = True
    settings.DATA_DIR = tmp_path
    settings.BACKUP_DIR = tmp_path / "backups"
    backup.criar()

    assert backup.avisos() == []


# ---------------------------------------------------------------------------
# O comando
# ---------------------------------------------------------------------------


def test_comando_cria_e_rotaciona(alias_de_teste, pasta_de_backup, relogio, capsys):
    for _ in range(3):
        call_command("backup", "--manter", "2")
        relogio()

    assert len(backup.listar()) == 2
    assert "integridade ok" in capsys.readouterr().out


def test_comando_em_json(alias_de_teste, pasta_de_backup, capsys):
    call_command("backup", "--json")
    dados = json.loads(capsys.readouterr().out)

    assert dados["ok"] is True
    assert dados["manifesto"]["integridade"] == "ok"


def test_comando_listar(alias_de_teste, pasta_de_backup, relogio, capsys):
    backup.criar()
    relogio()
    backup.criar()

    call_command("backup", "--listar", "--json")
    dados = json.loads(capsys.readouterr().out)

    assert dados["total"] == 2
    assert dados["horas_desde_o_ultimo"] is not None


def test_comando_conferir_sai_1_em_backup_ruim(pasta_de_backup):
    pasta_de_backup.mkdir(parents=True, exist_ok=True)
    lixo = pasta_de_backup / "db-20260101T000000Z.sqlite3"
    lixo.write_bytes(b"nao e banco")

    with pytest.raises(SystemExit) as saida:
        call_command("backup", "--conferir", str(lixo))

    assert saida.value.code == 1


def test_comando_conferir_sem_backup_reclama(pasta_de_backup):
    with pytest.raises(CommandError, match="Nenhum backup"):
        call_command("backup", "--conferir")


# ---------------------------------------------------------------------------
# O backup é um arquivo e mais nada
# ---------------------------------------------------------------------------


def test_backup_nao_deixa_satelites_do_wal(alias_de_teste, pasta_de_backup):
    """A origem está em WAL e a cópia herdava o modo, deixando um `-wal` e um
    `-shm` ao lado — que a rotação nunca apagava, e que convidam a copiar só o
    arquivo principal com um journal alheio do lado."""
    feito = backup.criar()

    vizinhos = sorted(c.name for c in pasta_de_backup.iterdir())
    assert vizinhos == [feito.caminho_manifesto.name, feito.caminho.name]


def test_a_copia_sai_fora_do_wal_e_ainda_assim_abre(alias_de_teste, pasta_de_backup):
    feito = backup.criar()

    conexao = sqlite3.connect(f"file:{feito.caminho}?mode=ro", uri=True)
    try:
        modo = conexao.execute("PRAGMA journal_mode").fetchone()[0]
        aliases = conexao.execute("SELECT COUNT(*) FROM mensagens_alias").fetchone()[0]
    finally:
        conexao.close()

    assert modo == "delete"
    assert aliases == 1


def test_rotacao_nao_deixa_nada_para_tras(alias_de_teste, pasta_de_backup, relogio):
    for _ in range(3):
        backup.criar()
        relogio()

    backup.rotacionar(manter=1)

    restante = sorted(c.name for c in pasta_de_backup.iterdir())
    assert len(restante) == 2  # o .sqlite3 e o .json do mais novo, nada mais


def test_copia_descartada_nao_deixa_satelites(alias_de_teste, pasta_de_backup, monkeypatch):
    monkeypatch.setattr(backup, "integridade", lambda caminho: "*** in database main")

    with pytest.raises(backup.ErroBackup):
        backup.criar()

    assert list(pasta_de_backup.iterdir()) == []
