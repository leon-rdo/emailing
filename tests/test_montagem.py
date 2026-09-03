"""montar_email(): função pura, sem efeito colateral."""

import pytest

from mensagens.montagem import Anexo, DadosRedacao, calcular_hash_previa, montar_corpo, montar_email

pytestmark = pytest.mark.django_db

ASSINATURA = '<table style="width:500px"><tr><td style="color:red">Leonardo</td></tr></table>'


def test_from_e_envelope_sao_independentes(alias_de_teste):
    dados = DadosRedacao(para=["cliente@example.com"], assunto="Oi", corpo_html="<p>oi</p>")

    mensagem = montar_email(dados, alias_de_teste)

    # from_email é o envelope (MAIL FROM): bare address.
    assert mensagem.from_email == "financeiro@leonardocosta.dev"
    # O cabeçalho From: carrega o nome de exibição — os dois levers são
    # independentes no Django (extra_headers["From"] vence self.from_email).
    assert mensagem.extra_headers["From"] == "Leonardo Costa <financeiro@leonardocosta.dev>"


def test_e_multipart_alternative_com_texto_legivel(alias_de_teste):
    dados = DadosRedacao(
        para=["cliente@example.com"], assunto="Oi", corpo_html="<p><b>Olá</b>, tudo bem?</p>"
    )

    mensagem = montar_email(dados, alias_de_teste)

    assert mensagem.content_subtype == "plain"
    assert "Olá, tudo bem?" in mensagem.body
    assert mensagem.alternatives[0][1] == "text/html"
    assert "<b>Olá</b>" in mensagem.alternatives[0][0]


def test_corpo_e_sanitizado_mas_assinatura_nao(alias_de_teste):
    alias_de_teste.assinatura_html = ASSINATURA
    alias_de_teste.save()
    dados = DadosRedacao(para=["c@example.com"], corpo_html="<p>oi</p><script>alert(1)</script>")

    html_final, _ = montar_corpo(dados, alias_de_teste)

    assert "<script" not in html_final
    # A assinatura passou por fora do sanitizador: sai byte a byte como foi
    # cadastrada, sem o embutir de CSS nem a limpeza que o corpo leva.
    assert ASSINATURA in html_final


def test_sem_assinatura_nao_quebra(alias_de_teste):
    html_final, texto = montar_corpo(
        DadosRedacao(para=["c@x.com"], corpo_html="<p>oi</p>"), alias_de_teste
    )
    assert "oi" in html_final
    assert "oi" in texto


def test_citacao_entra_em_blockquote(alias_de_teste):
    dados = DadosRedacao(
        para=["c@x.com"], corpo_html="<p>resposta</p>", citacao_html="<p>original</p>"
    )
    html_final, _ = montar_corpo(dados, alias_de_teste)
    assert "<blockquote><p>original</p></blockquote>" in html_final
    assert html_final.index("resposta") < html_final.index("original")


def test_cabecalhos_de_thread_soh_quando_presentes(alias_de_teste):
    sem_thread = montar_email(DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias_de_teste)
    assert "In-Reply-To" not in sem_thread.extra_headers
    assert "References" not in sem_thread.extra_headers

    com_thread = montar_email(
        DadosRedacao(
            para=["c@x.com"], corpo_html="oi",
            in_reply_to="<orig@x>", referencias="<a@x> <orig@x>",
        ),
        alias_de_teste,
    )
    assert com_thread.extra_headers["In-Reply-To"] == "<orig@x>"
    assert com_thread.extra_headers["References"] == "<a@x> <orig@x>"


def test_message_id_soh_quando_passado(alias_de_teste):
    sem_id = montar_email(DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias_de_teste)
    assert "Message-ID" not in sem_id.extra_headers

    com_id = montar_email(
        DadosRedacao(para=["c@x.com"], corpo_html="oi"),
        alias_de_teste,
        message_id="<xyz@leonardocosta.dev>",
    )
    assert com_id.extra_headers["Message-ID"] == "<xyz@leonardocosta.dev>"


def test_reply_to_do_alias_e_usado(alias_de_teste):
    alias_de_teste.reply_to = "outro@leonardocosta.dev"
    alias_de_teste.save()
    mensagem = montar_email(DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias_de_teste)
    assert mensagem.reply_to == ["outro@leonardocosta.dev"]


def test_anexos_sao_anexados(alias_de_teste):
    anexo = Anexo(nome="nota.pdf", conteudo=b"%PDF-1.4 conteudo", tipo="application/pdf")
    mensagem = montar_email(
        DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias_de_teste, anexos=[anexo]
    )
    assert len(mensagem.attachments) == 1
    assert mensagem.attachments[0][0] == "nota.pdf"


def test_e_realmente_pura_mesma_entrada_mesma_saida(alias_de_teste):
    dados = DadosRedacao(para=["c@x.com"], assunto="X", corpo_html="<p>oi</p>")
    m1 = montar_email(dados, alias_de_teste)
    m2 = montar_email(dados, alias_de_teste)
    assert m1.body == m2.body
    assert m1.alternatives[0][0] == m2.alternatives[0][0]
    assert m1.extra_headers["From"] == m2.extra_headers["From"]


def test_hash_previa_muda_com_o_conteudo(alias_de_teste):
    dados = DadosRedacao(para=["c@x.com"])
    a = calcular_hash_previa(dados, alias_de_teste, "<p>um</p>")
    b = calcular_hash_previa(dados, alias_de_teste, "<p>dois</p>")
    assert a != b
    assert a == calcular_hash_previa(dados, alias_de_teste, "<p>um</p>")


def test_hash_previa_muda_com_os_anexos(alias_de_teste):
    dados = DadosRedacao(para=["c@x.com"])
    sem_anexo = calcular_hash_previa(dados, alias_de_teste, "<p>x</p>", [])
    com_anexo = calcular_hash_previa(dados, alias_de_teste, "<p>x</p>", ["id-1"])
    assert sem_anexo != com_anexo
    # Ordem não importa: mesmos anexos em ordem diferente dão o mesmo hash.
    ordem_a = calcular_hash_previa(dados, alias_de_teste, "<p>x</p>", ["a", "b"])
    ordem_b = calcular_hash_previa(dados, alias_de_teste, "<p>x</p>", ["b", "a"])
    assert ordem_a == ordem_b


def test_hash_previa_muda_com_o_destinatario(alias_de_teste):
    """O hash tem que cobrir para/cc/cco/assunto, não só o corpo — trocar o
    destinatário depois de pré-visualizar não pode passar despercebido."""
    html = "<p>x</p>"
    para_a = calcular_hash_previa(DadosRedacao(para=["a@x.com"]), alias_de_teste, html)
    para_b = calcular_hash_previa(DadosRedacao(para=["b@x.com"]), alias_de_teste, html)
    assert para_a != para_b

    mesmo_para_assunto_muda = calcular_hash_previa(
        DadosRedacao(para=["a@x.com"], assunto="Um"), alias_de_teste, html
    )
    assert mesmo_para_assunto_muda != para_a
