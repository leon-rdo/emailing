"""Marcadores `{{ nome }}`: lista fechada, expandida só no envio."""

import pytest

from mensagens.marcadores import GLOSSARIO, NOMES, expandir
from mensagens.montagem import DadosRedacao, calcular_hash_previa, montar_corpo, montar_email

pytestmark = pytest.mark.django_db


def _dados(corpo="", **extra):
    extra.setdefault("para", ["cliente@exemplo.com"])
    return DadosRedacao(corpo_html=corpo, **extra)


def test_data_e_trocada(alias_de_teste):
    from django.utils import timezone

    hoje = timezone.localtime().strftime("%d/%m/%Y")
    assert expandir("hoje é {{ data }}", alias_de_teste, _dados(), escapar_html=True) == (
        f"hoje é {hoje}"
    )


def test_espacos_dentro_das_chaves_sao_opcionais(alias_de_teste):
    com_espaco = expandir("{{ ano }}", alias_de_teste, _dados(), escapar_html=True)
    sem_espaco = expandir("{{ano}}", alias_de_teste, _dados(), escapar_html=True)
    assert com_espaco == sem_espaco
    assert com_espaco.isdigit()


def test_marcador_desconhecido_fica_literal(alias_de_teste):
    """A lista é fechada: o que não é nosso não é tocado."""
    texto = "{{ inventado }} e {{ Date.now }} e {{ 1+1 }}"
    assert expandir(texto, alias_de_teste, _dados(), escapar_html=True) == texto


def test_sintaxe_de_outros_motores_fica_literal(alias_de_teste):
    """EJS, PHP e afins não são marcadores — o app não avalia código."""
    texto = "<%= Date.now() %> {% now %} <?php echo 1; ?>"
    assert expandir(texto, alias_de_teste, _dados(), escapar_html=True) == texto


def test_dados_do_remetente_e_destinatario(alias_de_teste):
    dados = _dados(para=["cliente@exemplo.com", "outro@x.com"], assunto="Proposta")
    resultado = expandir(
        "{{ remetente_email }} | {{ remetente_nome }} | {{ destinatario }} | {{ assunto }}",
        alias_de_teste, dados, escapar_html=True,
    )
    assert resultado == (
        "financeiro@empresa.example | Ana Souza | cliente@exemplo.com | Proposta"
    )


def test_valor_e_escapado_no_html(alias_de_teste):
    """Nem um valor com '<' consegue injetar marcação no corpo."""
    alias_de_teste.nome_exibicao = "Fulano <script>"
    dados = _dados()
    html = expandir("{{ remetente_nome }}", alias_de_teste, dados, escapar_html=True)
    texto = expandir("{{ remetente_nome }}", alias_de_teste, dados, escapar_html=False)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<script>" in texto  # na parte text/plain não há o que injetar


def test_sem_marcador_nao_mexe_no_texto(alias_de_teste):
    texto = "<p>nada aqui</p>"
    assert expandir(texto, alias_de_teste, _dados(), escapar_html=True) == texto


def test_glossario_bate_com_o_que_e_reconhecido(alias_de_teste):
    """Cada marcador do glossário tem que funcionar de verdade — um glossário
    que promete o que não existe é pior que glossário nenhum."""
    for marcador in GLOSSARIO:
        entrada = f"[{{{{ {marcador.nome} }}}}]"
        saida = expandir(entrada, alias_de_teste, _dados(assunto="X"), escapar_html=True)
        assert saida != entrada, f"{marcador.nome} está no glossário mas não expande"
    assert NOMES == {m.nome for m in GLOSSARIO}


# --- a parte que interage com o hash da prévia ------------------------


def test_email_enviado_leva_o_valor_expandido(alias_de_teste):
    mensagem = montar_email(_dados("<p>em {{ ano }}</p>"), alias_de_teste)
    from django.utils import timezone

    ano = str(timezone.localtime().year)
    assert ano in mensagem.alternatives[0][0]
    assert "{{ ano }}" not in mensagem.alternatives[0][0]
    assert ano in mensagem.body  # a parte texto também


def test_hash_e_do_conteudo_autoral_nao_do_expandido(alias_de_teste):
    """`{{ hora }}` mudaria sozinho entre a prévia e o Enviar; se o hash fosse
    do texto expandido, o envio seria recusado por 'o conteúdo mudou'."""
    dados = _dados("<p>agora são {{ hora }}</p>")
    html_autoral, _ = montar_corpo(dados, alias_de_teste)

    assert "{{ hora }}" in html_autoral  # o autoral guarda o marcador

    hash_um = calcular_hash_previa(dados, alias_de_teste, html_autoral)
    hash_dois = calcular_hash_previa(dados, alias_de_teste, montar_corpo(dados, alias_de_teste)[0])
    assert hash_um == hash_dois


def test_marcador_no_texto_simples_nao_fica_escapado(alias_de_teste):
    mensagem = montar_email(_dados("<p>{{ remetente_email }}</p>"), alias_de_teste)
    assert "financeiro@empresa.example" in mensagem.body
