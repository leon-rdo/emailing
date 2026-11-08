"""analisar_eml(): extração de cabeçalhos e threading a partir de .eml/.txt."""

from pathlib import Path

import pytest

from mensagens.eml import (
    ErroImportacaoEML,
    analisar_eml,
    normalizar_message_id,
    referencias_para_resposta,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _ler(nome: str) -> bytes:
    return (FIXTURES / nome).read_bytes()


# --- o caso completo: multipart, quoted-printable, RFC 2047, References dobrado ---


def test_eml_quoted_printable_multipart():
    resultado = analisar_eml(_ler("resposta_quoted_printable.eml"))

    assert resultado.message_id == "<abc123_ticket9001@exemplo.com>"
    # To prefere Reply-To sobre From.
    assert resultado.para == "atendimento@exemplo.com"
    assert resultado.assunto == "Re: Dúvida sobre integração"
    assert resultado.avisos == []

    # get_body prefere HTML; decodificação quoted-printable + acentuação ok.
    assert "ção" in resultado.citacao_html
    assert "<b>" in resultado.citacao_html  # sobreviveu ao sanitizador

    # References dobrado em várias linhas + Message-ID do original no final.
    assert resultado.referencias == (
        "<primeira-mensagem@empresa.example> "
        "<resposta-automatica@exemplo.com> "
        "<abc123_ticket9001@exemplo.com>"
    )


def test_eml_sem_reply_to_usa_from():
    resultado = analisar_eml(_ler("sem_message_id.eml"))
    assert resultado.para == "Cliente Sem ID <cliente@exemplo.com>"


# --- sem Message-ID: preenche o resto, avisa que não encadeia ---


def test_eml_sem_message_id():
    resultado = analisar_eml(_ler("sem_message_id.eml"))
    assert resultado.message_id == ""
    assert resultado.para
    assert resultado.assunto == "Re: Pergunta rápida"
    assert len(resultado.avisos) == 1
    assert "não vai encadear" in resultado.avisos[0]


# --- colagem do Outlook em pt-BR: não parseia, erro claro ---


def test_colagem_outlook_e_recusada():
    with pytest.raises(ErroImportacaoEML, match="Outlook"):
        analisar_eml(_ler("colagem_outlook.txt"))


# --- BOM UTF-8 ---


def test_bom_utf8_no_inicio_nao_corrompe_o_primeiro_cabecalho():
    bom = b"\xef\xbb\xbf"
    bruto = bom + b"From: a@x.com\r\nSubject: Oi\r\nMessage-ID: <1@x>\r\n\r\ncorpo\r\n"
    resultado = analisar_eml(bruto)
    assert resultado.para == "a@x.com"
    assert resultado.message_id == "<1@x>"


# --- normalização de Message-ID ---


@pytest.mark.parametrize(
    "bruto,esperado",
    [
        ("<abc@x.com>", "<abc@x.com>"),
        ("abc@x.com", "<abc@x.com>"),
        ("  <abc@x.com>  ", "<abc@x.com>"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalizar_message_id(bruto, esperado):
    assert normalizar_message_id(bruto) == esperado


# --- References: dedup, ordem, teto de 20 ---


def test_referencias_para_resposta_deduplica_preservando_ordem():
    resultado = referencias_para_resposta(["<a@x>", "<b@x>", "<a@x>"], "<c@x>")
    assert resultado == "<a@x> <b@x> <c@x>"


def test_referencias_para_resposta_sem_repetir_o_proprio_message_id():
    # Se o Message-ID do original já estivesse (por algum motivo) nas suas
    # próprias References, não duplica — só garante que fica por último,
    # não importa em que posição estivesse originalmente.
    assert referencias_para_resposta(["<a@x>", "<msg@x>"], "<msg@x>") == "<a@x> <msg@x>"
    assert referencias_para_resposta(["<msg@x>", "<a@x>"], "<msg@x>") == "<a@x> <msg@x>"


def test_referencias_limitadas_a_20_mantendo_a_primeira():
    originais = [f"<{i}@x>" for i in range(25)]
    resultado = referencias_para_resposta(originais, "<novo@x>")
    ids = resultado.split()
    assert len(ids) == 20
    assert ids[0] == "<0@x>"  # a primeira da thread nunca é descartada
    assert ids[-1] == "<novo@x>"


def test_referencias_vazias_com_so_o_message_id_novo():
    assert referencias_para_resposta([], "<novo@x>") == "<novo@x>"


# --- duplicidade de Message-ID: fica só o primeiro ---


def test_message_id_duplicado_usa_o_primeiro():
    bruto = (
        b"From: a@x.com\r\nSubject: Oi\r\n"
        b"Message-ID: <primeiro@x>\r\nMessage-ID: <segundo@x>\r\n\r\ncorpo\r\n"
    )
    resultado = analisar_eml(bruto)
    assert resultado.message_id == "<primeiro@x>"


# --- getaddresses com lixo: endereço vazio e sintaxe de grupo são descartados ---


def test_from_com_grupo_undisclosed_recipients_nao_quebra():
    bruto = (
        b"From: undisclosed-recipients:;\r\nSubject: Oi\r\n"
        b"Message-ID: <1@x>\r\n\r\ncorpo\r\n"
    )
    resultado = analisar_eml(bruto)
    assert resultado.para == ""  # nada de válido para extrair, mas não quebra


# --- corpo texto puro vira <pre> escapado, depois sanitizado ---


def test_corpo_so_texto_plano_fica_dentro_de_pre():
    bruto = (
        b"From: a@x.com\r\nSubject: Oi\r\nMessage-ID: <1@x>\r\n"
        b'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        b"linha 1\r\nlinha 2 com <tag> solta\r\n"
    )
    resultado = analisar_eml(bruto)
    assert "<pre>" in resultado.citacao_html
    assert "linha 1" in resultado.citacao_html
    # A tag solta no texto original vira texto literal, não HTML de verdade.
    assert "&lt;tag&gt;" in resultado.citacao_html


# --- referências com apenas In-Reply-To (RFC 5322 §3.6.4) ---


def test_sem_references_semeia_de_in_reply_to():
    bruto = (
        b"From: a@x.com\r\nSubject: Oi\r\nMessage-ID: <novo@x>\r\n"
        b"In-Reply-To: <original@x>\r\n\r\ncorpo\r\n"
    )
    resultado = analisar_eml(bruto)
    assert resultado.referencias == "<original@x> <novo@x>"


# --- prefixos de assunto: todos removidos, um único "Re: " no final ---


@pytest.mark.parametrize(
    "assunto_original,esperado",
    [
        ("Pedido", "Re: Pedido"),
        ("Re: Pedido", "Re: Pedido"),
        ("RE: Pedido", "Re: Pedido"),
        ("RES: Pedido", "Re: Pedido"),  # Outlook pt-BR em resposta
        ("ENC: Pedido", "Re: Pedido"),  # Outlook pt-BR em encaminhamento
        ("Fwd: Pedido", "Re: Pedido"),
        ("FW: Pedido", "Re: Pedido"),
        ("Re[2]: Pedido", "Re: Pedido"),
        ("Re: Re: Pedido", "Re: Pedido"),
        ("Re: RES: Fwd: Pedido", "Re: Pedido"),
    ],
)
def test_prefixos_de_assunto(assunto_original, esperado):
    bruto = (
        f"From: a@x.com\r\nSubject: {assunto_original}\r\n"
        "Message-ID: <1@x>\r\n\r\ncorpo\r\n"
    ).encode()
    resultado = analisar_eml(bruto)
    assert resultado.assunto == esperado


# --- .txt cru (mesmo conteúdo MIME, extensão diferente) parseia igual ---


def test_txt_com_mime_cru_parseia_como_eml(tmp_path):
    conteudo = _ler("resposta_quoted_printable.eml")
    caminho_txt = tmp_path / "copia.txt"
    caminho_txt.write_bytes(conteudo)
    resultado = analisar_eml(caminho_txt.read_bytes())
    assert resultado.message_id == "<abc123_ticket9001@exemplo.com>"


# --- arquivo genuinamente ilegível não derruba a view com 500 ---


def test_lixo_binario_nao_derruba():
    with pytest.raises(ErroImportacaoEML):
        analisar_eml(b"\x00\x01\x02\xff\xfe\xfd sem estrutura nenhuma de e-mail")
