"""Dados que o menu lateral precisa em toda tela."""

from django.db.models import Count

from .models import EnvioAgendado


def navegacao(request):
    """Contagens do menu e a página ativa.

    Só para quem está logado: a tela de entrada não tem menu, e duas consultas
    a mais numa página pública seriam gasto à toa.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    Status = EnvioAgendado.Status
    contagens = {
        linha["status"]: linha["total"]
        for linha in EnvioAgendado.objects.filter(
            status__in=(Status.AGENDADO, Status.RASCUNHO)
        )
        .values("status")
        .annotate(total=Count("pk"))
    }
    atual = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
    return {
        "menu_agendados": contagens.get(Status.AGENDADO, 0),
        "menu_rascunhos": contagens.get(Status.RASCUNHO, 0),
        "menu_ativo": {
            "inicio": "enviados", "historico": "enviados", "registro": "enviados",
            "agendados": "agendados", "agendado": "agendados",
            "rascunhos": "rascunhos", 
        }.get(atual, ""),
    }
