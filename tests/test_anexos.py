"""Anexos de rascunho: gravar, listar, remover, expirar."""

import time

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from mensagens.anexos import (
    ErroAnexo,
    criar_token,
    ler_anexos,
    limpar_rascunhos_expirados,
    listar_anexos,
    remover_anexo,
    salvar_anexo,
)


@pytest.fixture(autouse=True)
def _diretorio_de_rascunhos(tmp_path, settings):
    settings.RASCUNHOS_DIR = tmp_path


def _arquivo(nome="nota.pdf", conteudo=b"conteudo", tipo="application/pdf"):
    return SimpleUploadedFile(nome, conteudo, content_type=tipo)


def test_criar_token_e_unico():
    assert criar_token() != criar_token()


def test_salvar_e_listar():
    token = criar_token()
    salvar_anexo(token, _arquivo("a.pdf", b"1234"))
    salvar_anexo(token, _arquivo("b.png", b"56789"))
    itens = listar_anexos(token)
    assert {i.nome for i in itens} == {"a.pdf", "b.png"}
    assert {i.tamanho for i in itens} == {4, 5}


def test_listar_token_inexistente_e_lista_vazia():
    assert listar_anexos("nao-existe") == []
    assert listar_anexos("") == []


def test_remover_por_id():
    token = criar_token()
    item = salvar_anexo(token, _arquivo())
    outro = salvar_anexo(token, _arquivo("b.pdf"))
    remover_anexo(token, item.id)
    restantes = listar_anexos(token)
    assert len(restantes) == 1
    assert restantes[0].id == outro.id


def test_remover_id_inexistente_nao_quebra():
    token = criar_token()
    salvar_anexo(token, _arquivo())
    remover_anexo(token, "id-que-nao-existe")
    assert len(listar_anexos(token)) == 1


def test_nome_com_caminho_e_saneado():
    token = criar_token()
    item = salvar_anexo(token, _arquivo("../../etc/passwd"))
    assert item.nome == "passwd"
    assert "/" not in item.nome and ".." not in item.nome


def test_extensao_bloqueada(settings):
    settings.ANEXOS_EXTENSOES_BLOQUEADAS = ["exe"]
    token = criar_token()
    with pytest.raises(ErroAnexo, match=r"\.exe"):
        salvar_anexo(token, _arquivo("virus.exe"))
    assert listar_anexos(token) == []


def test_arquivo_grande_demais(settings):
    settings.ANEXO_MAX_BYTES = 10
    token = criar_token()
    with pytest.raises(ErroAnexo, match="acima do limite"):
        salvar_anexo(token, _arquivo(conteudo=b"x" * 20))


def test_limite_de_quantidade(settings):
    settings.ANEXOS_MAX_ARQUIVOS = 2
    token = criar_token()
    salvar_anexo(token, _arquivo("a.pdf"))
    salvar_anexo(token, _arquivo("b.pdf"))
    with pytest.raises(ErroAnexo, match="Limite de 2"):
        salvar_anexo(token, _arquivo("c.pdf"))


def test_limite_de_soma_total(settings):
    settings.ANEXOS_MAX_TOTAL_BYTES = 15
    token = criar_token()
    salvar_anexo(token, _arquivo("a.pdf", b"x" * 10))
    with pytest.raises(ErroAnexo, match="somando todos os anexos"):
        salvar_anexo(token, _arquivo("b.pdf", b"x" * 10))


def test_ler_anexos_devolve_conteudo_para_montagem():
    token = criar_token()
    salvar_anexo(token, _arquivo("a.pdf", b"conteudo-pdf", "application/pdf"))
    lidos = ler_anexos(token)
    assert len(lidos) == 1
    assert lidos[0].nome == "a.pdf"
    assert lidos[0].conteudo == b"conteudo-pdf"
    assert lidos[0].tipo == "application/pdf"


def test_ler_anexos_sem_token():
    assert ler_anexos("") == []


def test_limpar_rascunhos_expirados(tmp_path):
    token_velho = criar_token()
    salvar_anexo(token_velho, _arquivo())
    antigo = time.time() - 10 * 86400
    for caminho in (tmp_path / token_velho).iterdir():
        import os

        os.utime(caminho, (antigo, antigo))

    token_novo = criar_token()
    salvar_anexo(token_novo, _arquivo())

    apagados = limpar_rascunhos_expirados(ttl_dias=7)

    assert apagados == 1
    assert listar_anexos(token_velho) == []
    assert len(listar_anexos(token_novo)) == 1
