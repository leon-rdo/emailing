"""O servidor MCP: as tools são finas, e o que se prova aqui é que elas não
viraram um segundo app — mesma validação da tela, mesmo `RegistroEnvio`,
threading calculado no servidor — e que as proteções próprias do MCP (teto por
sessão, anotações de escrita, conteúdo externo marcado) existem.

As tools são chamadas direto (o decorador devolve a função embrulhada, que já
traduz erro de domínio em `ToolError`). Um teste no fim passa pelo cliente MCP
de verdade, em memória, para provar a ligação: worker thread, banco, schema.
"""

import asyncio
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from imap_falso import mensagem_de_exemplo
from mcp.server.mcpserver.exceptions import ToolError

from mensagens import mcp_servidor as m
from mensagens.models import EnvioAgendado, RegistroEnvio

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _cota_zerada():
    m.zerar_cota()
    yield
    m.zerar_cota()


def _daqui_a(horas=2):
    return timezone.localtime(timezone.now() + timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


def test_listar_aliases(alias_de_teste, imap):
    resultado = m.listar_aliases()
    assert resultado["aliases"][0]["slug"] == "financeiro"
    assert resultado["aliases"][0]["caixa"] == "me@empresa.example"
    assert resultado["caixas"] == [
        {"caixa": "me@empresa.example", "nome": "Conta de teste", "recebimento": True}
    ]


def test_conferir_nao_envia_e_nao_exige_destinatario(alias_de_teste):
    resultado = m.conferir_email(alias="financeiro", assunto="Oi", corpo_html="<p>Olá</p>")
    assert resultado["acao"] == "conferir"
    assert "Olá" in resultado["html"]
    assert resultado["para"] == []
    assert mail.outbox == []
    assert not RegistroEnvio.objects.exists()


def test_conferir_recusa_endereco_invalido(alias_de_teste):
    with pytest.raises(ToolError, match="para"):
        m.conferir_email(alias="financeiro", para=["cliente@exe"], corpo_html="<p>x</p>")


def test_buscar_e_ler_pela_caixa_ou_pelo_alias(alias_de_teste, imap):
    imap.entregar(mensagem_de_exemplo())

    por_alias = m.buscar_emails(caixa="financeiro")
    por_caixa = m.buscar_emails(caixa="me@empresa.example")
    assert por_alias["mensagens"] == por_caixa["mensagens"]
    item = por_alias["mensagens"][0]
    assert item["assunto"] == "Proposta de parceria"

    assert por_alias["ordem"] == "data"

    lida = m.ler_email(id=item["id"])
    assert lida["conteudo_externo"] is True
    assert lida["links_encurtados"] == 0
    assert lida["corpo"].startswith("Olá, segue a proposta.")
    assert lida["anexos"] == [
        {"nome": "proposta.pdf", "tipo": "application/pdf", "tamanho": 14}
    ]
    assert lida["lida"] is False
    assert all("\\Seen" not in d["flags"] for d in imap.pastas["INBOX"].values())


def test_caixa_desconhecida_explica(alias_de_teste):
    with pytest.raises(ToolError, match="listar_aliases"):
        m.buscar_emails(caixa="ninguem")


def test_historico_e_listar_agendados(alias_de_teste):
    m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html="<p>a</p>")
    m.agendar_email(alias="financeiro", em=_daqui_a(), para=["c@x.com"], corpo_html="<p>b</p>")
    assert m.historico()["envios"][0]["status"] == "enviado"
    assert m.listar_agendados()["mensagens"][0]["status"] == "agendado"


# ---------------------------------------------------------------------------
# Envio: o mesmo caminho da tela
# ---------------------------------------------------------------------------


def test_enviar_passa_pelo_mesmo_registro(alias_de_teste):
    resultado = m.enviar_email(
        alias="financeiro", para=["cliente@example.com"], assunto="Proposta",
        corpo_html="<p>Olá</p>",
    )
    assert resultado["ok"] is True
    assert mail.outbox[0].to == ["cliente@example.com"]
    registro = RegistroEnvio.objects.get()
    assert registro.status == RegistroEnvio.Status.ENVIADO
    assert resultado["message_id"] == registro.message_id


def test_enviar_sem_destinatario_e_erro_do_formulario(alias_de_teste):
    with pytest.raises(ToolError, match="para"):
        m.enviar_email(alias="financeiro", corpo_html="<p>x</p>")
    assert mail.outbox == []


def test_alias_desconhecido_lista_os_disponiveis(alias_de_teste):
    with pytest.raises(ToolError, match="Disponíveis: financeiro"):
        m.enviar_email(alias="nao-existe", para=["c@x.com"])


def test_falha_de_smtp_vira_erro_com_o_registro(alias_de_teste, monkeypatch):
    from smtplib import SMTPException

    def recusar(self):
        raise SMTPException("550 recusado")

    monkeypatch.setattr("django.core.mail.EmailMultiAlternatives.send", recusar)
    with pytest.raises(ToolError, match="550 recusado"):
        m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html="<p>x</p>")
    assert RegistroEnvio.objects.get().status == RegistroEnvio.Status.FALHOU


def test_responder_a_calcula_o_encadeamento_no_servidor(alias_de_teste, imap):
    imap.entregar(mensagem_de_exemplo())
    id_ = m.buscar_emails(caixa="financeiro")["mensagens"][0]["id"]

    m.enviar_email(alias="financeiro", corpo_html="<p>Recebido, obrigado.</p>", responder_a=id_)

    enviada = mail.outbox[0]
    assert enviada.to == ["Cliente <cliente@exemplo.test>"]
    assert enviada.subject == "Re: Proposta de parceria"
    assert enviada.extra_headers["In-Reply-To"] == "<original@exemplo.test>"
    assert enviada.extra_headers["References"] == (
        "<primeira@exemplo.test> <original@exemplo.test>"
    )
    assert "segue a" in enviada.alternatives[0][0]  # a citação foi junto


def test_responder_sem_citar(alias_de_teste, imap):
    imap.entregar(mensagem_de_exemplo())
    id_ = m.buscar_emails(caixa="financeiro")["mensagens"][0]["id"]
    m.enviar_email(alias="financeiro", corpo_html="<p>ok</p>", responder_a=id_, citar=False)
    assert "segue a" not in mail.outbox[0].alternatives[0][0]


# ---------------------------------------------------------------------------
# Teto da sessão
# ---------------------------------------------------------------------------


def test_teto_por_sessao(alias_de_teste, settings):
    settings.MCP_MAX_ENVIOS_POR_SESSAO = 2
    m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html="<p>1</p>")
    m.agendar_email(alias="financeiro", em=_daqui_a(), para=["c@x.com"], corpo_html="<p>2</p>")

    with pytest.raises(ToolError, match="Teto de 2"):
        m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html="<p>3</p>")
    assert len(mail.outbox) == 1


def test_erro_de_validacao_nao_gasta_a_cota(alias_de_teste, settings):
    settings.MCP_MAX_ENVIOS_POR_SESSAO = 1
    with pytest.raises(ToolError):
        m.enviar_email(alias="financeiro", para=["torto@"], corpo_html="<p>x</p>")
    m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html="<p>x</p>")
    assert len(mail.outbox) == 1


def test_teto_zero_desliga_envio_mas_nao_rascunho(alias_de_teste, settings):
    settings.MCP_MAX_ENVIOS_POR_SESSAO = 0
    with pytest.raises(ToolError, match="desligado"):
        m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html="<p>x</p>")
    assert m.salvar_rascunho(alias="financeiro", corpo_html="<p>x</p>")["ok"] is True


# ---------------------------------------------------------------------------
# Agendar, rascunho, cancelar
# ---------------------------------------------------------------------------


def test_agendar(alias_de_teste):
    resultado = m.agendar_email(
        alias="financeiro", em=_daqui_a(), para=["c@x.com"], corpo_html="<p>{{ hora }}</p>"
    )
    agendado = EnvioAgendado.objects.get(pk=resultado["agendado"])
    assert agendado.status == EnvioAgendado.Status.AGENDADO
    assert "{{ hora }}" in agendado.corpo_html  # corpo cru: expande no despacho
    assert mail.outbox == []


def test_agendar_no_passado_explica_com_o_nome_do_campo(alias_de_teste):
    with pytest.raises(ToolError, match="em: .*já passou"):
        m.agendar_email(alias="financeiro", em="2020-01-01 09:00", para=["c@x.com"])


def test_rascunho_sem_destinatario(alias_de_teste):
    resultado = m.salvar_rascunho(alias="financeiro", assunto="Depois", corpo_html="<p>x</p>")
    rascunho = EnvioAgendado.objects.get(pk=resultado["rascunho"])
    assert rascunho.status == EnvioAgendado.Status.RASCUNHO
    assert resultado["tela"] == f"/mensagens/{rascunho.pk}/editar/"


def test_cancelar(alias_de_teste):
    pk = m.agendar_email(
        alias="financeiro", em=_daqui_a(), para=["c@x.com"], corpo_html="<p>x</p>"
    )["agendado"]
    assert m.cancelar_agendado(id=pk) == {"ok": True, "cancelado": pk}
    with pytest.raises(ToolError, match="não está na fila \\(status: cancelado\\)"):
        m.cancelar_agendado(id=pk)
    with pytest.raises(ToolError, match="não existe"):
        m.cancelar_agendado(id=9999)


# ---------------------------------------------------------------------------
# Escrita na caixa
# ---------------------------------------------------------------------------


def test_marcar_e_mover(alias_de_teste, imap):
    imap.criar_pasta("Arquivo")
    imap.entregar(mensagem_de_exemplo())
    id_ = m.buscar_emails(caixa="financeiro")["mensagens"][0]["id"]

    assert m.marcar_email(id=id_, lida=True)["lida"] is True
    assert m.mover_email(id=id_, destino="Arquivo") == {
        "ok": True, "de": "INBOX", "para": "Arquivo"
    }
    assert m.buscar_emails(caixa="financeiro")["total"] == 0
    assert m.buscar_emails(caixa="financeiro", pasta="Arquivo")["total"] == 1


# ---------------------------------------------------------------------------
# Pelo protocolo
# ---------------------------------------------------------------------------


def _pelo_cliente(corrotina):
    from mcp import Client

    async def rodar():
        async with Client(m.servidor) as cliente:
            return await corrotina(cliente)

    return asyncio.run(rodar())


def test_anotacoes_separam_leitura_de_escrita(db):
    ferramentas = _pelo_cliente(lambda c: c.list_tools()).tools
    por_nome = {f.name: f.annotations for f in ferramentas}

    leitura = {"listar_aliases", "listar_pastas", "buscar_emails", "ler_email",
               "conferir_email", "listar_agendados", "historico", "ler_agendado"}
    escrita = {"enviar_email", "agendar_email", "salvar_rascunho", "cancelar_agendado",
               "marcar_email", "mover_email", "editar_mensagem", "agendar_rascunho",
               "tirar_da_fila", "descartar_rascunho"}
    assert set(por_nome) == leitura | escrita
    assert all(por_nome[n].read_only_hint is True for n in leitura)
    assert all(por_nome[n].read_only_hint is False for n in escrita)
    for nome in ("enviar_email", "editar_mensagem", "agendar_rascunho", "descartar_rascunho"):
        assert por_nome[nome].destructive_hint is True, nome


@pytest.mark.django_db(transaction=True)
def test_chamada_pelo_protocolo_roda_o_orm_na_worker_thread(alias_de_teste):
    """Se a tool rodasse no event loop, o ORM levantaria SynchronousOnlyOperation."""
    async def chamar(cliente):
        ok = await cliente.call_tool("listar_aliases", {})
        erro = await cliente.call_tool("enviar_email", {"alias": "nao-existe", "para": ["c@x"]})
        return ok, erro

    ok, erro = _pelo_cliente(chamar)
    assert ok.is_error is False
    assert ok.structured_content["aliases"][0]["slug"] == "financeiro"
    assert erro.is_error is True
    assert "Alias desconhecido" in erro.content[0].text


# ---------------------------------------------------------------------------
# Assinatura opcional
# ---------------------------------------------------------------------------


@pytest.fixture
def com_assinatura(alias_de_teste):
    alias_de_teste.assinatura_html = "<p>ASSINATURA-DO-ALIAS</p>"
    alias_de_teste.save()
    return alias_de_teste


def test_enviar_e_conferir_sem_assinatura(com_assinatura):
    corpo = "<table><tr><td>HTML pronto</td></tr></table>"
    conferido = m.conferir_email(alias="financeiro", corpo_html=corpo, assinatura=False)
    assert conferido["assinatura"] is False
    assert "ASSINATURA-DO-ALIAS" not in conferido["html"]

    m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html=corpo, assinatura=False)
    assert "ASSINATURA-DO-ALIAS" not in mail.outbox[0].alternatives[0][0]

    m.enviar_email(alias="financeiro", para=["c@x.com"], corpo_html="<p>normal</p>")
    assert "ASSINATURA-DO-ALIAS" in mail.outbox[1].alternatives[0][0]


def test_rascunho_e_agendado_guardam_a_escolha(com_assinatura):
    r = m.salvar_rascunho(alias="financeiro", corpo_html="<p>x</p>", assinatura=False)
    a = m.agendar_email(alias="financeiro", em=_daqui_a(), para=["c@x.com"],
                        corpo_html="<p>x</p>", assinatura=False)
    assert EnvioAgendado.objects.get(pk=r["rascunho"]).assinatura is False
    assert EnvioAgendado.objects.get(pk=a["agendado"]).assinatura is False
    assert all(x["assinatura"] is False for x in m.listar_agendados(status="todos")["mensagens"])


def test_teto_padrao_e_50():
    from django.conf import settings

    assert settings.MCP_MAX_ENVIOS_POR_SESSAO == 50


# ---------------------------------------------------------------------------
# Editar agendados e rascunhos
# ---------------------------------------------------------------------------


@pytest.fixture
def anexos_em(tmp_path, settings):
    settings.RASCUNHOS_DIR = tmp_path
    return tmp_path


def _agendado_com_anexo(alias):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from mensagens.agendamento import agendar
    from mensagens.anexos import criar_token, salvar_anexo
    from mensagens.montagem import DadosRedacao

    token = criar_token()
    salvar_anexo(token, SimpleUploadedFile("contrato.pdf", b"conteudo"))
    dados = DadosRedacao(para=["a@x.com"], cc=["b@x.com"], assunto="Original",
                         corpo_html="<p>texto original</p>")
    return agendar(alias, dados, timezone.now() + timedelta(days=1), token_anexos=token)


def _nomes_dos_anexos(linha):
    from mensagens.anexos import listar_anexos

    return [a.nome for a in listar_anexos(linha.token_anexos)]


def test_ler_agendado_traz_o_conteudo_completo(alias_de_teste, anexos_em):
    agendado = _agendado_com_anexo(alias_de_teste)
    lido = m.ler_agendado(id=agendado.pk)
    assert lido["status"] == "agendado" and lido["editavel"] is True
    assert lido["corpo_html"] == "<p>texto original</p>"
    assert lido["cc"] == ["b@x.com"]
    assert lido["assinatura"] is True
    assert [a["nome"] for a in lido["anexos"]] == ["contrato.pdf"]
    with pytest.raises(ToolError, match="não existe"):
        m.ler_agendado(id=9999)


def test_editar_agendado_muda_so_o_que_foi_passado_e_preserva_anexos(
    alias_de_teste, anexos_em
):
    agendado = _agendado_com_anexo(alias_de_teste)
    token_antigo = agendado.token_anexos
    nova_data = _daqui_a(horas=48)

    resultado = m.editar_mensagem(id=agendado.pk, assunto="Corrigido", em=nova_data,
                                  assinatura=False)

    agendado.refresh_from_db()
    assert resultado["status"] == agendado.status == "agendado"
    assert agendado.assunto == "Corrigido"
    assert agendado.assinatura is False
    assert agendado.para == ["a@x.com"] and agendado.cc == ["b@x.com"]  # não passados
    assert agendado.corpo_html == "<p>texto original</p>"
    assert timezone.localtime(agendado.enviar_em).strftime("%Y-%m-%d %H:%M") == nova_data
    assert _nomes_dos_anexos(agendado) == ["contrato.pdf"]
    assert agendado.token_anexos != token_antigo  # a cópia virou a pasta da mensagem
    assert not (anexos_em / token_antigo).exists()


def test_editar_rascunho_aceita_lista_vazia_e_apaga_data_provisoria(alias_de_teste):
    r = m.salvar_rascunho(alias="financeiro", para=["a@x.com"], corpo_html="<p>x</p>",
                          em="2026-12-01 09:00")
    m.editar_mensagem(id=r["rascunho"], para=[], em="")
    rascunho = EnvioAgendado.objects.get(pk=r["rascunho"])
    assert rascunho.status == "rascunho"
    assert rascunho.para == [] and rascunho.enviar_em is None


def test_editar_agendado_valida_como_envio(alias_de_teste, anexos_em):
    agendado = _agendado_com_anexo(alias_de_teste)
    with pytest.raises(ToolError, match="para"):
        m.editar_mensagem(id=agendado.pk, para=[])
    with pytest.raises(ToolError, match="tirar_da_fila"):
        m.editar_mensagem(id=agendado.pk, em="")
    with pytest.raises(ToolError, match="já passou"):
        m.editar_mensagem(id=agendado.pk, em="2020-01-01 09:00")

    EnvioAgendado.objects.filter(pk=agendado.pk).update(
        enviar_em=timezone.now() - timedelta(minutes=5)
    )
    with pytest.raises(ToolError, match="já passou; informe uma nova"):
        m.editar_mensagem(id=agendado.pk, assunto="sem data nova")
    agendado.refresh_from_db()
    assert agendado.assunto == "Original"


def test_editar_perdendo_a_corrida_nao_salva_nem_apaga_os_anexos(
    alias_de_teste, anexos_em, monkeypatch
):
    """O cron reivindica a mensagem entre a leitura e a gravação."""
    agendado = _agendado_com_anexo(alias_de_teste)
    original = m.preparar

    def cron_no_meio(*args, **kwargs):
        EnvioAgendado.objects.filter(pk=agendado.pk).update(status="enviando")
        return original(*args, **kwargs)

    monkeypatch.setattr(m, "preparar", cron_no_meio)
    with pytest.raises(ToolError, match="mudou de estado.*Nada foi salvo"):
        m.editar_mensagem(id=agendado.pk, assunto="tarde demais")

    agendado.refresh_from_db()
    assert agendado.assunto == "Original"
    assert _nomes_dos_anexos(agendado) == ["contrato.pdf"]  # o despacho ainda os tem


def test_encerrado_nao_se_edita(alias_de_teste, anexos_em):
    agendado = _agendado_com_anexo(alias_de_teste)
    m.cancelar_agendado(id=agendado.pk)
    with pytest.raises(ToolError, match="status cancelado"):
        m.editar_mensagem(id=agendado.pk, assunto="x")


def test_tirar_da_fila_e_agendar_de_novo(alias_de_teste, anexos_em, settings):
    agendado = _agendado_com_anexo(alias_de_teste)
    data = agendado.enviar_em

    m.tirar_da_fila(id=agendado.pk)
    agendado.refresh_from_db()
    assert agendado.status == "rascunho" and agendado.enviar_em == data
    assert _nomes_dos_anexos(agendado) == ["contrato.pdf"]

    settings.MCP_MAX_ENVIOS_POR_SESSAO = 1
    resultado = m.agendar_rascunho(id=agendado.pk)  # a data provisória ainda é futura
    agendado.refresh_from_db()
    assert resultado["agendado"] == agendado.pk and agendado.status == "agendado"
    assert agendado.enviar_em == data
    with pytest.raises(ToolError, match="Teto de 1"):  # agendar conta no teto
        m.agendar_email(alias="financeiro", em=_daqui_a(), para=["c@x.com"])


def test_agendar_rascunho_exige_destinatario_e_data(alias_de_teste):
    r = m.salvar_rascunho(alias="financeiro", corpo_html="<p>x</p>")
    with pytest.raises(ToolError, match="data no futuro"):
        m.agendar_rascunho(id=r["rascunho"])
    with pytest.raises(ToolError, match="para"):
        m.agendar_rascunho(id=r["rascunho"], em=_daqui_a())
    assert EnvioAgendado.objects.get(pk=r["rascunho"]).status == "rascunho"


def test_descartar_so_rascunho(alias_de_teste, anexos_em):
    r = m.salvar_rascunho(alias="financeiro", corpo_html="<p>x</p>")
    assert m.descartar_rascunho(id=r["rascunho"]) == {"ok": True, "descartado": r["rascunho"]}
    assert not EnvioAgendado.objects.filter(pk=r["rascunho"]).exists()

    agendado = _agendado_com_anexo(alias_de_teste)
    with pytest.raises(ToolError, match="não é rascunho"):
        m.descartar_rascunho(id=agendado.pk)
