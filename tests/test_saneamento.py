"""limpar_html() e html_para_texto()."""

from mensagens.saneamento import embutir_css, html_para_texto, limpar_html

TEMPLATE_COM_FOLHA_DE_ESTILO = """<!DOCTYPE html><html><head><style>
.cartao { background-color: #f0f4ff; padding: 20px; }
.botao { display: inline-block; background: #667eea; padding: 14px 32px; }
@media (max-width: 600px) { .cartao { padding: 10px; } }
</style></head><body>
<div class="cartao"><h1>Título</h1></div>
<a href="https://exemplo.com" class="botao">Clique</a>
</body></html>"""


# --- CSS de folha vira estilo inline (senão o e-mail chega sem formatação) ---


def test_css_da_folha_vira_estilo_inline():
    limpo = limpar_html(TEMPLATE_COM_FOLHA_DE_ESTILO)
    assert 'class="cartao"' in limpo
    assert "background-color: #f0f4ff" in limpo
    assert "padding: 20px" in limpo
    assert "padding: 14px 32px" in limpo  # o link também recebeu o estilo


def test_media_query_sobrevive_no_style():
    """@media não tem como virar inline — o <style> tem que sobreviver."""
    limpo = limpar_html(TEMPLATE_COM_FOLHA_DE_ESTILO)
    assert "<style" in limpo
    assert "@media" in limpo


def test_script_continua_removido_mesmo_com_style_liberado():
    limpo = limpar_html("<style>.a{color:red}</style><p>ok</p><script>alert(1)</script>")
    assert "alert" not in limpo
    assert "<style" in limpo
    assert "<p>ok</p>" in limpo


def test_css_malformado_nao_derruba_o_envio():
    """Um CSS quebrado não pode impedir o e-mail de ser montado."""
    quebrado = "<style>.a { color: ;;; @@@ }</style><p>corpo</p>"
    assert "corpo" in limpar_html(quebrado)


def test_embutir_css_e_idempotente_com_html_simples():
    """O caso comum (texto do Trix, sem folha de estilo) passa incólume."""
    assert "negrito" in embutir_css("<div><strong>negrito</strong></div>")


def test_estilo_inline_do_autor_e_preservado():
    # <td> precisa estar dentro de <table>: solto, o parser HTML5 descarta a
    # tag órfã (comportamento de parser, não do sanitizador).
    limpo = limpar_html('<table><tr><td style="color:red" bgcolor="#fff">x</td></tr></table>')
    assert "color:red" in limpo or "color: red" in limpo
    assert "bgcolor" in limpo


def test_texto_simples_nao_leva_o_css_junto():
    """O conteúdo do <style> é código, não texto: não pode vazar para a
    parte text/plain do e-mail."""
    texto = html_para_texto(limpar_html(TEMPLATE_COM_FOLHA_DE_ESTILO))
    assert "background-color" not in texto
    assert "@media" not in texto
    assert "Título" in texto
    assert "Clique" in texto


def test_mantem_formatacao_basica():
    assert limpar_html("<p><b>negrito</b> e <i>itálico</i></p>") == (
        "<p><b>negrito</b> e <i>itálico</i></p>"
    )


def test_remove_script():
    limpo = limpar_html("<p>oi</p><script>alert(1)</script>")
    assert "<script" not in limpo
    assert "alert" not in limpo


def test_remove_manipulador_de_evento_em_atributo():
    limpo = limpar_html('<img src="x.png" onerror="alert(1)">')
    assert "onerror" not in limpo
    assert 'src="x.png"' in limpo


def test_remove_iframe_object_form():
    limpo = limpar_html("<iframe src='x'></iframe><object></object><form></form>texto")
    assert "<iframe" not in limpo
    assert "<object" not in limpo
    assert "<form" not in limpo
    assert "texto" in limpo


def test_preserva_tabela_com_estilo_inline():
    """A assinatura usa <table> com estilo inline — o corpo pode ter o mesmo."""
    bruto = (
        '<table style="max-width:500px" cellpadding="0"><tr>'
        '<td style="color:red">célula</td></tr></table>'
    )
    limpo = limpar_html(bruto)
    assert "<table" in limpo
    assert 'style="color:red"' in limpo or "color:red" in limpo
    assert "célula" in limpo


def test_link_ganha_rel_noopener():
    limpo = limpar_html('<a href="https://x.com">link</a>')
    assert 'rel="noopener noreferrer"' in limpo


def test_classe_e_preservada_para_as_media_queries_funcionarem():
    """`class` sobrevive de propósito desde que o `<style>` passou a sobreviver:
    as media queries preservadas miram justamente as classes, e tirar uma sem a
    outra quebraria o responsivo. O preço é que a sopa de classes do Word
    também passa — feia, mas inofensiva."""
    limpo = limpar_html('<p class="MsoNormal">texto</p>')
    assert 'class="MsoNormal"' in limpo
    assert "texto" in limpo


def test_remove_comentarios_condicionais_do_word():
    limpo = limpar_html("<!--[if mso]><p>oculto</p><![endif]-->texto visível")
    assert "oculto" not in limpo
    assert "texto visível" in limpo


def test_string_vazia_ou_so_espaco():
    assert limpar_html("") == ""
    assert limpar_html("   \n\t  ") == ""


def test_esquema_javascript_e_removido_do_href():
    limpo = limpar_html('<a href="javascript:alert(1)">clique</a>')
    assert "javascript:" not in limpo


# --- html_para_texto ---------------------------------------------------


def test_texto_negrito_vira_texto_simples():
    assert html_para_texto("<p><b>oi</b></p>") == "oi"


def test_lista_vira_travessao():
    texto = html_para_texto("<ul><li>um</li><li>dois</li></ul>")
    assert "- um" in texto
    assert "- dois" in texto


def test_link_vira_rotulo_e_url():
    texto = html_para_texto('<a href="https://exemplo.com">clique aqui</a>')
    assert "clique aqui" in texto
    assert "<https://exemplo.com>" in texto


def test_entidades_html_sao_decodificadas():
    assert "é" in html_para_texto("<p>voc&ecirc; &eacute;</p>".replace("&ecirc;", "ê"))
    assert html_para_texto("<p>a &amp; b</p>") == "a & b"


def test_blocos_viram_quebra_de_linha():
    # Cada fronteira de bloco vira uma linha; dois parágrafos consecutivos
    # (fechamento + abertura) somam duas — um espaço em branco entre
    # parágrafos, exatamente como se esperaria em texto simples legível.
    texto = html_para_texto("<p>um</p><p>dois</p>")
    assert texto == "um\n\ndois"


def test_string_vazia():
    assert html_para_texto("") == ""
