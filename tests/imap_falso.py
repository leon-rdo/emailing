"""Um servidor IMAP de mentira, no formato que o `imaplib` devolve.

Guarda as pastas em memória e registra cada comando em `comandos`, que é o que
os testes conferem: EXAMINE em vez de SELECT, `BODY.PEEK`, nenhum `EXPUNGE`
geral. Só implementa o que `mensagens/caixa.py` usa.
"""

from __future__ import annotations

import imaplib
import re
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import parsedate_to_datetime


def mensagem_de_exemplo(
    assunto="Proposta de parceria",
    de="Cliente <cliente@exemplo.test>",
    para="financeiro@leonardocosta.dev",
    message_id="<original@exemplo.test>",
    referencias="<primeira@exemplo.test>",
    texto="Olá, segue a proposta.\nAbraço.",
    html="<p>Olá, segue a <strong>proposta</strong>.</p><p>Abraço.</p>",
    anexo: bytes | None = b"%PDF-1.4 falso",
    data="Sat, 07 Nov 2026 10:30:00 -0300",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = de
    msg["To"] = para
    msg["Subject"] = assunto
    msg["Date"] = data
    msg["Message-ID"] = message_id
    if referencias:
        msg["References"] = referencias
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")
    if anexo is not None:
        msg.add_attachment(anexo, maintype="application", subtype="pdf", filename="proposta.pdf")
    return msg.as_bytes()


def _uids_de(conjunto: str) -> list[int]:
    """`1:3,7` → [1, 2, 3, 7]."""
    uids = []
    for parte in conjunto.split(","):
        if ":" in parte:
            inicio, fim = (int(x) for x in parte.split(":"))
            uids += range(inicio, fim + 1)
        else:
            uids.append(int(parte))
    return uids


def _instante(bruto: bytes) -> float:
    try:
        return parsedate_to_datetime(message_from_bytes(bruto)["Date"]).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _sem_aspas(nome: str) -> str:
    if nome.startswith('"') and nome.endswith('"'):
        return re.sub(r"\\(.)", r"\1", nome[1:-1])
    return nome


class ServidorFalso:
    def __init__(self, capacidades=("IMAP4REV1", "MOVE", "UIDPLUS")):
        self.capacidades = capacidades
        self.pastas: dict[str, dict[int, dict]] = {"INBOX": {}}
        self.uidvalidity: dict[str, int] = {"INBOX": 1000}
        self.proxima_uid: dict[str, int] = {"INBOX": 1}
        self.extras_list: list = []
        self.senha_certa = "segredo-de-teste"
        self.comandos: list[tuple] = []
        self.literais: list[bytes] = []

    def criar_pasta(self, nome: str, uidvalidity: int = 2000) -> None:
        self.pastas[nome] = {}
        self.uidvalidity[nome] = uidvalidity
        self.proxima_uid[nome] = 1

    def entregar(self, bruto: bytes, pasta="INBOX", flags=()) -> int:
        uid = self.proxima_uid[pasta]
        self.proxima_uid[pasta] += 1
        self.pastas[pasta][uid] = {"bruto": bruto, "flags": set(flags)}
        return uid

    def conexao(self, host, port=993, timeout=None, ssl_context=None):
        return ConexaoFalsa(self)


class ConexaoFalsa:
    def __init__(self, servidor: ServidorFalso):
        self.s = servidor
        self.selecionada: str | None = None
        self.literal: bytes | None = None
        self._respostas: dict[str, list] = {}

    # --- sessão -------------------------------------------------------------

    def login(self, usuario, senha):
        self.s.comandos.append(("LOGIN", usuario))
        if senha != self.s.senha_certa:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def logout(self):
        self.s.comandos.append(("LOGOUT",))
        return "BYE", [b""]

    def capability(self):
        return "OK", [" ".join(self.s.capacidades).encode()]

    def list(self):
        linhas = [b'(\\HasNoChildren) "/" "INBOX"']
        for nome in self.s.pastas:
            if nome != "INBOX":
                linhas.append(b'(\\HasNoChildren) "/" "' + nome.encode() + b'"')
        return "OK", linhas + self.s.extras_list

    def select(self, mailbox, readonly=False):
        nome = _sem_aspas(mailbox)
        self.s.comandos.append(("EXAMINE" if readonly else "SELECT", nome))
        if nome not in self.s.pastas:
            return "NO", [b"Mailbox doesn't exist"]
        self.selecionada = nome
        self._respostas["UIDVALIDITY"] = [str(self.s.uidvalidity[nome]).encode()]
        return "OK", [str(len(self.s.pastas[nome])).encode()]

    def response(self, codigo):
        return codigo, self._respostas.pop(codigo, [None])

    # --- comandos UID -------------------------------------------------------

    def uid(self, comando, *args):
        self.s.comandos.append(("UID", comando, *args))
        if self.literal is not None:
            self.s.literais.append(self.literal)
            self.literal = None
        pasta = self.s.pastas[self.selecionada]
        metodo = getattr(self, f"_uid_{comando.lower()}")
        return metodo(pasta, *args)

    def _filtrar(self, pasta, criterios):
        uids = sorted(pasta)
        if "UNSEEN" in criterios:
            uids = [u for u in uids if "\\Seen" not in pasta[u]["flags"]]
        return uids

    def _uid_search(self, pasta, *criterios):
        return "OK", [" ".join(str(u) for u in self._filtrar(pasta, criterios)).encode()]

    def _uid_sort(self, pasta, programa, charset, *criterios):
        assert programa == "(REVERSE DATE)" and charset == "UTF-8"
        uids = sorted(
            self._filtrar(pasta, criterios),
            key=lambda u: (_instante(pasta[u]["bruto"]), u), reverse=True,
        )
        return "OK", [" ".join(str(u) for u in uids).encode()]

    def _linha(self, uid, dados):
        flags = " ".join(sorted(dados["flags"]))
        return f"{uid} (UID {uid} FLAGS ({flags}) RFC822.SIZE {len(dados['bruto'])}".encode()

    def _uid_fetch(self, pasta, conjunto, itens):
        uids = _uids_de(conjunto)
        if itens == "(FLAGS RFC822.SIZE)":
            achadas = [self._linha(u, pasta[u]) + b")" for u in uids if u in pasta]
            return "OK", achadas or [None]
        resposta = []
        for uid in uids:
            if uid not in pasta:
                continue
            bruto = pasta[uid]["bruto"]
            if "HEADER.FIELDS" in itens:
                corpo = bruto.split(b"\n\n", 1)[0] + b"\n\n"
                rotulo = b" BODY[HEADER.FIELDS (...)]"
            else:
                assert "BODY.PEEK[]" in itens, itens  # nunca BODY[] — isso marcaria como lida
                corpo = bruto
                rotulo = b" BODY[]"
            resposta.append((self._linha(uid, pasta[uid]) + rotulo + b" {%d}" % len(corpo), corpo))
            resposta.append(b")")
        return "OK", resposta

    def _uid_store(self, pasta, uid, operacao, flags):
        nomes = flags.strip("()").split()
        dados = pasta.get(int(uid))
        if dados is None:
            return "OK", [None]
        if operacao.startswith("+"):
            dados["flags"].update(nomes)
        else:
            dados["flags"].difference_update(nomes)
        return "OK", [self._linha(int(uid), dados) + b")"]

    def _copiar(self, pasta, uid, destino):
        destino = _sem_aspas(destino)
        if destino not in self.s.pastas:
            return False
        self.s.entregar(pasta[int(uid)]["bruto"], destino, pasta[int(uid)]["flags"] - {"\\Deleted"})
        return True

    def _uid_move(self, pasta, uid, destino):
        if not self._copiar(pasta, uid, destino):
            return "NO", [b"[TRYCREATE] Mailbox doesn't exist"]
        del pasta[int(uid)]
        return "OK", [None]

    def _uid_copy(self, pasta, uid, destino):
        if not self._copiar(pasta, uid, destino):
            return "NO", [b"[TRYCREATE] Mailbox doesn't exist"]
        return "OK", [None]

    def _uid_expunge(self, pasta, uid):
        if "\\Deleted" in pasta[int(uid)]["flags"]:
            del pasta[int(uid)]
        return "OK", [None]
