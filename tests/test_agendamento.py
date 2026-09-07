"""Envio programado: fila, trava de concorrência, retentativa e a limpeza.

O que este arquivo cobre não é "o agendamento funciona" — é o conjunto de
coisas que só dão errado quando ninguém está olhando, que é a diferença entre
este caminho e o da tela.
"""

import os
from datetime import timedelta
from smtplib import SMTPException

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from mensagens.agendamento import (
    agendar,
    cancelar,
    dados_de,
    despachar_pendentes,
    reivindicar,
    tokens_pendentes,
)
from mensagens.anexos import criar_token, limpar_rascunhos_expirados, listar_anexos, salvar_anexo
from mensagens.models import EnvioAgendado, RegistroEnvio
from mensagens.montagem import DadosRedacao

pytestmark = pytest.mark.django_db


def _dados(**extra):
    base = {"para": ["cliente@example.com"], "assunto": "Oi", "corpo_html": "<p>Olá</p>"}
    return DadosRedacao(**{**base, **extra})


def _quebrar_smtp(monkeypatch, deixar_aviso_passar=False):
    """Faz todo envio falhar. Com `deixar_aviso_passar`, o e-mail de aviso da
    própria falha continua saindo — senão não haveria como observá-lo."""
    original = mail.EmailMultiAlternatives.send

    def falso(self, *args, **kwargs):
        if deixar_aviso_passar and self.subject.startswith("[Emailing]"):
            return original(self, *args, **kwargs)
        raise SMTPException("smtp fora do ar")

    monkeypatch.setattr(mail.EmailMultiAlternatives, "send", falso)


# ---------------------------------------------------------------------------
# O que é guardado, e quando é resolvido
# ---------------------------------------------------------------------------


def test_guarda_o_corpo_do_editor_sem_sanitizar_nem_expandir(alias_de_teste):
    """O agendamento guarda a mensagem como ela foi escrita.

    Guardar o HTML já pronto seria uma segunda versão da verdade — a mesma razão
    pela qual a prévia não persiste rascunho.
    """
    quando = timezone.now() + timedelta(hours=2)
    agendado = agendar(
        alias_de_teste,
        _dados(corpo_html="<p>Bom dia, são &#123;&#123; hora &#125;&#125;</p><script>x</script>"),
        quando,
    )

    assert "{{ hora }}" not in agendado.corpo_html  # a entidade HTML não é o marcador
    assert "<script>x</script>" in agendado.corpo_html  # sanitiza no despacho, não aqui
    assert agendado.status == EnvioAgendado.Status.AGENDADO
    assert agendado.tentativas == 0


def test_marcador_de_hora_resolve_no_despacho_e_nao_no_agendamento(alias_de_teste):
    """É o ponto do desenho: a hora que interessa num agendamento é a da
    entrega. Cai pronto da separação autoral/final de `montagem.py`."""
    agendado = agendar(
        alias_de_teste, _dados(corpo_html="<p>Enviado em {{ data }}</p>"),
        timezone.now() - timedelta(minutes=1),
    )
    assert "{{ data }}" in agendado.corpo_html

    despachar_pendentes()

    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.ENVIADO
    hoje = timezone.localtime().strftime("%d/%m/%Y")
    assert hoje in mail.outbox[0].alternatives[0][0]
    # E o guardado continua com o marcador: se uma retentativa acontecesse
    # amanhã, ela diria "amanhã".
    assert "{{ data }}" in agendado.corpo_html


def test_ida_e_volta_pelo_banco_preserva_os_dados(alias_de_teste):
    original = _dados(
        para=["a@x.com", "Nome Com, Vírgula <b@x.com>"], cc=["c@x.com"], cco=["d@x.com"],
        assunto="Assunto", corpo_html="<p>oi</p>", citacao_html="<p>antes</p>",
        in_reply_to="<orig@x>", referencias="<a@x> <orig@x>",
    )
    agendado = agendar(alias_de_teste, original, timezone.now() + timedelta(days=1))
    agendado.refresh_from_db()

    assert dados_de(agendado) == original


# ---------------------------------------------------------------------------
# Despacho
# ---------------------------------------------------------------------------


def test_nao_despacha_antes_da_hora(alias_de_teste):
    agendar(alias_de_teste, _dados(), timezone.now() + timedelta(hours=1))

    assert despachar_pendentes() == []
    assert mail.outbox == []


def test_despacha_o_que_venceu_e_liga_ao_registro(alias_de_teste):
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=5))

    despachados = despachar_pendentes()

    assert len(despachados) == 1
    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.ENVIADO
    assert agendado.tentativas == 1
    assert agendado.erro == ""
    assert agendado.registro.status == RegistroEnvio.Status.ENVIADO
    assert len(mail.outbox) == 1


def test_respeita_o_teto_por_execucao(alias_de_teste):
    """O teto existe porque Hostinger e Titan contam saída por hora e por dia:
    um lote inteiro de uma vez volta como fileira de FALHOU, não como atraso."""
    for _ in range(3):
        agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=1))

    assert len(despachar_pendentes(limite=2)) == 2
    assert len(mail.outbox) == 2
    assert EnvioAgendado.objects.filter(status=EnvioAgendado.Status.AGENDADO).count() == 1


def test_reivindicar_e_ganho_por_um_processo_so(alias_de_teste):
    """A trava que a tela não precisa. Duas execuções de cron sobrepostas
    mandariam a mesma mensagem duas vezes."""
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=1))
    outra_leitura = EnvioAgendado.objects.get(pk=agendado.pk)

    assert reivindicar(agendado) is True
    assert reivindicar(outra_leitura) is False
    assert agendado.tentativas == 1  # o F() foi relido, não ficou desatualizado


def test_despacho_ignora_o_que_outra_execucao_ja_pegou(alias_de_teste):
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=1))
    reivindicar(agendado)  # como se outro processo tivesse pegado

    assert despachar_pendentes() == []
    assert mail.outbox == []


def test_alias_desativado_nao_manda_e_explica(alias_de_teste):
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=1))
    alias_de_teste.ativo = False
    alias_de_teste.save(update_fields=["ativo"])

    despachar_pendentes()

    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.FALHOU
    assert "inativo" in agendado.erro
    assert mail.outbox == []


def test_atraso_acima_da_tolerancia_nao_manda_mensagem_velha(alias_de_teste, settings):
    """Servidor fora do ar dois dias: disparar o acumulado ao voltar é pior do
    que não disparar. A mensagem foi escrita para um momento que já passou."""
    settings.AGENDADOS_TOLERANCIA_HORAS = 24
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(hours=48))

    despachar_pendentes()

    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.FALHOU
    assert "tolerância" in agendado.erro
    assert mail.outbox == []


def test_tolerancia_zero_manda_de_qualquer_jeito(alias_de_teste, settings):
    settings.AGENDADOS_TOLERANCIA_HORAS = 0
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(days=30))

    despachar_pendentes()

    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.ENVIADO


# ---------------------------------------------------------------------------
# Falha, retentativa e aviso
# ---------------------------------------------------------------------------


def test_falha_volta_para_a_fila_com_espera_crescente(alias_de_teste, settings, monkeypatch):
    settings.AGENDADOS_MAX_TENTATIVAS = 3
    settings.AGENDADOS_BACKOFF_MINUTOS = 5
    _quebrar_smtp(monkeypatch)
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=1))

    despachar_pendentes()
    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.AGENDADO
    assert agendado.tentativas == 1
    assert "smtp fora do ar" in agendado.erro
    # A espera conta do instante da falha, não do horário que estava marcado:
    # o que interessa é dar tempo ao provedor, não recuperar o atraso.
    assert timedelta(minutes=4) < agendado.enviar_em - timezone.now() < timedelta(minutes=6)

    despachar_pendentes(agora=agendado.enviar_em)
    agendado.refresh_from_db()
    assert agendado.tentativas == 2
    assert timedelta(minutes=9) < agendado.enviar_em - timezone.now() < timedelta(minutes=11)


def test_cada_tentativa_deixa_o_seu_registro(alias_de_teste, settings, monkeypatch):
    """`RegistroEnvio` é log de tentativas de envio. Três tentativas foram três
    tentativas — e o histórico tem que contar isso."""
    settings.AGENDADOS_MAX_TENTATIVAS = 2
    _quebrar_smtp(monkeypatch)
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=1))

    despachar_pendentes()
    agendado.refresh_from_db()
    despachar_pendentes(agora=agendado.enviar_em)

    assert RegistroEnvio.objects.count() == 2
    assert all(r.status == RegistroEnvio.Status.FALHOU for r in RegistroEnvio.objects.all())


def test_esgotadas_as_tentativas_desiste_e_avisa(alias_de_teste, settings, monkeypatch):
    settings.AGENDADOS_MAX_TENTATIVAS = 1
    settings.AGENDADOS_AVISAR_PARA = "eu@leonardocosta.dev"
    _quebrar_smtp(monkeypatch, deixar_aviso_passar=True)
    agendado = agendar(alias_de_teste, _dados(assunto="Proposta"), timezone.now())

    despachar_pendentes()

    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.FALHOU
    assert len(mail.outbox) == 1
    aviso = mail.outbox[0]
    assert aviso.to == ["eu@leonardocosta.dev"]
    assert f"#{agendado.pk}" in aviso.subject
    assert "Proposta" in aviso.alternatives[0][0]


def test_sem_endereco_de_aviso_nao_tenta_avisar(alias_de_teste, settings, monkeypatch):
    settings.AGENDADOS_MAX_TENTATIVAS = 1
    settings.AGENDADOS_AVISAR_PARA = ""
    _quebrar_smtp(monkeypatch, deixar_aviso_passar=True)
    agendar(alias_de_teste, _dados(), timezone.now())

    despachar_pendentes()

    assert mail.outbox == []


def test_aviso_que_nao_sai_nao_derruba_o_despacho(alias_de_teste, settings, monkeypatch):
    """Um aviso que falha não pode virar uma segunda falha em cascata."""
    settings.AGENDADOS_MAX_TENTATIVAS = 1
    settings.AGENDADOS_AVISAR_PARA = "eu@leonardocosta.dev"
    settings.AGENDADOS_AVISAR_ALIAS = "nao-existe"
    _quebrar_smtp(monkeypatch, deixar_aviso_passar=True)
    agendado = agendar(alias_de_teste, _dados(), timezone.now())

    despachar_pendentes()  # não levanta

    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.FALHOU


# ---------------------------------------------------------------------------
# Cancelamento
# ---------------------------------------------------------------------------


def test_cancelar_tira_da_fila_e_apaga_os_anexos(alias_de_teste, tmp_path, settings):
    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("nota.pdf", b"x"))
    agendado = agendar(
        alias_de_teste, _dados(), timezone.now() + timedelta(days=1), token_anexos=token
    )

    assert listar_anexos(agendado.token_anexos)  # tomou posse dos arquivos

    assert cancelar(agendado.pk) is True

    agendado.refresh_from_db()
    assert agendado.status == EnvioAgendado.Status.CANCELADO
    assert listar_anexos(agendado.token_anexos) == []


def test_cancelar_o_que_ja_saiu_devolve_falso(alias_de_teste):
    agendado = agendar(alias_de_teste, _dados(), timezone.now() - timedelta(minutes=1))
    despachar_pendentes()

    assert cancelar(agendado.pk) is False
    assert cancelar(9999) is False


# ---------------------------------------------------------------------------
# A armadilha: os anexos têm que sobreviver ao TTL do rascunho
# ---------------------------------------------------------------------------


def test_limpeza_preserva_anexo_de_agendamento_pendente(alias_de_teste, tmp_path, settings):
    """Sem isto, um agendamento para daqui a 10 dias passa do TTL de 7 e sai
    **sem os anexos, em silêncio** — porque `ler_anexos()` devolve `[]` para
    pasta inexistente em vez de falhar."""
    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("contrato.pdf", b"conteudo"))
    agendado = agendar(
        alias_de_teste, _dados(), timezone.now() + timedelta(days=10), token_anexos=token
    )

    # envelhece a pasta muito além do TTL
    antigo = timezone.now().timestamp() - 30 * 86400
    pasta = tmp_path / agendado.token_anexos
    for caminho in [pasta, *pasta.iterdir()]:
        os.utime(caminho, (antigo, antigo))

    assert limpar_rascunhos_expirados(7, tokens_pendentes()) == 0
    assert len(listar_anexos(agendado.token_anexos)) == 1


def test_limpeza_leva_rascunho_sem_agendamento(alias_de_teste, tmp_path, settings):
    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("solto.pdf", b"x"))
    antigo = timezone.now().timestamp() - 30 * 86400
    pasta = tmp_path / token
    for caminho in [pasta, *pasta.iterdir()]:
        os.utime(caminho, (antigo, antigo))

    assert limpar_rascunhos_expirados(7, tokens_pendentes()) == 1
    assert listar_anexos(token) == []


def test_anexo_agendado_chega_na_mensagem_e_e_limpo_no_despacho(
    alias_de_teste, tmp_path, settings
):
    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("nota.pdf", b"conteudo-pdf"))
    agendado = agendar(alias_de_teste, _dados(), timezone.now(), token_anexos=token)

    despachar_pendentes()

    assert len(mail.outbox[0].attachments) == 1
    assert mail.outbox[0].attachments[0][0] == "nota.pdf"
    assert listar_anexos(agendado.token_anexos) == []  # enviado → rascunho sai


def test_tokens_pendentes_ignora_o_que_ja_encerrou(alias_de_teste, tmp_path, settings):
    settings.RASCUNHOS_DIR = tmp_path
    vivos, mortos = criar_token(), criar_token()
    salvar_anexo(vivos, SimpleUploadedFile("a.pdf", b"x"))
    salvar_anexo(mortos, SimpleUploadedFile("b.pdf", b"x"))

    fica = agendar(
        alias_de_teste, _dados(), timezone.now() + timedelta(days=1), token_anexos=vivos
    )
    sai = agendar(
        alias_de_teste, _dados(), timezone.now() + timedelta(days=1), token_anexos=mortos
    )
    cancelar(sai.pk)

    assert tokens_pendentes() == [fica.token_anexos]


def test_dois_agendamentos_do_mesmo_rascunho_nao_dividem_a_pasta(
    alias_de_teste, tmp_path, settings
):
    """O caso que a transferência de token existe para matar: sem ela, o
    primeiro despacho apaga a pasta e o segundo sai sem anexo, em silêncio."""
    settings.RASCUNHOS_DIR = tmp_path
    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("contrato.pdf", b"conteudo"))

    primeiro = agendar(alias_de_teste, _dados(), timezone.now(), token_anexos=token)
    # o mesmo POST reenviado: a pasta original já mudou de dono
    segundo = agendar(alias_de_teste, _dados(), timezone.now(), token_anexos=token)

    assert primeiro.token_anexos != segundo.token_anexos
    assert len(listar_anexos(primeiro.token_anexos)) == 1
    # O segundo não fica com anexo — mas, crucialmente, também não rouba nem
    # apaga o do primeiro quando for despachado.
    assert segundo.token_anexos == ""

    despachar_pendentes()

    assert len(mail.outbox) == 2
    assert len(mail.outbox[0].attachments) == 1
