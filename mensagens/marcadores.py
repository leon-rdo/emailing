"""Marcadores `{{ nome }}`, trocados por valores no momento do envio.

A lista é **fechada de propósito**. O que não está aqui fica literal no
e-mail, como qualquer outro texto — foi assim que o `<%= Date.now() %>` de um
template EJS chegou escrito por extenso, e é assim que tem que ser: o app
nunca avalia o que você escreve no corpo, só troca nomes que ele mesmo
conhece por valores que ele mesmo produz. É a diferença entre uma
conveniência e uma porta de execução de código dentro do corpo do e-mail.

Os valores são escapados ao entrar no HTML, então nem um nome de alias com
`<` consegue injetar marcação.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from datetime import datetime

from django.utils import formats, timezone

# `{{ nome }}`, com espaço opcional. Nada de argumentos, filtros ou pontos:
# se não for um nome simples e conhecido, não é marcador.
_MARCADOR = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


@dataclass(frozen=True)
class Marcador:
    nome: str
    descricao: str
    exemplo: str


def _agora() -> datetime:
    return timezone.localtime()


def _valores(alias, dados) -> dict[str, str]:
    agora = _agora()
    primeiro_destinatario = dados.para[0] if dados.para else ""
    return {
        "data": formats.date_format(agora, "d/m/Y"),
        "data_extenso": formats.date_format(agora, "DATE_FORMAT"),
        "hora": formats.date_format(agora, "H:i"),
        "data_hora": formats.date_format(agora, "d/m/Y H:i"),
        "ano": str(agora.year),
        "remetente": alias.remetente,
        "remetente_nome": alias.nome_exibicao or alias.endereco,
        "remetente_email": alias.endereco,
        "destinatario": primeiro_destinatario,
        "assunto": dados.assunto,
    }


GLOSSARIO: list[Marcador] = [
    Marcador("data", "Data de hoje, em números.", "03/09/2026"),
    Marcador("data_extenso", "Data de hoje por extenso.", "3 de Setembro de 2026"),
    Marcador("hora", "Hora do envio.", "14:32"),
    Marcador("data_hora", "Data e hora do envio.", "03/09/2026 14:32"),
    Marcador("ano", "Ano corrente — útil em rodapé de copyright.", "2026"),
    Marcador("remetente", "O alias escolhido, com nome e endereço.", "Fulano <x@dominio.com>"),
    Marcador("remetente_nome", "Só o nome de exibição do alias.", "Fulano"),
    Marcador("remetente_email", "Só o endereço do alias.", "x@dominio.com"),
    Marcador("destinatario", "O primeiro endereço do campo Para.", "cliente@exemplo.com"),
    Marcador("assunto", "O assunto desta mensagem.", "Proposta comercial"),
]

NOMES = {m.nome for m in GLOSSARIO}


def expandir(texto: str, alias, dados, *, escapar_html: bool) -> str:
    """Troca os marcadores conhecidos. Nome desconhecido fica como está.

    `escapar_html` liga o escape dos valores — verdadeiro para o corpo HTML,
    falso para a parte em texto simples.
    """
    if not texto or "{{" not in texto:
        return texto

    valores = _valores(alias, dados)

    def substituir(achado: re.Match) -> str:
        nome = achado.group(1)
        if nome not in valores:
            return achado.group(0)  # não é nosso: fica literal
        valor = valores[nome]
        return _html.escape(valor) if escapar_html else valor

    return _MARCADOR.sub(substituir, texto)
