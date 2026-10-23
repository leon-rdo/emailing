"""Anexos de rascunho: gravados no disco entre a prévia e o envio.

Não existe endpoint de upload separado: qualquer POST da tela de redação
processa `request.FILES` antes de decidir o que mostrar (prévia ou, na Etapa
7, envio). Um rascunho é identificado por um token opaco, gerado na primeira
anexação e carregado de volta pelo formulário a cada POST seguinte (campo
`rascunho`, em `forms.FormularioRedacao`) — os arquivos daquele token ficam em
`RASCUNHOS_DIR/<token>/`, nomeados `<id>__<nome-original>`.

A linha de comando (`manage.py enviar --anexo`) entra pela mesma pasta, via
`guardar_caminhos()`: a partir dali o rascunho é indistinguível de um vindo do
navegador. As regras de tamanho e extensão vivem em `_validar()` justamente
para as duas origens não divergirem.

E há uma armadilha aqui: mensagem **agendada** guarda os anexos neste mesmo
lugar, por um prazo que pode passar do TTL da limpeza. Ver
`limpar_rascunhos_expirados`.
"""

from __future__ import annotations

import mimetypes
import re
import secrets
import shutil
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from .montagem import Anexo


class ErroAnexo(Exception):
    """A mensagem já é o texto pronto para mostrar ao usuário."""


@dataclass(frozen=True)
class AnexoRascunho:
    id: str
    nome: str
    tamanho: int
    tipo: str

    @property
    def tamanho_legivel(self) -> str:
        return _tamanho_legivel(self.tamanho)


def _tamanho_legivel(tamanho_bytes: int) -> str:
    valor = float(tamanho_bytes)
    for unidade in ("B", "KB", "MB"):
        if valor < 1024:
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} GB"


_CARACTERES_DE_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")


def _nome_seguro(nome: str) -> str:
    """Descarta qualquer caminho e caracteres de controle; preserva acentuação."""
    base = Path(nome).name or "arquivo"
    return _CARACTERES_DE_CONTROLE.sub("", base).strip() or "arquivo"


def criar_token() -> str:
    return secrets.token_urlsafe(16)


def _pasta(token: str) -> Path:
    return Path(settings.RASCUNHOS_DIR) / token


def _validar(nome: str, tamanho: int, existentes: list[AnexoRascunho]) -> None:
    """As regras que valem para QUALQUER origem de anexo.

    Ficam num lugar só de propósito: hoje o upload do navegador e o `--anexo` do
    `manage.py enviar` entram por aqui. Se a linha de comando aceitasse o que o
    formulário recusa (ou o contrário), "funciona no navegador e não no
    terminal" viraria um relatório de bug para você mesmo.
    """
    extensao = Path(nome).suffix.lstrip(".").lower()
    if extensao in settings.ANEXOS_EXTENSOES_BLOQUEADAS:
        raise ErroAnexo(f"Tipo de arquivo não permitido: .{extensao} ({nome}).")
    if tamanho > settings.ANEXO_MAX_BYTES:
        raise ErroAnexo(
            f"{nome} tem {_tamanho_legivel(tamanho)}, acima do limite de "
            f"{_tamanho_legivel(settings.ANEXO_MAX_BYTES)} por arquivo."
        )
    if len(existentes) >= settings.ANEXOS_MAX_ARQUIVOS:
        raise ErroAnexo(f"Limite de {settings.ANEXOS_MAX_ARQUIVOS} anexos por mensagem atingido.")
    if sum(a.tamanho for a in existentes) + tamanho > settings.ANEXOS_MAX_TOTAL_BYTES:
        raise ErroAnexo(
            f"Anexar {nome} passaria do limite de "
            f"{_tamanho_legivel(settings.ANEXOS_MAX_TOTAL_BYTES)} somando todos os anexos."
        )


def _tipo_de(nome: str) -> str:
    tipo, _ = mimetypes.guess_type(nome)
    return tipo or "application/octet-stream"


def salvar_anexo(token: str, arquivo: UploadedFile) -> AnexoRascunho:
    """Valida e grava um arquivo enviado. Levanta `ErroAnexo` com a explicação."""
    nome = _nome_seguro(arquivo.name or "arquivo")
    _validar(nome, arquivo.size, listar_anexos(token))

    pasta = _pasta(token)
    pasta.mkdir(parents=True, exist_ok=True)
    id_ = secrets.token_hex(8)
    destino = pasta / f"{id_}__{nome}"
    with destino.open("wb") as saida:
        for pedaco in arquivo.chunks():
            saida.write(pedaco)

    return AnexoRascunho(id=id_, nome=nome, tamanho=arquivo.size, tipo=_tipo_de(nome))


def listar_anexos(token: str) -> list[AnexoRascunho]:
    if not token:
        return []
    pasta = _pasta(token)
    if not pasta.is_dir():
        return []
    itens = []
    for caminho in sorted(pasta.iterdir()):
        id_, separador, nome = caminho.name.partition("__")
        if not separador:
            continue
        itens.append(
            AnexoRascunho(
                id=id_, nome=nome, tamanho=caminho.stat().st_size, tipo=_tipo_de(nome)
            )
        )
    return itens


def remover_anexo(token: str, anexo_id: str) -> None:
    pasta = _pasta(token)
    if not pasta.is_dir():
        return
    for caminho in pasta.iterdir():
        if caminho.name.startswith(f"{anexo_id}__"):
            caminho.unlink(missing_ok=True)
            return


def inspecionar_caminhos(
    caminhos: list[str], existentes: list[AnexoRascunho] = ()
) -> list[AnexoRascunho]:
    """Valida arquivos do disco local **sem gravar nada**, e os descreve.

    É o que o `--conferir` do `manage.py enviar` usa. Como a prévia da tela (ver
    `views._previa_de`), não precisa dos bytes: anexo nunca aparece no corpo
    HTML, vira parte MIME separada. O `id` sai vazio porque id só existe depois
    de haver pasta de rascunho.
    """
    acumulado = list(existentes)
    descritos: list[AnexoRascunho] = []
    for bruto in caminhos:
        caminho = Path(bruto).expanduser()
        if not caminho.is_file():
            raise ErroAnexo(f"Anexo não encontrado: {bruto}")
        try:
            tamanho = caminho.stat().st_size
        except OSError as exc:
            raise ErroAnexo(f"Não consegui ler {bruto}: {exc}") from exc
        nome = _nome_seguro(caminho.name)
        _validar(nome, tamanho, acumulado)
        descrito = AnexoRascunho(id="", nome=nome, tamanho=tamanho, tipo=_tipo_de(nome))
        acumulado.append(descrito)
        descritos.append(descrito)
    return descritos


def guardar_caminhos(token: str, caminhos: list[str]) -> list[AnexoRascunho]:
    """Copia arquivos do disco local para a pasta de rascunho do token.

    Valida **tudo** antes de copiar qualquer coisa: metade dos anexos gravada e
    a outra metade recusada seria o pior dos mundos. Depois disso o rascunho é
    igual a um vindo do navegador — é o que permite a linha de comando agendar
    com anexo sem um segundo caminho de código.
    """
    inspecionar_caminhos(caminhos, listar_anexos(token))
    pasta = _pasta(token)
    pasta.mkdir(parents=True, exist_ok=True)
    guardados = []
    for bruto in caminhos:
        origem = Path(bruto).expanduser()
        nome = _nome_seguro(origem.name)
        id_ = secrets.token_hex(8)
        shutil.copyfile(origem, pasta / f"{id_}__{nome}")
        guardados.append(
            AnexoRascunho(
                id=id_, nome=nome, tamanho=origem.stat().st_size, tipo=_tipo_de(nome)
            )
        )
    return guardados


def ler_anexos(token: str) -> list[Anexo]:
    """Conteúdo completo dos anexos do rascunho — só chamado na hora de enviar."""
    if not token:
        return []
    pasta = _pasta(token)
    return [
        Anexo(
            nome=item.nome,
            conteudo=(pasta / f"{item.id}__{item.nome}").read_bytes(),
            tipo=item.tipo,
        )
        for item in listar_anexos(token)
    ]


def transferir_rascunho(token: str) -> str:
    """Move os anexos para um token novo e devolve o novo. `""` se não havia nada.

    Serve para um agendamento tomar posse dos arquivos. Sem isso, dois
    agendamentos feitos a partir do mesmo rascunho (um "voltar" no navegador e
    reenviar o POST) compartilhariam a pasta, e o primeiro despacho — que limpa
    o rascunho ao concluir — levaria os anexos do segundo, que sairia **sem
    anexo, em silêncio**.

    Preferimos tornar a invariante verdadeira por construção ("cada
    agendamento é dono dos seus arquivos") a checar o caso na hora de apagar.
    """
    if not token:
        return ""
    origem = _pasta(token)
    if not origem.is_dir():
        return ""
    novo = criar_token()
    origem.rename(_pasta(novo))
    return novo


def copiar_rascunho(token: str) -> str:
    """Copia os anexos para um token novo e devolve o novo. `""` se não havia nada.

    É o que permite **editar** uma mensagem guardada sem tocar nela: a tela de
    edição trabalha na cópia (adiciona, remove, abandona) e só na hora de salvar
    a cópia substitui a original. Mexer direto na pasta do agendamento deixaria o
    despacho enxergar uma edição pela metade — ou uma abandonada.
    """
    if not token:
        return ""
    origem = _pasta(token)
    if not origem.is_dir():
        return ""
    novo = criar_token()
    shutil.copytree(origem, _pasta(novo))
    return novo


def resumo_dos_anexos(token: str) -> list[dict]:
    """Nome, tamanho e tipo dos anexos do token, no formato de `RegistroEnvio.anexos`."""
    return [
        {"nome": a.nome, "tamanho": a.tamanho, "tipo": a.tipo} for a in listar_anexos(token)
    ]


def limpar_rascunho(token: str) -> None:
    """Apaga a pasta inteira do rascunho — chamado depois de um envio bem-sucedido."""
    if token:
        shutil.rmtree(_pasta(token), ignore_errors=True)


def limpar_rascunhos_expirados(ttl_dias: int, tokens_protegidos: Iterable[str] = ()) -> int:
    """Apaga rascunhos abandonados. Usado pelo comando `limpar_rascunhos`.

    `tokens_protegidos` **não é refinamento**: mensagem agendada guarda os
    anexos aqui até a hora de sair, e um agendamento para daqui a 10 dias
    passaria do TTL de 7. Pior: `ler_anexos()` devolve `[]` para pasta
    inexistente, então a mensagem sairia **sem os anexos, em silêncio**, em vez
    de falhar. Quem passa a lista é o comando `limpar_rascunhos`.
    """
    raiz = Path(settings.RASCUNHOS_DIR)
    if not raiz.is_dir():
        return 0

    protegidos = set(tokens_protegidos)
    limite = time.time() - ttl_dias * 86400
    apagados = 0
    for pasta in raiz.iterdir():
        if not pasta.is_dir() or pasta.name in protegidos:
            continue
        arquivos = list(pasta.iterdir())
        referencia = max((a.stat().st_mtime for a in arquivos), default=pasta.stat().st_mtime)
        if referencia < limite:
            shutil.rmtree(pasta, ignore_errors=True)
            apagados += 1
    return apagados
