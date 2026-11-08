"""Caixa de entrada por IMAP, sob demanda — só para o servidor MCP.

A tela continua sem caixa de entrada (ver PRODUCT.md); quem lê é o Claude Code,
por `mcp_servidor.py`. Três regras que parecem excesso de cuidado e não são:

1. **Nada é guardado.** Cada operação abre uma conexão, faz o que tem que fazer
   e sai; os bytes da mensagem vivem só em memória, como na importação de
   `.eml` (`views.importar_eml`). Não há cópia local da caixa para divergir da
   real, nem correspondência de terceiros no disco ou no backup.
2. **Ler não muda a caixa.** Busca e leitura abrem a pasta com `EXAMINE`
   (`readonly=True`) e pedem `BODY.PEEK[]`: a mensagem continua não lida no
   webmail. Mudar estado (`marcar`, `mover`) é outra função, com outra tool e
   outra aprovação.
3. **Mover nunca faz `EXPUNGE` geral.** Sem `MOVE` (RFC 6851), a alternativa
   segura é `COPY` + `\\Deleted` + `UID EXPUNGE` (UIDPLUS, RFC 4315), que apaga
   só aquela UID. Um `EXPUNGE` puro apagaria de vez **toda** mensagem que outro
   cliente tivesse marcado como `\\Deleted` na pasta — então, sem UIDPLUS,
   `mover` recusa.

As mensagens são identificadas pelo par (UIDVALIDITY, UID) da pasta. UID
sozinha não basta: se o servidor renumerar a pasta, a mesma UID passa a ser
outra mensagem, e marcar ou mover a errada seria silencioso.
"""

from __future__ import annotations

import base64
import imaplib
import logging
import re
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from email import policy
from email.parser import BytesHeaderParser, BytesParser
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from django.conf import settings

from .models import ContaEmail
from .saneamento import html_para_texto, limpar_html

logger = logging.getLogger(__name__)

_MESES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_CABECALHOS_DA_LISTA = "FROM TO CC SUBJECT DATE MESSAGE-ID CONTENT-TYPE"

_UID = re.compile(rb"\bUID (\d+)")
_FLAGS = re.compile(rb"\bFLAGS \(([^)]*)\)")
_TAMANHO = re.compile(rb"\bRFC822\.SIZE (\d+)")
_LINHA_LIST = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<sep>"(?:[^"\\]|\\.)*"|NIL)\s*(?P<nome>.*)$')
_USOS_ESPECIAIS = {"\\sent", "\\trash", "\\junk", "\\drafts", "\\archive", "\\all", "\\flagged"}


class ErroCaixa(Exception):
    """A mensagem já é o texto para mostrar a quem pediu."""


# ---------------------------------------------------------------------------
# Identificador opaco
# ---------------------------------------------------------------------------


def id_de(conta: ContaEmail, uidvalidity: int, uid: int, pasta: str) -> str:
    """A pasta vai por último porque pode conter `:`."""
    return f"{conta.pk}:{uidvalidity}:{uid}:{pasta}"


@dataclass(frozen=True)
class Referencia:
    conta: ContaEmail
    uidvalidity: int
    uid: int
    pasta: str


def abrir_id(texto: str) -> Referencia:
    partes = (texto or "").split(":", 3)
    try:
        conta_pk, uidvalidity, uid = (int(p) for p in partes[:3])
        pasta = partes[3]
    except (IndexError, ValueError) as exc:
        raise ErroCaixa(
            f"Identificador de mensagem inválido: {texto!r}. "
            "Use o `id` devolvido por buscar_emails."
        ) from exc
    conta = ContaEmail.objects.filter(pk=conta_pk, ativa=True).first()
    if conta is None:
        raise ErroCaixa("A caixa desta mensagem não existe mais ou foi desativada.")
    return Referencia(conta, uidvalidity, uid, pasta)


# ---------------------------------------------------------------------------
# Nomes de pasta: UTF-7 modificado (RFC 3501 §5.1.3) e aspas
# ---------------------------------------------------------------------------


def decodificar_pasta(nome: str) -> str:
    def trocar(m: re.Match) -> str:
        miolo = m.group(1)
        if not miolo:
            return "&"
        b64 = miolo.replace(",", "/")
        b64 += "=" * (-len(b64) % 4)
        try:
            return base64.b64decode(b64).decode("utf-16-be")
        except (ValueError, UnicodeDecodeError):
            return m.group(0)

    return re.sub(r"&([A-Za-z0-9+,]*)-", trocar, nome)


def codificar_pasta(nome: str) -> str:
    saida: list[str] = []
    pendente: list[str] = []

    def descarregar():
        if pendente:
            b64 = base64.b64encode("".join(pendente).encode("utf-16-be")).decode("ascii")
            saida.append("&" + b64.rstrip("=").replace("/", ",") + "-")
            pendente.clear()

    for caractere in nome:
        if 0x20 <= ord(caractere) <= 0x7E:
            descarregar()
            saida.append("&-" if caractere == "&" else caractere)
        else:
            pendente.append(caractere)
    descarregar()
    return "".join(saida)


def _citar(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _pasta_no_fio(nome: str) -> str:
    return _citar(codificar_pasta(nome))


# ---------------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------------


def _explicar(exc: Exception, host: str, porta: int) -> str:
    if isinstance(exc, ssl.SSLError):
        return f"A conexão segura com {host}:{porta} falhou. IMAP aqui é só SSL direto (993)."
    if isinstance(exc, TimeoutError):
        return f"{host}:{porta} não respondeu a tempo. Confira o servidor IMAP e a porta."
    if isinstance(exc, OSError):
        return f"Não foi possível conectar a {host}:{porta} ({exc.strerror or exc})."
    return f"O servidor IMAP respondeu com erro: {exc}"


def _abrir(host: str, porta: int, usuario: str, senha: str, timeout: int) -> imaplib.IMAP4_SSL:
    try:
        imap = imaplib.IMAP4_SSL(
            host, porta, timeout=timeout, ssl_context=ssl.create_default_context()
        )
    except (OSError, imaplib.IMAP4.error) as exc:
        raise ErroCaixa(_explicar(exc, host, porta)) from exc
    try:
        imap.login(usuario, senha)
    except imaplib.IMAP4.error as exc:
        _sair(imap)
        raise ErroCaixa(f"O servidor IMAP {host} recusou o usuário ou a senha.") from exc
    except OSError as exc:
        _sair(imap)
        raise ErroCaixa(_explicar(exc, host, porta)) from exc
    return imap


def _sair(imap) -> None:
    try:
        imap.logout()
    except Exception:  # noqa: BLE001 — sair é melhor-esforço; o erro que importa já foi dito
        pass


def testar_login(host: str, porta: int, usuario: str, senha: str, timeout: int) -> None:
    """Conecta e autentica, nada mais. Usado pelo "Testar conexão" da tela."""
    _sair(_abrir(host, porta, usuario, senha, timeout))


@contextmanager
def sessao(conta: ContaEmail) -> Iterator[imaplib.IMAP4_SSL]:
    """Uma conexão por operação: login → operação → logout."""
    if not conta.imap_host:
        raise ErroCaixa(
            f"A caixa {conta.usuario} não tem servidor IMAP configurado "
            "(Configurações → Contas SMTP → Recebimento)."
        )
    imap = _abrir(conta.imap_host, conta.imap_porta, conta.usuario, conta.senha, conta.timeout)
    try:
        yield imap
    except (imaplib.IMAP4.error, OSError) as exc:
        raise ErroCaixa(_explicar(exc, conta.imap_host, conta.imap_porta)) from exc
    finally:
        _sair(imap)


def _capacidades(imap) -> set[str]:
    # Depois do login: vários servidores só anunciam MOVE/UIDPLUS autenticados,
    # e o `imap.capabilities` do imaplib é o de antes do login.
    tipo, dados = imap.capability()
    if tipo != "OK" or not dados or not dados[0]:
        return set()
    return {c.upper() for c in dados[0].decode("ascii", "replace").split()}


def _selecionar(imap, pasta: str, *, escrita: bool = False) -> int:
    """Abre a pasta e devolve o UIDVALIDITY. Sem `escrita`, é `EXAMINE`."""
    tipo, dados = imap.select(_pasta_no_fio(pasta), readonly=not escrita)
    if tipo != "OK":
        detalhe = dados[0].decode("utf-8", "replace") if dados and dados[0] else ""
        raise ErroCaixa(
            f"Não consegui abrir a pasta {pasta!r} ({detalhe}). Veja os nomes com listar_pastas."
        )
    _, valores = imap.response("UIDVALIDITY")
    try:
        return int(valores[0])
    except (IndexError, TypeError, ValueError):
        return 0


def _conferir_validade(atual: int, esperado: int) -> None:
    if atual != esperado:
        raise ErroCaixa(
            "A pasta foi renumerada pelo servidor desde a busca (UIDVALIDITY mudou). "
            "Busque de novo para obter identificadores válidos."
        )


def _existe(imap, uid: int) -> bytes:
    """Devolve a linha de FETCH (FLAGS RFC822.SIZE) da UID, ou levanta."""
    tipo, dados = imap.uid("FETCH", str(uid), "(FLAGS RFC822.SIZE)")
    for item in dados or []:
        linha = item[0] if isinstance(item, tuple) else item
        if isinstance(linha, bytes) and _UID.search(linha):
            return linha
    raise ErroCaixa("Mensagem não encontrada: foi apagada ou movida desde a busca.")


def _flags(linha: bytes) -> set[str]:
    m = _FLAGS.search(linha)
    return {f.lower() for f in m.group(1).decode("ascii", "replace").split()} if m else set()


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------


@dataclass
class Pasta:
    nome: str
    uso: str  # "\\Sent", "\\Trash"… (RFC 6154) ou vazio


def listar_pastas(conta: ContaEmail) -> list[Pasta]:
    with sessao(conta) as imap:
        tipo, dados = imap.list()
    if tipo != "OK":
        raise ErroCaixa("O servidor IMAP não devolveu a lista de pastas.")
    pastas = []
    for item in dados or []:
        if item is None:
            continue
        if isinstance(item, tuple):  # nome veio como literal {n}
            meta, nome_bruto = item[0], item[1]
        else:
            meta, nome_bruto = item, None
        m = _LINHA_LIST.match(meta.strip())
        if not m:
            continue
        flags = m.group("flags").decode("ascii", "replace").split()
        if any(f.lower() == "\\noselect" for f in flags):
            continue
        if nome_bruto is None:
            nome_bruto = m.group("nome").strip()
            if nome_bruto.startswith(b'"') and nome_bruto.endswith(b'"'):
                nome_bruto = re.sub(rb"\\(.)", rb"\1", nome_bruto[1:-1])
        nome = decodificar_pasta(nome_bruto.decode("utf-8", "replace"))
        uso = next((f for f in flags if f.lower() in _USOS_ESPECIAIS), "")
        pastas.append(Pasta(nome=nome, uso=uso))
    return pastas


@dataclass
class Filtro:
    texto: str = ""
    de: str = ""
    para: str = ""
    desde: date | None = None
    ate: date | None = None  # inclusivo
    nao_lidas: bool = False


def _data_imap(d: date) -> str:
    return f"{d.day:02d}-{_MESES[d.month - 1]}-{d.year}"


def _criterios(filtro: Filtro) -> tuple[list[str], bytes | None]:
    """Critérios de busca (os mesmos para `SEARCH` e `SORT`), e o literal UTF-8
    se houver. O charset não vai aqui: no `SEARCH` ele é `CHARSET UTF-8`, no
    `SORT` é posicional — quem monta o comando é que sabe.

    O imaplib só manda **um** literal por comando, e sempre no fim. Por isso o
    critério com acento (texto ou remetente) vai por último, e só um pode tê-lo.
    """
    partes: list[str] = []
    literal: tuple[str, bytes] | None = None

    for chave, valor in (("FROM", filtro.de), ("TEXT", filtro.texto)):
        valor = (valor or "").strip()
        if not valor:
            continue
        if valor.isascii():
            partes += [chave, _citar(valor)]
        elif literal is None:
            literal = (chave, valor.encode("utf-8"))
        else:
            raise ErroCaixa(
                "Só um dos filtros (texto ou remetente) pode ter acento por busca; "
                "tire o acento de um deles."
            )
    para = (filtro.para or "").strip()
    if para:
        if not para.isascii():
            raise ErroCaixa("O filtro `para` precisa ser um endereço sem acento.")
        partes += ["OR", "TO", _citar(para), "CC", _citar(para)]
    if filtro.desde:
        partes += ["SINCE", _data_imap(filtro.desde)]
    if filtro.ate:
        partes += ["BEFORE", _data_imap(filtro.ate + timedelta(days=1))]
    if filtro.nao_lidas:
        partes.append("UNSEEN")

    if literal:
        return [*partes, literal[0]], literal[1]
    return partes or ["ALL"], None


@dataclass
class Envelope:
    uid: int
    data: str
    de: str
    para: str
    cc: str
    assunto: str
    message_id: str
    lida: bool
    sinalizada: bool
    tamanho: int
    tem_anexo: bool  # aproximação: Content-Type multipart/mixed


@dataclass
class ResultadoBusca:
    uidvalidity: int
    total: int
    ordem: str = "data"
    envelopes: list[Envelope] = field(default_factory=list)


def _cabecalho(msg, nome: str) -> str:
    try:
        return str(msg.get(nome, "") or "").strip()
    except Exception:  # noqa: BLE001 — cabeçalho torto de terceiros não derruba a lista
        return ""


def _data_iso(bruto: str) -> str:
    try:
        return parsedate_to_datetime(bruto).isoformat()
    except (TypeError, ValueError, IndexError):
        return bruto


def _respostas_de_fetch(dados) -> Iterator[tuple[bytes, bytes]]:
    """(meta, literal) por mensagem. Alguns servidores mandam FLAGS depois do
    literal, num item `bytes` solto — ele é colado de volta na meta."""
    itens = list(dados or [])
    for i, item in enumerate(itens):
        if not isinstance(item, tuple):
            continue
        meta, literal = item[0], item[1]
        if i + 1 < len(itens) and isinstance(itens[i + 1], bytes):
            meta = meta + b" " + itens[i + 1]
        yield meta, literal


def _conjunto(uids) -> str:
    """UIDs como conjunto IMAP compacto: `1:40,42,50:60`. Uma janela de 2.000
    UIDs listados um a um passaria do tamanho de linha que alguns servidores
    aceitam; em faixas, costuma caber em poucas dezenas de bytes."""
    faixas: list[str] = []
    ordenados = sorted(set(uids))
    inicio = anterior = ordenados[0]
    for uid in ordenados[1:] + [None]:
        if uid is not None and uid == anterior + 1:
            anterior = uid
            continue
        faixas.append(str(inicio) if inicio == anterior else f"{inicio}:{anterior}")
        if uid is not None:
            inicio = anterior = uid
    return ",".join(faixas)


def _instante(bruto: str) -> float:
    try:
        return parsedate_to_datetime(bruto).timestamp()
    except (TypeError, ValueError, IndexError, OverflowError):
        return 0.0  # sem data legível: vai para o fim, na ordem de chegada


def _por_data_no_cliente(imap, uids: list[int], limite: int) -> list[int]:
    """As `limite` mais novas pelo cabeçalho `Date`, sem `SORT` no servidor.

    UID é ordem de chegada **na pasta**, não data: mensagem que um filtro ou
    outro cliente moveu para lá depois ganha UID maior que outras mais novas
    (foi assim que a pasta Promoções mostrou 11/10 antes de 26/10). Então lê só
    o `Date` de cada uma e ordena aqui.
    """
    if not uids:
        return []
    tipo, dados = imap.uid("FETCH", _conjunto(uids), "(UID BODY.PEEK[HEADER.FIELDS (DATE)])")
    datas: dict[int, float] = {}
    for meta, literal in _respostas_de_fetch(dados):
        m_uid = _UID.search(meta)
        if m_uid:
            msg = BytesHeaderParser(policy=policy.default).parsebytes(literal or b"")
            datas[int(m_uid.group(1))] = _instante(_cabecalho(msg, "Date"))
    return sorted(uids, key=lambda u: (datas.get(u, 0.0), u), reverse=True)[:limite]


def buscar(conta: ContaEmail, pasta: str, filtro: Filtro, limite: int) -> ResultadoBusca:
    """As `limite` mensagens mais novas **pela data do e-mail** que casam com o
    filtro, da mais nova para a mais velha. Só cabeçalhos, com `BODY.PEEK`:
    nada fica lido.

    Com `SORT` (RFC 5256, a Hostinger tem) quem ordena é o servidor, sobre a
    pasta inteira. Sem ele (a GoDaddy não tem), ordena-se aqui, sobre as
    `IMAP_JANELA_ORDENACAO` mais recentes por chegada — e `ordem` diz quando a
    janela cortou alguma coisa, em vez de fingir que a ordem é exata.
    """
    criterios, literal = _criterios(filtro)
    limite = max(limite, 0)
    with sessao(conta) as imap:
        tem_sort = "SORT" in _capacidades(imap)
        uidvalidity = _selecionar(imap, pasta)
        if literal is not None:
            imap.literal = literal
        if tem_sort:
            tipo, dados = imap.uid("SORT", "(REVERSE DATE)", "UTF-8", *criterios)
        else:
            prefixo = ["CHARSET", "UTF-8"] if literal is not None else []
            tipo, dados = imap.uid("SEARCH", *prefixo, *criterios)
        if tipo != "OK":
            raise ErroCaixa("O servidor IMAP recusou a busca. Simplifique os filtros.")
        uids = [int(u) for u in (dados[0] or b"").split()] if dados and dados[0] else []

        resultado = ResultadoBusca(uidvalidity=uidvalidity, total=len(uids))
        if tem_sort:
            escolhidas = uids[:limite]
        else:
            janela = sorted(uids)[-settings.IMAP_JANELA_ORDENACAO:]
            if len(janela) < len(uids):
                resultado.ordem = (
                    f"data, entre as {len(janela)} que chegaram por último à pasta "
                    "(o servidor não ordena; refine com desde/ate para ver as mais antigas)"
                )
            escolhidas = _por_data_no_cliente(imap, janela, limite) if limite else []
        if not escolhidas:
            return resultado
        tipo, dados = imap.uid(
            "FETCH",
            _conjunto(escolhidas),
            f"(UID FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({_CABECALHOS_DA_LISTA})])",
        )

    por_uid: dict[int, Envelope] = {}
    for meta, literal_bruto in _respostas_de_fetch(dados):
        m_uid = _UID.search(meta)
        if not m_uid:
            continue
        msg = BytesHeaderParser(policy=policy.default).parsebytes(literal_bruto or b"")
        flags = _flags(meta)
        m_tam = _TAMANHO.search(meta)
        por_uid[int(m_uid.group(1))] = Envelope(
            uid=int(m_uid.group(1)),
            data=_data_iso(_cabecalho(msg, "Date")),
            de=_cabecalho(msg, "From"),
            para=_cabecalho(msg, "To"),
            cc=_cabecalho(msg, "Cc"),
            assunto=_cabecalho(msg, "Subject"),
            message_id=_cabecalho(msg, "Message-ID"),
            lida="\\seen" in flags,
            sinalizada="\\flagged" in flags,
            tamanho=int(m_tam.group(1)) if m_tam else 0,
            tem_anexo=_cabecalho(msg, "Content-Type").lower().startswith("multipart/mixed"),
        )
    resultado.envelopes = [por_uid[u] for u in escolhidas if u in por_uid]
    return resultado


@dataclass
class MensagemBruta:
    bruto: bytes
    lida: bool
    sinalizada: bool


def ler(ref: Referencia) -> MensagemBruta:
    """Os bytes da mensagem, em memória. `BODY.PEEK[]`: continua não lida."""
    with sessao(ref.conta) as imap:
        _conferir_validade(_selecionar(imap, ref.pasta), ref.uidvalidity)
        linha = _existe(imap, ref.uid)
        m_tam = _TAMANHO.search(linha)
        tamanho = int(m_tam.group(1)) if m_tam else 0
        if tamanho > settings.IMAP_MAX_BYTES:
            raise ErroCaixa(
                f"A mensagem tem {tamanho // (1024 * 1024)} MB, acima do limite de leitura "
                f"({settings.IMAP_MAX_BYTES // (1024 * 1024)} MB). Abra pelo webmail."
            )
        flags = _flags(linha)
        tipo, dados = imap.uid("FETCH", str(ref.uid), "(BODY.PEEK[])")
    for _meta, literal in _respostas_de_fetch(dados):
        return MensagemBruta(
            bruto=literal or b"", lida="\\seen" in flags, sinalizada="\\flagged" in flags
        )
    raise ErroCaixa("O servidor não devolveu o conteúdo da mensagem.")


@dataclass
class AnexoRecebido:
    nome: str
    tipo: str
    tamanho: int


@dataclass
class MensagemLida:
    cabecalhos: dict[str, str]
    corpo: str
    corpo_truncado: bool
    anexos: list[AnexoRecebido]
    links_encurtados: int = 0


_LINK = re.compile(r"https?://[^\s<>\"']+")
_LINK_MAX = 80


def encurtar_links(texto: str) -> tuple[str, int]:
    """Tira query string e fragmento dos links, e corta caminho longo, marcando
    com `…` onde cortou.

    Existe porque e-mail de marketing é feito mais de rastreamento que de texto:
    num do Mercado Livre lido em produção, a maior parte dos caracteres do corpo
    eram parâmetros `utm_*`/`matt_*` repetidos em cada link — contexto do modelo
    gasto em nada. O link inteiro continua disponível em `formato="html"`.
    Só vale para o que é **lido**: a parte texto do que o app envia sai de
    `saneamento.html_para_texto`, que não passa por aqui.
    """
    encurtados = 0

    def encurtar(m: re.Match) -> str:
        nonlocal encurtados
        url = m.group(0)
        try:
            partes = urlsplit(url)
        except ValueError:
            return url
        base = f"{partes.scheme}://{partes.netloc}{partes.path}"
        cortou = bool(partes.query or partes.fragment)
        if len(base) > _LINK_MAX:
            base, cortou = base[: _LINK_MAX - 1], True
        if not cortou:
            return url
        encurtados += 1
        return base + "…"

    return _LINK.sub(encurtar, texto), encurtados


def _conteudo(parte) -> str:
    try:
        return parte.get_content()
    except (LookupError, UnicodeError, ValueError):
        bruto = parte.get_payload(decode=True) or b""
        return bruto.decode(parte.get_content_charset() or "utf-8", errors="replace")


def interpretar(bruto: bytes, *, formato: str, limite: int) -> MensagemLida:
    """Cabeçalhos, corpo e anexos (só os metadados) de uma mensagem recebida.

    `formato="texto"` prefere a parte text/plain e, sem ela, converte o HTML; os
    links saem encurtados (ver `encurtar_links`), antes do corte em `limite`.
    `formato="html"` prefere o HTML, passado pelo mesmo sanitizador do que é
    colado no editor: é conteúdo de terceiros.
    """
    msg = BytesParser(policy=policy.default).parsebytes(bruto)
    cabecalhos = {
        nome.lower(): _cabecalho(msg, nome)
        for nome in ("From", "To", "Cc", "Reply-To", "Subject", "Date", "Message-ID",
                     "In-Reply-To")
    }
    cabecalhos["date"] = _data_iso(cabecalhos["date"])

    preferencia = ("plain", "html") if formato == "texto" else ("html", "plain")
    parte = msg.get_body(preferencelist=preferencia)
    corpo = ""
    if parte is not None:
        corpo = _conteudo(parte)
        tipo = parte.get_content_type()
        if formato == "texto" and tipo == "text/plain" and not corpo.strip():
            # Há remetente que manda text/plain vazio ao lado do HTML de verdade;
            # preferir a parte vazia devolveria um corpo em branco.
            html = msg.get_body(preferencelist=("html",))
            if html is not None:
                corpo, tipo = _conteudo(html), "text/html"
        if formato == "texto" and tipo == "text/html":
            corpo = html_para_texto(corpo)
        elif formato == "html":
            corpo = limpar_html(corpo) if tipo == "text/html" else corpo

    links_encurtados = 0
    if formato == "texto":
        corpo, links_encurtados = encurtar_links(corpo)

    truncado = len(corpo) > limite
    if truncado:
        corpo = corpo[:limite]

    anexos = []
    for anexo in msg.iter_attachments():
        try:
            tamanho = len(anexo.get_payload(decode=True) or b"")
        except Exception:  # noqa: BLE001 — anexo malformado ainda é listado
            tamanho = 0
        anexos.append(AnexoRecebido(
            nome=anexo.get_filename() or "(sem nome)",
            tipo=anexo.get_content_type(),
            tamanho=tamanho,
        ))
    return MensagemLida(
        cabecalhos=cabecalhos, corpo=corpo, corpo_truncado=truncado, anexos=anexos,
        links_encurtados=links_encurtados,
    )


# ---------------------------------------------------------------------------
# Escrita: marcar e mover
# ---------------------------------------------------------------------------


def marcar(ref: Referencia, *, lida: bool | None, sinalizada: bool | None) -> dict[str, bool]:
    """Liga ou desliga `\\Seen` e `\\Flagged`. Nenhuma outra flag."""
    mudancas = [(f, v) for f, v in (("\\Seen", lida), ("\\Flagged", sinalizada)) if v is not None]
    if not mudancas:
        raise ErroCaixa("Diga o que marcar: `lida` e/ou `sinalizada`.")
    with sessao(ref.conta) as imap:
        _conferir_validade(_selecionar(imap, ref.pasta, escrita=True), ref.uidvalidity)
        _existe(imap, ref.uid)
        for flag, valor in mudancas:
            tipo, _ = imap.uid("STORE", str(ref.uid), "+FLAGS" if valor else "-FLAGS", f"({flag})")
            if tipo != "OK":
                raise ErroCaixa(f"O servidor recusou mudar {flag}.")
        flags = _flags(_existe(imap, ref.uid))
    logger.info(
        "marcar conta=%s pasta=%r uid=%s %s",
        ref.conta.usuario, ref.pasta, ref.uid, dict(mudancas),
    )
    return {"lida": "\\seen" in flags, "sinalizada": "\\flagged" in flags}


def mover(ref: Referencia, destino: str) -> None:
    destino = (destino or "").strip()
    if not destino:
        raise ErroCaixa("Diga para qual pasta mover. Veja os nomes com listar_pastas.")
    if destino == ref.pasta:
        raise ErroCaixa(f"A mensagem já está em {destino!r}.")
    with sessao(ref.conta) as imap:
        capacidades = _capacidades(imap)
        _conferir_validade(_selecionar(imap, ref.pasta, escrita=True), ref.uidvalidity)
        _existe(imap, ref.uid)
        alvo = _pasta_no_fio(destino)
        uid = str(ref.uid)
        if "MOVE" in capacidades:
            tipo, dados = imap.uid("MOVE", uid, alvo)
        elif "UIDPLUS" in capacidades:
            tipo, dados = imap.uid("COPY", uid, alvo)
            if tipo == "OK":
                imap.uid("STORE", uid, "+FLAGS.SILENT", "(\\Deleted)")
                imap.uid("EXPUNGE", uid)
        else:
            raise ErroCaixa(
                "Este servidor não oferece MOVE nem UIDPLUS. Mover exigiria um EXPUNGE "
                "geral, que apagaria de vez outras mensagens marcadas para exclusão na "
                "pasta — por isso não movo. Mova pelo webmail."
            )
        if tipo != "OK":
            detalhe = dados[0].decode("utf-8", "replace") if dados and dados[0] else ""
            raise ErroCaixa(
                f"O servidor recusou mover para {destino!r} ({detalhe}). "
                "Confira o nome com listar_pastas."
            )
    logger.info(
        "mover conta=%s de=%r uid=%s para=%r", ref.conta.usuario, ref.pasta, ref.uid, destino
    )
