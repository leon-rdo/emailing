"""Dados que o menu lateral precisa em toda tela."""

from django.db.models import Count
from django.urls import reverse

from .models import ContaEmail, EnvioAgendado
from .templatetags.mensagens_ui import matiz

_SECAO = {
    "inicio": "enviados", "historico": "enviados", "registro": "enviados",
    "agendados": "agendados", "agendado": "agendados",
    "rascunhos": "rascunhos",
    "config_contas": "contas", "config_conta_nova": "contas", "config_conta": "contas",
    "config_aliases": "aliases", "config_alias_novo": "aliases", "config_alias": "aliases",
}
_LISTA_DA_SECAO = {
    "enviados": "mensagens:historico",
    "agendados": "mensagens:agendados",
    "rascunhos": "mensagens:rascunhos",
}


def navegacao(request):
    """Caixas, contagens e a seção ativa do menu.

    Só para quem está logado: a tela de entrada não tem menu, e consultas a
    mais numa página pública seriam gasto à toa.

    `?caixa=<id>` filtra as listas por caixa (conta SMTP). O menu carrega esse
    parâmetro adiante nos links, para a escolha não se perder ao trocar de lista.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    contas = list(ContaEmail.objects.filter(ativa=True))
    bruto = request.GET.get("caixa", "")
    caixa = next((c for c in contas if bruto.isdigit() and c.pk == int(bruto)), None)

    Status = EnvioAgendado.Status
    fila = EnvioAgendado.objects.filter(status__in=(Status.AGENDADO, Status.RASCUNHO))
    if caixa:
        fila = fila.filter(alias__conta=caixa)
    contagens = {x["status"]: x["total"] for x in fila.values("status").annotate(total=Count("pk"))}

    atual = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
    secao = _SECAO.get(atual, "")
    base = reverse(_LISTA_DA_SECAO.get(secao, "mensagens:historico"))
    caixas = []
    if len(contas) > 1:
        caixas = [
            {
                "pk": c.pk, "nome": c.nome, "url": f"{base}?caixa={c.pk}",
                "matiz": matiz((c.dominios or [c.nome])[0]),
                "ativa": caixa is not None and c.pk == caixa.pk,
            }
            for c in contas
        ]
    return {
        "menu_agendados": contagens.get(Status.AGENDADO, 0),
        "menu_rascunhos": contagens.get(Status.RASCUNHO, 0),
        "menu_ativo": secao,
        "menu_em_lista": secao in _LISTA_DA_SECAO,
        "menu_caixas": caixas,
        "menu_todas_url": base,
        "menu_caixa": caixa,
        "menu_caixa_qs": f"?caixa={caixa.pk}" if caixa else "",
    }
