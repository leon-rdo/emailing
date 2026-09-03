"""montar_email(): função pura, sem efeito colateral."""

from django.test import override_settings

from mensagens.aliases import alias_por_slug
from mensagens.montagem import Anexo, DadosRedacao, calcular_hash_previa, montar_corpo, montar_email

DOMINIOS = override_settings(ALIAS_ALLOWED_DOMAINS=["leonardocosta.dev"])
BASE = {
    "SMTP_USER": "me@leonardocosta.dev",
    "SMTP_PASSWORD": "segredo",
    "ALIASES": "financeiro",
    "ALIAS_FINANCEIRO_ADDRESS": "financeiro@leonardocosta.dev",
    "ALIAS_FINANCEIRO_NAME": "Leonardo Costa",
}


@DOMINIOS
def test_from_e_envelope_sao_independentes(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(para=["cliente@example.com"], assunto="Oi", corpo_html="<p>oi</p>")

    mensagem = montar_email(dados, alias)

    # from_email é o envelope (MAIL FROM): bare address.
    assert mensagem.from_email == "financeiro@leonardocosta.dev"
    # O cabeçalho From: carrega o nome de exibição — os dois levers são
    # independentes no Django (extra_headers["From"] vence self.from_email).
    assert mensagem.extra_headers["From"] == "Leonardo Costa <financeiro@leonardocosta.dev>"


@DOMINIOS
def test_e_multipart_alternative_com_texto_legivel(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(
        para=["cliente@example.com"], assunto="Oi", corpo_html="<p><b>Olá</b>, tudo bem?</p>"
    )

    mensagem = montar_email(dados, alias)

    assert mensagem.content_subtype == "plain"
    assert "Olá, tudo bem?" in mensagem.body
    assert mensagem.alternatives[0][1] == "text/html"
    assert "<b>Olá</b>" in mensagem.alternatives[0][0]


@DOMINIOS
def test_corpo_e_sanitizado_mas_assinatura_nao(ambiente_de_aliases, tmp_path, settings):
    settings.SIGNATURES_DIR = tmp_path
    (tmp_path / "financeiro.html").write_text(
        '<table style="width:500px"><tr><td style="color:red">Leonardo</td></tr></table>'
    )
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(
        para=["c@example.com"], corpo_html="<p>oi</p><script>alert(1)</script>"
    )

    html_final, _ = montar_corpo(dados, alias)

    assert "<script" not in html_final
    # A assinatura passou por fora do sanitizador: o estilo inline sobrevive
    # byte a byte, mesmo sem "style" estar liberado explicitamente para <td>
    # nessa chamada específica (é o corpo que é filtrado, não a assinatura).
    assert '<td style="color:red">Leonardo</td>' in html_final


@DOMINIOS
def test_sem_assinatura_nao_quebra(ambiente_de_aliases, tmp_path, settings):
    settings.SIGNATURES_DIR = tmp_path  # diretório vazio, sem <slug>.html
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    html_final, texto = montar_corpo(DadosRedacao(para=["c@x.com"], corpo_html="<p>oi</p>"), alias)
    assert "oi" in html_final
    assert "oi" in texto


@DOMINIOS
def test_citacao_entra_em_blockquote(ambiente_de_aliases, tmp_path, settings):
    settings.SIGNATURES_DIR = tmp_path
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(
        para=["c@x.com"], corpo_html="<p>resposta</p>", citacao_html="<p>original</p>"
    )
    html_final, _ = montar_corpo(dados, alias)
    assert "<blockquote><p>original</p></blockquote>" in html_final
    assert html_final.index("resposta") < html_final.index("original")


@DOMINIOS
def test_cabecalhos_de_thread_soh_quando_presentes(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    sem_thread = montar_email(DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias)
    assert "In-Reply-To" not in sem_thread.extra_headers
    assert "References" not in sem_thread.extra_headers

    com_thread = montar_email(
        DadosRedacao(
            para=["c@x.com"], corpo_html="oi",
            in_reply_to="<orig@x>", referencias="<a@x> <orig@x>",
        ),
        alias,
    )
    assert com_thread.extra_headers["In-Reply-To"] == "<orig@x>"
    assert com_thread.extra_headers["References"] == "<a@x> <orig@x>"


@DOMINIOS
def test_message_id_soh_quando_passado(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    sem_id = montar_email(DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias)
    assert "Message-ID" not in sem_id.extra_headers

    com_id = montar_email(
        DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias, message_id="<xyz@leonardocosta.dev>"
    )
    assert com_id.extra_headers["Message-ID"] == "<xyz@leonardocosta.dev>"


@DOMINIOS
def test_reply_to_do_alias_e_usado(ambiente_de_aliases):
    ambiente_de_aliases(**BASE, ALIAS_FINANCEIRO_REPLY_TO="outro@leonardocosta.dev")
    alias = alias_por_slug("financeiro")
    mensagem = montar_email(DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias)
    assert mensagem.reply_to == ["outro@leonardocosta.dev"]


@DOMINIOS
def test_anexos_sao_anexados(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    anexo = Anexo(nome="nota.pdf", conteudo=b"%PDF-1.4 conteudo", tipo="application/pdf")
    mensagem = montar_email(
        DadosRedacao(para=["c@x.com"], corpo_html="oi"), alias, anexos=[anexo]
    )
    assert len(mensagem.attachments) == 1
    assert mensagem.attachments[0][0] == "nota.pdf"


@DOMINIOS
def test_e_realmente_pura_mesma_entrada_mesma_saida(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(para=["c@x.com"], assunto="X", corpo_html="<p>oi</p>")
    m1 = montar_email(dados, alias)
    m2 = montar_email(dados, alias)
    assert m1.body == m2.body
    assert m1.alternatives[0][0] == m2.alternatives[0][0]
    assert m1.extra_headers["From"] == m2.extra_headers["From"]


@DOMINIOS
def test_hash_previa_muda_com_o_conteudo(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(para=["c@x.com"])
    a = calcular_hash_previa(dados, alias, "<p>um</p>")
    b = calcular_hash_previa(dados, alias, "<p>dois</p>")
    assert a != b
    assert a == calcular_hash_previa(dados, alias, "<p>um</p>")


@DOMINIOS
def test_hash_previa_muda_com_os_anexos(ambiente_de_aliases):
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    dados = DadosRedacao(para=["c@x.com"])
    sem_anexo = calcular_hash_previa(dados, alias, "<p>x</p>", [])
    com_anexo = calcular_hash_previa(dados, alias, "<p>x</p>", ["id-1"])
    assert sem_anexo != com_anexo
    # Ordem não importa: mesmos anexos em ordem diferente dão o mesmo hash.
    ordem_a = calcular_hash_previa(dados, alias, "<p>x</p>", ["a", "b"])
    ordem_b = calcular_hash_previa(dados, alias, "<p>x</p>", ["b", "a"])
    assert ordem_a == ordem_b


@DOMINIOS
def test_hash_previa_muda_com_o_destinatario(ambiente_de_aliases):
    """O hash tem que cobrir para/cc/cco/assunto, não só o corpo — trocar o
    destinatário depois de pré-visualizar não pode passar despercebido."""
    ambiente_de_aliases(**BASE)
    alias = alias_por_slug("financeiro")
    html = "<p>x</p>"
    para_a = calcular_hash_previa(DadosRedacao(para=["a@x.com"]), alias, html)
    para_b = calcular_hash_previa(DadosRedacao(para=["b@x.com"]), alias, html)
    assert para_a != para_b

    mesmo_para_assunto_muda = calcular_hash_previa(
        DadosRedacao(para=["a@x.com"], assunto="Um"), alias, html
    )
    assert mesmo_para_assunto_muda != para_a
