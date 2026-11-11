"""`manage.py enviar`: a porta do operador (e de um agente com ssh).

O que importa aqui é que esta rota não seja um segundo app: mesma validação,
mesma montagem, mesmo `RegistroEnvio` da tela. E que as diferenças deliberadas
— corpo fora do `argv`, sem trava de hash, `--conferir` em vez de prévia —
sejam as únicas diferenças.
"""

import io
import json
from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from mensagens.models import EnvioAgendado, RegistroEnvio

pytestmark = pytest.mark.django_db


def _corpo(tmp_path, html="<p>Olá</p>"):
    caminho = tmp_path / "corpo.html"
    caminho.write_text(html, encoding="utf-8")
    return str(caminho)


def _chamar(*args, **kwargs):
    saida = io.StringIO()
    call_command("enviar", *args, stdout=saida, stderr=saida, **kwargs)
    return saida.getvalue()


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------


def test_envia_com_corpo_de_arquivo(alias_de_teste, tmp_path):
    saida = _chamar(
        "--alias", "financeiro",
        "--para", "cliente@example.com",
        "--assunto", "Proposta",
        "--corpo-arquivo", _corpo(tmp_path),
    )

    assert "Enviado" in saida
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["cliente@example.com"]
    assert mail.outbox[0].subject == "Proposta"
    registro = RegistroEnvio.objects.get()
    assert registro.status == RegistroEnvio.Status.ENVIADO
    assert registro.alias == "financeiro"


def test_registra_no_mesmo_historico_da_tela(alias_de_teste, tmp_path, settings):
    """Uma trilha de auditoria só, independente de quem redigiu."""
    settings.GUARDAR_CORPO_ENVIADO = True
    _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path, "<p>vindo do terminal</p>"),
    )
    assert "vindo do terminal" in RegistroEnvio.objects.get().corpo_html


def test_corpo_pelo_stdin(alias_de_teste, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("<p>pelo cano</p>"))

    _chamar("--alias", "financeiro", "--para", "c@x.com")

    assert "pelo cano" in mail.outbox[0].alternatives[0][0]


def test_sem_corpo_e_sem_stdin_explica_por_que(alias_de_teste, monkeypatch):
    """O corpo não entra por argumento de propósito — e o erro precisa dizer
    isso, senão a próxima tentativa é inventar um `--corpo`."""
    falso = io.StringIO("")
    falso.isatty = lambda: True
    monkeypatch.setattr("sys.stdin", falso)

    with pytest.raises(CommandError) as erro:
        _chamar("--alias", "financeiro", "--para", "c@x.com")

    assert "--corpo-arquivo" in str(erro.value)
    assert "stdin" in str(erro.value)


def test_html_passa_pelo_mesmo_sanitizador(alias_de_teste, tmp_path):
    _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path, "<p>ok</p><script>alert(1)</script>"),
    )
    assert "<script>" not in mail.outbox[0].alternatives[0][0]


def test_marcadores_expandem_no_envio(alias_de_teste, tmp_path):
    _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path, "<p>Hoje é {{ data }}</p>"),
    )
    hoje = timezone.localtime().strftime("%d/%m/%Y")
    assert hoje in mail.outbox[0].alternatives[0][0]


def test_falha_de_smtp_sai_com_codigo_1(alias_de_teste, tmp_path, monkeypatch):
    from smtplib import SMTPException

    def quebrar(self, *args, **kwargs):
        raise SMTPException("sem credencial")

    monkeypatch.setattr(mail.EmailMultiAlternatives, "send", quebrar)

    with pytest.raises(SystemExit) as saida:
        _chamar(
            "--alias", "financeiro", "--para", "c@x.com",
            "--corpo-arquivo", _corpo(tmp_path),
        )

    assert saida.value.code == 1
    # E a tentativa fica registrada — falhar não é desaparecer.
    assert RegistroEnvio.objects.get().status == RegistroEnvio.Status.FALHOU


def test_json_de_envio_e_legivel_por_maquina(alias_de_teste, tmp_path):
    saida = _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path), "--json",
    )
    dados = json.loads(saida)
    assert dados["ok"] is True
    assert dados["acao"] == "enviar"
    assert dados["message_id"].endswith("@empresa.example>")
    assert dados["historico"] == f"/historico/{RegistroEnvio.objects.get().pk}/"


# ---------------------------------------------------------------------------
# Validação — a mesma da tela, sem uma segunda cópia
# ---------------------------------------------------------------------------


def test_alias_desconhecido_lista_os_disponiveis(alias_de_teste, tmp_path):
    with pytest.raises(CommandError) as erro:
        _chamar("--alias", "vendas", "--para", "c@x.com", "--corpo-arquivo", _corpo(tmp_path))
    assert "financeiro" in str(erro.value)


def test_endereco_invalido_e_recusado(alias_de_teste, tmp_path):
    with pytest.raises(CommandError) as erro:
        _chamar(
            "--alias", "financeiro", "--para", "cliente@exe",
            "--corpo-arquivo", _corpo(tmp_path),
        )
    assert "cliente@exe" in str(erro.value)
    assert mail.outbox == []


def test_enviar_exige_destinatario(alias_de_teste, tmp_path):
    with pytest.raises(CommandError):
        _chamar("--alias", "financeiro", "--corpo-arquivo", _corpo(tmp_path))


def test_limite_de_destinatarios_vale_igual(alias_de_teste, tmp_path, settings):
    settings.MAX_DESTINATARIOS = 2
    with pytest.raises(CommandError) as erro:
        _chamar(
            "--alias", "financeiro", "--para", "a@x.com,b@x.com,c@x.com",
            "--corpo-arquivo", _corpo(tmp_path),
        )
    assert "limite" in str(erro.value)


# ---------------------------------------------------------------------------
# --conferir
# ---------------------------------------------------------------------------


def test_conferir_nao_envia_nada(alias_de_teste, tmp_path):
    saida = _chamar(
        "--alias", "financeiro", "--para", "c@x.com", "--assunto", "Oi",
        "--corpo-arquivo", _corpo(tmp_path), "--conferir",
    )

    assert mail.outbox == []
    assert RegistroEnvio.objects.count() == 0
    assert "Nada foi enviado" in saida
    assert "financeiro@empresa.example" in saida


def test_conferir_mostra_o_html_que_sairia(alias_de_teste, tmp_path):
    saida = _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path, "<p>ok</p><script>x</script>"),
        "--conferir",
    )
    assert "<p>ok</p>" in saida
    assert "<script>" not in saida  # já sanitizado, como sairia


def test_conferir_dispensa_destinatario(alias_de_teste, tmp_path):
    """Mesma decisão da prévia da tela: conferir é do conteúdo, e o
    destinatário é a última coisa que se decide."""
    saida = _chamar("--alias", "financeiro", "--corpo-arquivo", _corpo(tmp_path), "--conferir")
    assert "(nenhum)" in saida


def test_conferir_recusa_endereco_torto(alias_de_teste, tmp_path):
    """Aqui a tolerância da prévia da tela NÃO se aplica: lá vem outra tecla
    atrás; no terminal, não vem nada atrás."""
    with pytest.raises(CommandError):
        _chamar(
            "--alias", "financeiro", "--para", "cliente@exe",
            "--corpo-arquivo", _corpo(tmp_path), "--conferir",
        )


def test_conferir_em_json(alias_de_teste, tmp_path):
    saida = _chamar(
        "--alias", "financeiro", "--para", "c@x.com", "--assunto", "Oi",
        "--corpo-arquivo", _corpo(tmp_path), "--conferir", "--json",
    )
    dados = json.loads(saida)
    assert dados["acao"] == "conferir"
    assert dados["remetente"] == "Ana Souza <financeiro@empresa.example>"
    assert dados["envelope"] == "financeiro@empresa.example"
    assert "<p>Olá</p>" in dados["html"]
    assert "Olá" in dados["texto"]


# ---------------------------------------------------------------------------
# Anexos do disco local
# ---------------------------------------------------------------------------


def test_anexo_do_disco_vai_na_mensagem(alias_de_teste, tmp_path, settings):
    settings.RASCUNHOS_DIR = tmp_path / "rascunhos"
    anexo = tmp_path / "nota.pdf"
    anexo.write_bytes(b"conteudo-pdf")

    _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path), "--anexo", str(anexo),
    )

    assert mail.outbox[0].attachments[0][0] == "nota.pdf"


def test_anexo_inexistente_falha_antes_de_enviar(alias_de_teste, tmp_path, settings):
    settings.RASCUNHOS_DIR = tmp_path / "rascunhos"
    with pytest.raises(CommandError) as erro:
        _chamar(
            "--alias", "financeiro", "--para", "c@x.com",
            "--corpo-arquivo", _corpo(tmp_path), "--anexo", str(tmp_path / "fantasma.pdf"),
        )
    assert "não encontrado" in str(erro.value)
    assert mail.outbox == []


def test_extensao_bloqueada_vale_igual_na_cli(alias_de_teste, tmp_path, settings):
    """Se a CLI aceitasse o que o formulário recusa, "funciona no navegador e
    não no terminal" viraria um relatório de bug para você mesmo."""
    settings.RASCUNHOS_DIR = tmp_path / "rascunhos"
    ruim = tmp_path / "instalador.exe"
    ruim.write_bytes(b"MZ")

    with pytest.raises(CommandError) as erro:
        _chamar(
            "--alias", "financeiro", "--para", "c@x.com",
            "--corpo-arquivo", _corpo(tmp_path), "--anexo", str(ruim),
        )
    assert ".exe" in str(erro.value)


def test_conferir_com_anexo_nao_grava_rascunho(alias_de_teste, tmp_path, settings):
    rascunhos = tmp_path / "rascunhos"
    settings.RASCUNHOS_DIR = rascunhos
    anexo = tmp_path / "nota.pdf"
    anexo.write_bytes(b"x")

    saida = _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path), "--anexo", str(anexo), "--conferir",
    )

    assert "nota.pdf" in saida
    assert not rascunhos.exists() or list(rascunhos.iterdir()) == []


# ---------------------------------------------------------------------------
# --em: agendar pela linha de comando
# ---------------------------------------------------------------------------


def test_em_agenda_em_vez_de_enviar(alias_de_teste, tmp_path):
    quando = timezone.localtime() + timedelta(days=1)
    saida = _chamar(
        "--alias", "financeiro", "--para", "c@x.com", "--assunto", "Depois",
        "--corpo-arquivo", _corpo(tmp_path), "--em", quando.strftime("%Y-%m-%d %H:%M"),
    )

    assert mail.outbox == []
    agendado = EnvioAgendado.objects.get()
    assert agendado.status == EnvioAgendado.Status.AGENDADO
    assert agendado.assunto == "Depois"
    assert f"#{agendado.pk}" in saida


def test_em_aceita_o_formato_brasileiro(alias_de_teste, tmp_path):
    quando = timezone.localtime() + timedelta(days=2)
    _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path), "--em", quando.strftime("%d/%m/%Y %H:%M"),
    )
    agendado = EnvioAgendado.objects.get()
    assert timezone.localtime(agendado.enviar_em).date() == quando.date()


def test_em_no_passado_e_recusado(alias_de_teste, tmp_path):
    passado = (timezone.localtime() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(CommandError) as erro:
        _chamar(
            "--alias", "financeiro", "--para", "c@x.com",
            "--corpo-arquivo", _corpo(tmp_path), "--em", passado,
        )
    assert "já passou" in str(erro.value)
    assert EnvioAgendado.objects.count() == 0


def test_em_com_formato_impossivel_diz_os_formatos(alias_de_teste, tmp_path):
    with pytest.raises(CommandError) as erro:
        _chamar(
            "--alias", "financeiro", "--para", "c@x.com",
            "--corpo-arquivo", _corpo(tmp_path), "--em", "amanhã de manhã",
        )
    assert "2026-09-10 09:00" in str(erro.value)


def test_agendamento_pela_cli_guarda_o_marcador_intacto(alias_de_teste, tmp_path):
    quando = timezone.localtime() + timedelta(days=1)
    _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path, "<p>Bom dia, {{ hora }}</p>"),
        "--em", quando.strftime("%Y-%m-%d %H:%M"),
    )
    assert "{{ hora }}" in EnvioAgendado.objects.get().corpo_html


def test_anexo_agendado_pela_cli_fica_guardado(alias_de_teste, tmp_path, settings):
    from mensagens.anexos import listar_anexos

    settings.RASCUNHOS_DIR = tmp_path / "rascunhos"
    anexo = tmp_path / "contrato.pdf"
    anexo.write_bytes(b"conteudo")
    quando = timezone.localtime() + timedelta(days=1)

    _chamar(
        "--alias", "financeiro", "--para", "c@x.com",
        "--corpo-arquivo", _corpo(tmp_path), "--anexo", str(anexo),
        "--em", quando.strftime("%Y-%m-%d %H:%M"),
    )

    agendado = EnvioAgendado.objects.get()
    assert agendado.token_anexos
    assert len(listar_anexos(agendado.token_anexos)) == 1


def test_sem_assinatura_pela_linha_de_comando(alias_de_teste, tmp_path):
    alias_de_teste.assinatura_html = "<p>ASSINATURA-DO-ALIAS</p>"
    alias_de_teste.save()

    _chamar("--alias", "financeiro", "--para", "c@x.com", "--sem-assinatura",
            "--corpo-arquivo", _corpo(tmp_path, "<table><tr><td>pronto</td></tr></table>"))

    html = mail.outbox[0].alternatives[0][0]
    assert "pronto" in html
    assert "ASSINATURA-DO-ALIAS" not in html
