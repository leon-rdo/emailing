"""Admin do Django, sem dependência externa.

`RegistroEnvio` é um log de auditoria: existe para provar o que foi enviado,
não para ser editado. Por isso as permissões de escrita são desligadas por
completo — inclusive apagar, porque um log de auditoria que pode ser apagado
não prova nada.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import RegistroEnvio

admin.site.site_header = "Emailing"
admin.site.site_title = "Emailing"
admin.site.index_title = "Painel"
admin.site.empty_value_display = "—"

_COR_SELO = {
    RegistroEnvio.Status.ENVIADO: "#1a7f47",
    RegistroEnvio.Status.FALHOU: "#b42318",
    RegistroEnvio.Status.ENVIANDO: "#6b7280",
}


@admin.register(RegistroEnvio)
class RegistroEnvioAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("mensagens/admin_extra.css",)}

    list_display = ("criado_em", "alias", "para_resumido", "assunto", "selo")
    list_filter = ("status", "alias", "criado_em")
    search_fields = ("assunto", "para", "cc", "cco", "remetente", "message_id")
    date_hierarchy = "criado_em"
    ordering = ("-criado_em",)

    fieldsets = (
        (None, {"fields": ("criado_em", "status", "erro")}),
        ("Envelope", {"fields": ("alias", "remetente", "para", "cc", "cco", "assunto")}),
        ("Cabeçalhos", {"fields": ("message_id", "in_reply_to", "referencias")}),
        ("Conteúdo", {"fields": ("anexos", "corpo_html")}),
    )
    readonly_fields = [f.name for f in RegistroEnvio._meta.fields]

    @admin.display(description="para")
    def para_resumido(self, obj):
        return obj.para if len(obj.para) <= 60 else obj.para[:57] + "…"

    @admin.display(description="status", ordering="status")
    def selo(self, obj):
        cor = _COR_SELO.get(obj.status, "#6b7280")
        return format_html(
            '<span style="color:{}; font-weight:600;">{}</span>', cor, obj.get_status_display()
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
