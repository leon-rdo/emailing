"""limpar_html() e html_para_texto()."""

from mensagens.saneamento import html_para_texto, limpar_html


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


def test_remove_classe_de_word():
    """Sopa de classes do Word/Outlook não sobrevive: só 'style' é permitido."""
    limpo = limpar_html('<p class="MsoNormal">texto</p>')
    assert "class=" not in limpo
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
