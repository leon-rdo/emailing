"""`mensagens/caixa.py`: IMAP sob demanda para o servidor MCP.

O que se prova aqui são as três regras do módulo: ler não muda a caixa (EXAMINE
+ BODY.PEEK), a mensagem é identificada por (UIDVALIDITY, UID), e mover nunca
faz um EXPUNGE que apagaria mensagens alheias.
"""

from datetime import date

import pytest
from imap_falso import mensagem_de_exemplo

from mensagens import caixa
from mensagens.caixa import ErroCaixa, Filtro, Referencia

pytestmark = pytest.mark.django_db


def _ref(conta, servidor, uid, pasta="INBOX"):
    return Referencia(conta, servidor.uidvalidity[pasta], uid, pasta)


# ---------------------------------------------------------------------------
# Ler não muda a caixa
# ---------------------------------------------------------------------------


def test_buscar_abre_com_examine_e_traz_a_mais_nova_primeiro(imap, conta_de_teste):
    for n in range(5):
        imap.entregar(mensagem_de_exemplo(assunto=f"Mensagem {n}"))

    resultado = caixa.buscar(conta_de_teste, "INBOX", Filtro(), limite=3)

    assert ("EXAMINE", "INBOX") in imap.comandos
    assert not any(c[0] == "SELECT" for c in imap.comandos)
    assert resultado.total == 5
    assert [e.assunto for e in resultado.envelopes] == ["Mensagem 4", "Mensagem 3", "Mensagem 2"]
    assert resultado.uidvalidity == 1000
    envelope = resultado.envelopes[0]
    assert envelope.de == "Cliente <cliente@exemplo.test>"
    assert envelope.tem_anexo is True
    assert envelope.lida is False


def test_buscar_pede_so_cabecalhos_com_peek(imap, conta_de_teste):
    imap.entregar(mensagem_de_exemplo())
    caixa.buscar(conta_de_teste, "INBOX", Filtro(), limite=10)
    fetch = [c for c in imap.comandos if c[:2] == ("UID", "FETCH")]
    assert fetch and "BODY.PEEK[HEADER.FIELDS" in fetch[0][3]


def test_ler_nao_marca_como_lida(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo())

    bruta = caixa.ler(_ref(conta_de_teste, imap, uid))

    assert bruta.lida is False
    assert "\\Seen" not in imap.pastas["INBOX"][uid]["flags"]
    assert ("EXAMINE", "INBOX") in imap.comandos


def test_interpretar_texto_html_e_anexos(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo())
    bruto = caixa.ler(_ref(conta_de_teste, imap, uid)).bruto

    texto = caixa.interpretar(bruto, formato="texto", limite=10_000)
    assert texto.corpo.startswith("Olá, segue a proposta.")
    assert texto.cabecalhos["subject"] == "Proposta de parceria"
    assert [(a.nome, a.tipo) for a in texto.anexos] == [("proposta.pdf", "application/pdf")]

    html = caixa.interpretar(bruto, formato="html", limite=10_000)
    assert "<strong>proposta</strong>" in html.corpo


def test_interpretar_converte_html_quando_nao_ha_texto_simples():
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "x@exemplo.test"
    msg["Subject"] = "só html"
    msg.set_content("<p>Linha um</p><p>Linha <b>dois</b></p>", subtype="html")

    corpo = caixa.interpretar(msg.as_bytes(), formato="texto", limite=1000).corpo

    assert "<" not in corpo
    assert "Linha um" in corpo and "Linha dois" in corpo


def test_html_recebido_passa_pelo_sanitizador(imap, conta_de_teste):
    hostil = '<p onclick="x()">oi</p><script>alert(1)</script>'
    uid = imap.entregar(mensagem_de_exemplo(html=hostil))
    bruto = caixa.ler(_ref(conta_de_teste, imap, uid)).bruto
    corpo = caixa.interpretar(bruto, formato="html", limite=10_000).corpo
    assert "<script" not in corpo and "onclick" not in corpo


def test_corpo_longo_volta_truncado(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo(texto="a" * 500, html=None))
    bruto = caixa.ler(_ref(conta_de_teste, imap, uid)).bruto
    lida = caixa.interpretar(bruto, formato="texto", limite=100)
    assert lida.corpo_truncado is True
    assert len(lida.corpo) == 100


def test_mensagem_grande_demais_nao_e_baixada(imap, conta_de_teste, settings):
    settings.IMAP_MAX_BYTES = 100
    uid = imap.entregar(mensagem_de_exemplo())
    with pytest.raises(ErroCaixa, match="acima do limite"):
        caixa.ler(_ref(conta_de_teste, imap, uid))
    assert not any("BODY.PEEK[]" in str(c) for c in imap.comandos)


# ---------------------------------------------------------------------------
# Identificador
# ---------------------------------------------------------------------------


def test_uidvalidity_mudado_recusa_em_vez_de_agir_na_mensagem_errada(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo())
    ref = _ref(conta_de_teste, imap, uid)
    imap.uidvalidity["INBOX"] = 1001  # o servidor renumerou a pasta

    with pytest.raises(ErroCaixa, match="renumerada"):
        caixa.ler(ref)
    with pytest.raises(ErroCaixa, match="renumerada"):
        caixa.marcar(ref, lida=True, sinalizada=None)
    assert imap.pastas["INBOX"][uid]["flags"] == set()


def test_id_opaco_vai_e_volta_com_pasta_que_tem_dois_pontos(conta_de_teste):
    texto = caixa.id_de(conta_de_teste, 77, 12, "Arquivo:2026")
    ref = caixa.abrir_id(texto)
    assert (ref.conta, ref.uidvalidity, ref.uid) == (conta_de_teste, 77, 12)
    assert ref.pasta == "Arquivo:2026"


def test_id_invalido_explica(db):
    with pytest.raises(ErroCaixa, match="buscar_emails"):
        caixa.abrir_id("isto-nao")


def test_mensagem_sumida_explica(imap, conta_de_teste):
    with pytest.raises(ErroCaixa, match="apagada ou movida"):
        caixa.ler(_ref(conta_de_teste, imap, 999))


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------


def test_marcar_usa_select_e_so_mexe_nas_duas_flags(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo(), flags={"$Etiqueta"})

    estado = caixa.marcar(_ref(conta_de_teste, imap, uid), lida=True, sinalizada=True)

    assert estado == {"lida": True, "sinalizada": True}
    assert imap.pastas["INBOX"][uid]["flags"] == {"$Etiqueta", "\\Seen", "\\Flagged"}
    assert ("SELECT", "INBOX") in imap.comandos

    caixa.marcar(_ref(conta_de_teste, imap, uid), lida=False, sinalizada=None)
    assert imap.pastas["INBOX"][uid]["flags"] == {"$Etiqueta", "\\Flagged"}


def test_marcar_sem_nada_para_marcar_recusa(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo())
    with pytest.raises(ErroCaixa, match="Diga o que marcar"):
        caixa.marcar(_ref(conta_de_teste, imap, uid), lida=None, sinalizada=None)


def test_mover_com_move(imap, conta_de_teste):
    imap.criar_pasta("Arquivo")
    uid = imap.entregar(mensagem_de_exemplo())

    caixa.mover(_ref(conta_de_teste, imap, uid), "Arquivo")

    assert imap.pastas["INBOX"] == {}
    assert len(imap.pastas["Arquivo"]) == 1
    assert ("UID", "MOVE", str(uid), '"Arquivo"') in imap.comandos


def test_mover_sem_move_usa_uid_expunge_e_poupa_as_outras(imap, conta_de_teste):
    """Outra mensagem já marcada \\Deleted por outro cliente não pode sumir."""
    imap.capacidades = ("IMAP4REV1", "UIDPLUS")
    imap.criar_pasta("Arquivo")
    alvo = imap.entregar(mensagem_de_exemplo(assunto="mover esta"))
    alheia = imap.entregar(mensagem_de_exemplo(assunto="não tocar"), flags={"\\Deleted"})

    caixa.mover(_ref(conta_de_teste, imap, alvo), "Arquivo")

    assert alvo not in imap.pastas["INBOX"]
    assert alheia in imap.pastas["INBOX"]
    assert ("UID", "EXPUNGE", str(alvo)) in imap.comandos
    assert not any(c[0] == "EXPUNGE" for c in imap.comandos)


def test_mover_sem_move_nem_uidplus_recusa_sem_tocar_em_nada(imap, conta_de_teste):
    imap.capacidades = ("IMAP4REV1",)
    imap.criar_pasta("Arquivo")
    uid = imap.entregar(mensagem_de_exemplo())

    with pytest.raises(ErroCaixa, match="EXPUNGE"):
        caixa.mover(_ref(conta_de_teste, imap, uid), "Arquivo")

    assert uid in imap.pastas["INBOX"]
    assert imap.pastas["Arquivo"] == {}


def test_mover_para_pasta_inexistente_explica(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo())
    with pytest.raises(ErroCaixa, match="listar_pastas"):
        caixa.mover(_ref(conta_de_teste, imap, uid), "Não Existe")
    assert uid in imap.pastas["INBOX"]


# ---------------------------------------------------------------------------
# Conexão, pastas e filtros
# ---------------------------------------------------------------------------


def test_conta_sem_imap_explica_onde_configurar(conta_de_teste):
    with pytest.raises(ErroCaixa, match="Recebimento"):
        caixa.buscar(conta_de_teste, "INBOX", Filtro(), limite=5)


def test_senha_recusada(imap, conta_de_teste):
    imap.senha_certa = "outra"
    with pytest.raises(ErroCaixa, match="recusou o usuário ou a senha"):
        caixa.listar_pastas(conta_de_teste)


def test_listar_pastas_decodifica_utf7_e_pula_noselect(imap, conta_de_teste):
    imap.extras_list = [
        b'(\\HasNoChildren \\Junk) "/" "Lixo Eletr&APQ-nico"',
        b'(\\Noselect \\HasChildren) "/" "[Gmail]"',
        (b'(\\HasNoChildren \\Sent) "/" {14}', b"Itens Enviados"),
    ]
    pastas = {p.nome: p.uso for p in caixa.listar_pastas(conta_de_teste)}
    assert pastas == {"INBOX": "", "Lixo Eletrônico": "\\Junk", "Itens Enviados": "\\Sent"}


def test_abrir_pasta_com_acento_vai_em_utf7(imap, conta_de_teste):
    imap.criar_pasta("Lixo Eletr&APQ-nico")
    caixa.buscar(conta_de_teste, "Lixo Eletrônico", Filtro(), limite=5)
    assert ("EXAMINE", "Lixo Eletr&APQ-nico") in imap.comandos


def test_criterio_com_acento_vai_por_ultimo_como_literal():
    criterios, literal = caixa._criterios(
        Filtro(de="joão", texto="proposta", para="financeiro@empresa.example",
               desde=date(2026, 11, 1), ate=date(2026, 11, 8), nao_lidas=True)
    )
    assert "CHARSET" not in criterios  # quem põe o charset é o comando (SEARCH ou SORT)
    assert criterios[-1] == "FROM"
    assert literal == "joão".encode()
    assert "BEFORE" in criterios and "09-Nov-2026" in criterios  # `ate` é inclusivo


def test_dois_criterios_com_acento_recusa():
    with pytest.raises(ErroCaixa, match="Só um"):
        caixa._criterios(Filtro(de="joão", texto="ação"))


def test_sem_filtro_e_all():
    assert caixa._criterios(Filtro()) == (["ALL"], None)


def test_busca_com_acento_manda_o_literal(imap, conta_de_teste):
    imap.entregar(mensagem_de_exemplo())
    caixa.buscar(conta_de_teste, "INBOX", Filtro(texto="ação"), limite=5)
    assert imap.literais == ["ação".encode()]
    busca = next(c for c in imap.comandos if c[:2] == ("UID", "SEARCH"))
    assert busca[2:] == ("CHARSET", "UTF-8", "TEXT")


# ---------------------------------------------------------------------------
# Ordem: pela data do e-mail, não pela chegada à pasta
# ---------------------------------------------------------------------------


def _entregar_fora_de_ordem(imap):
    """A mais antiga chega por último à pasta (UID maior) — como quando um filtro
    ou outro cliente a move para lá depois. Foi o caso real da pasta Promoções."""
    imap.entregar(mensagem_de_exemplo(assunto="26/10", data="Mon, 26 Oct 2026 19:57:29 +0000"))
    imap.entregar(mensagem_de_exemplo(assunto="22/10", data="Thu, 22 Oct 2026 20:00:18 +0000"))
    imap.entregar(mensagem_de_exemplo(assunto="11/10", data="Sun, 11 Oct 2026 00:06:10 +0000"))


def test_sem_sort_ordena_pela_data_no_app(imap, conta_de_teste):
    _entregar_fora_de_ordem(imap)

    resultado = caixa.buscar(conta_de_teste, "INBOX", Filtro(), limite=2)

    assert [e.assunto for e in resultado.envelopes] == ["26/10", "22/10"]
    assert resultado.ordem == "data"
    assert not any(c[:2] == ("UID", "SORT") for c in imap.comandos)
    assert any("HEADER.FIELDS (DATE)" in str(c) for c in imap.comandos)


def test_com_sort_quem_ordena_e_o_servidor(imap, conta_de_teste):
    imap.capacidades = ("IMAP4REV1", "MOVE", "UIDPLUS", "SORT")
    _entregar_fora_de_ordem(imap)

    resultado = caixa.buscar(conta_de_teste, "INBOX", Filtro(), limite=2)

    assert [e.assunto for e in resultado.envelopes] == ["26/10", "22/10"]
    assert ("UID", "SORT", "(REVERSE DATE)", "UTF-8", "ALL") in imap.comandos
    assert not any(c[:2] == ("UID", "SEARCH") for c in imap.comandos)
    assert not any("HEADER.FIELDS (DATE)" in str(c) for c in imap.comandos)


def test_sort_com_acento_leva_o_charset_posicional_e_o_literal(imap, conta_de_teste):
    imap.capacidades = ("IMAP4REV1", "SORT")
    imap.entregar(mensagem_de_exemplo())
    caixa.buscar(conta_de_teste, "INBOX", Filtro(texto="ação", nao_lidas=True), limite=5)
    assert ("UID", "SORT", "(REVERSE DATE)", "UTF-8", "UNSEEN", "TEXT") in imap.comandos
    assert imap.literais == ["ação".encode()]


def test_janela_cortada_avisa_em_vez_de_fingir_ordem_exata(imap, conta_de_teste, settings):
    settings.IMAP_JANELA_ORDENACAO = 2
    _entregar_fora_de_ordem(imap)

    resultado = caixa.buscar(conta_de_teste, "INBOX", Filtro(), limite=5)

    assert resultado.total == 3
    assert "entre as 2" in resultado.ordem
    # A janela são as duas que chegaram por último (22/10 e 11/10), ordenadas por data.
    assert [e.assunto for e in resultado.envelopes] == ["22/10", "11/10"]


def test_conjunto_compacta_faixas():
    assert caixa._conjunto([5, 1, 2, 3, 7, 9, 10, 11, 4]) == "1:5,7,9:11"
    assert caixa._conjunto([42]) == "42"


# ---------------------------------------------------------------------------
# Links encurtados no texto
# ---------------------------------------------------------------------------

_RASTREADO = (
    "https://www.loja.example/p/MLB50744239?matt_tool=15253984&utm_source=x"
    "&utm_campaign=" + "a" * 300 + "#origem"
)


def test_texto_encurta_links_de_rastreamento(imap, conta_de_teste):
    html = f'<p>Oferta: <a href="{_RASTREADO}">ver</a> e <a href="https://outra.example">site</a></p>'
    uid = imap.entregar(mensagem_de_exemplo(texto="", html=html, anexo=None))
    bruto = caixa.ler(_ref(conta_de_teste, imap, uid)).bruto

    lida = caixa.interpretar(bruto, formato="texto", limite=10_000)

    assert "https://www.loja.example/p/MLB50744239…" in lida.corpo
    assert "utm_" not in lida.corpo
    assert "https://outra.example" in lida.corpo  # link curto e limpo fica intacto
    assert lida.links_encurtados == 1


def test_html_mantem_o_link_inteiro(imap, conta_de_teste):
    html = f'<p><a href="{_RASTREADO}">ver</a></p>'
    uid = imap.entregar(mensagem_de_exemplo(html=html, anexo=None))
    bruto = caixa.ler(_ref(conta_de_teste, imap, uid)).bruto

    lida = caixa.interpretar(bruto, formato="html", limite=10_000)

    assert "utm_campaign" in lida.corpo
    assert lida.links_encurtados == 0


def test_caminho_longo_sem_query_tambem_e_cortado():
    texto, n = caixa.encurtar_links("veja https://x.com/" + "b" * 200 + " ok")
    assert n == 1 and texto.endswith("… ok") and len(texto) < 100


def test_encurtar_vem_antes_do_corte_do_limite(imap, conta_de_teste):
    """O limite é de conteúdo: sem encurtar primeiro, o corte comeria texto real."""
    corpo = f"Começo. {_RASTREADO} Fim importante."
    uid = imap.entregar(mensagem_de_exemplo(texto=corpo, html=None, anexo=None))
    bruto = caixa.ler(_ref(conta_de_teste, imap, uid)).bruto
    lida = caixa.interpretar(bruto, formato="texto", limite=120)
    assert "Fim importante." in lida.corpo
    assert lida.corpo_truncado is False


def test_texto_simples_vazio_cai_para_o_html(imap, conta_de_teste):
    uid = imap.entregar(mensagem_de_exemplo(texto="   \n", html="<p>Conteúdo de verdade</p>"))
    bruto = caixa.ler(_ref(conta_de_teste, imap, uid)).bruto
    assert caixa.interpretar(bruto, formato="texto", limite=1000).corpo == "Conteúdo de verdade"
