"""Validar e descrever uma redação que não veio da tela.

Duas portas redigem fora do navegador: `manage.py enviar` e o servidor MCP
(`mcp_servidor.py`). As duas passam por aqui para não terem validação própria:
endereços, limite de destinatários, escolha de alias e formato de data saem do
`FormularioRedacao`, o mesmo da tela. Duas validações acabam divergindo, e o
sintoma seria "funciona no navegador e não no terminal" (ver docs/decisoes.md).

O que muda entre as portas é só a **forma** do erro: a CLI prefixa o campo com
`--`, o MCP não. Por isso `ErroRedacao` guarda os pares (campo, mensagem) e
cada porta escolhe como escrever.
"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from .aliases import alias_por_slug, carregar_aliases
from .forms import FormularioRascunho, FormularioRedacao, analisar_enviar_em, dados_do_formulario
from .models import Alias
from .montagem import DadosRedacao, montar_email

FORMATOS_DE_DATA = '"2026-09-10 09:00", "10/09/2026 09:00", "2026-09-10T09:00"'

# O que cada porta pode pedir. "conferir" é a prévia de quem não tem tela;
# "rascunho" é guardar, que não exige destinatário (ver `FormularioRascunho`).
MODOS = ("enviar", "conferir", "rascunho")


class ErroRedacao(Exception):
    """Erro de validação já em português, com o campo de cada mensagem.

    `campo` é `None` para erro que não é de um campo só (limite de
    destinatários, alias desconhecido).
    """

    def __init__(self, erros: list[tuple[str | None, str]]):
        self.erros = erros
        super().__init__(self.texto())

    def texto(self, prefixo: str = "") -> str:
        linhas = []
        for campo, mensagem in self.erros:
            if campo:
                linhas.append(f"{prefixo}{campo.replace('_', '-')}: {mensagem}")
            else:
                linhas.append(mensagem)
        return "\n".join(linhas)


def resolver_alias(slug: str) -> Alias:
    disponiveis = carregar_aliases()
    if not disponiveis:
        raise ErroRedacao([(None, (
            "Nenhum alias ativo cadastrado. Cadastre no admin ou rode "
            "`manage.py verificar_config` para ver o que está faltando."
        ))])
    try:
        return alias_por_slug(slug)
    except KeyError as exc:
        nomes = ", ".join(a.slug for a in disponiveis)
        raise ErroRedacao(
            [(None, f"Alias desconhecido: {slug!r}. Disponíveis: {nomes}.")]
        ) from exc


def analisar_quando(bruto: str) -> datetime:
    """Data de agendamento, pelos formatos da tela, e no futuro.

    O erro sai sem nome de campo: quem chama sabe se o campo se chama `--em`
    (CLI) ou `em` (MCP).
    """
    try:
        quando = analisar_enviar_em(bruto)
    except ValidationError as exc:
        raise ErroRedacao([(None, (
            f"{' '.join(exc.messages)} Formatos aceitos: {FORMATOS_DE_DATA}."
        ))]) from exc
    if quando <= timezone.now():
        local = timezone.localtime(quando).strftime("%d/%m/%Y %H:%M")
        raise ErroRedacao([(None, f"{local} já passou (fuso {settings.TIME_ZONE}).")])
    return quando


def preparar(alias: Alias, campos: dict, *, modo: str = "enviar") -> DadosRedacao:
    """`DadosRedacao` validado pelo mesmo formulário da tela.

    `campos` usa os nomes do formulário: para, cc, cco (texto com vírgulas),
    assunto, corpo, in_reply_to, referencias, citacao_html, sem_assinatura.

    No modo "conferir" as duas tolerâncias da prévia da tela se separam. "Sem
    destinatário" continua valendo — conferir é do conteúdo, e o destinatário
    costuma ser a última coisa que se decide. "Endereço inválido" não: na tela
    ele é descartado porque vem outra tecla atrás; aqui não vem nada atrás, e
    um endereço torto tem que doer agora, não no envio.
    """
    if modo not in MODOS:
        raise ValueError(f"modo desconhecido: {modo}")
    classe = FormularioRascunho if modo == "rascunho" else FormularioRedacao
    form = classe(
        data={
            "alias": alias.slug,
            "para": campos.get("para", ""),
            "cc": campos.get("cc", ""),
            "cco": campos.get("cco", ""),
            "assunto": campos.get("assunto", ""),
            "corpo": campos.get("corpo", ""),
            "in_reply_to": campos.get("in_reply_to", ""),
            "referencias": campos.get("referencias", ""),
            "citacao_html": campos.get("citacao_html", ""),
            "sem_assinatura": campos.get("sem_assinatura", False),
        },
        aliases=carregar_aliases(),
    )
    if modo == "conferir":
        form.fields["para"].minimo_um = False
    if not form.is_valid():
        erros: list[tuple[str | None, str]] = [(None, str(e)) for e in form.non_field_errors()]
        for campo, lista in form.errors.items():
            if campo == "__all__":
                continue
            erros += [(campo, str(erro)) for erro in lista]
        raise ErroRedacao(erros)
    return dados_do_formulario(form)


def descrever_conferencia(alias: Alias, dados: DadosRedacao, anexos, quando) -> dict:
    """O que sairia, pelo mesmo caminho do envio: `montar_email` é função pura,
    então isto é literalmente a mensagem final — envelope, HTML e texto, com
    assinatura e marcadores expandidos.

    `anexos` só é descrito (nome, tamanho, tipo): anexo nunca entra no corpo
    HTML, vira parte MIME separada.
    """
    mensagem = montar_email(dados, alias)
    return {
        "ok": True,
        "acao": "conferir",
        "alias": alias.slug,
        "remetente": alias.remetente,
        "envelope": alias.envelope,
        "reply_to": alias.reply_to,
        "para": dados.para,
        "cc": dados.cc,
        "cco": dados.cco,
        "assunto": dados.assunto,
        "in_reply_to": dados.in_reply_to,
        "referencias": dados.referencias,
        "assinatura": dados.assinatura,
        "agendar_para": quando.isoformat() if quando else None,
        "anexos": [{"nome": a.nome, "tamanho": a.tamanho, "tipo": a.tipo} for a in anexos],
        "html": mensagem.alternatives[0][0],
        "texto": mensagem.body,
    }
