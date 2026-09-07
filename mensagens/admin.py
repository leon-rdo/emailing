"""Admin do Django, sem dependência externa.

`RegistroEnvio` é um log de auditoria: existe para provar o que foi enviado,
não para ser editado. Por isso as permissões de escrita são desligadas por
completo — inclusive apagar, porque um log de auditoria que pode ser apagado
não prova nada.

`ContaEmail` e `Alias`, ao contrário, existem justamente para serem
gerenciados aqui.
"""

from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import Alias, ContaEmail, EnvioAgendado, RegistroEnvio

admin.site.site_header = "Emailing"
admin.site.site_title = "Emailing"
admin.site.index_title = "Painel"
admin.site.empty_value_display = "—"

_COR_SELO = {
    RegistroEnvio.Status.ENVIADO: "#1a7f47",
    RegistroEnvio.Status.FALHOU: "#b42318",
    RegistroEnvio.Status.ENVIANDO: "#6b7280",
    EnvioAgendado.Status.AGENDADO: "#24578f",
    EnvioAgendado.Status.CANCELADO: "#6b7280",
}


class FormularioContaEmail(forms.ModelForm):
    """A senha nunca volta para a tela: o campo sai sempre vazio e só grava
    quando algo novo é digitado."""

    senha = forms.CharField(
        label="senha",
        widget=forms.PasswordInput(render_value=False),
        required=False,
        help_text="Deixe em branco para manter a senha atual.",
    )

    class Meta:
        model = ContaEmail
        fields = [
            "nome", "host", "porta", "usuario", "senha", "usar_tls", "usar_ssl",
            "timeout", "dominios_permitidos", "envelope_from", "ativa",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is None:
            self.fields["senha"].required = True
            self.fields["senha"].help_text = ""

    def save(self, commit=True):
        conta = super().save(commit=False)
        nova = self.cleaned_data.get("senha")
        if nova:
            conta.senha = nova  # o setter do modelo cifra
        if commit:
            conta.save()
        return conta


class AliasInline(admin.TabularInline):
    model = Alias
    extra = 0
    fields = ("slug", "endereco", "nome_exibicao", "ativo", "ordem")
    show_change_link = True


@admin.register(ContaEmail)
class ContaEmailAdmin(admin.ModelAdmin):
    form = FormularioContaEmail
    inlines = [AliasInline]
    list_display = ("nome", "usuario", "host", "porta", "cifra", "quantos_aliases", "ativa")
    list_filter = ("ativa", "host")
    search_fields = ("nome", "usuario", "host")

    @admin.display(description="cifra")
    def cifra(self, obj):
        return "SSL" if obj.usar_ssl else ("STARTTLS" if obj.usar_tls else "—")

    @admin.display(description="aliases")
    def quantos_aliases(self, obj):
        return obj.aliases.count()


@admin.register(Alias)
class AliasAdmin(admin.ModelAdmin):
    list_display = ("slug", "endereco", "nome_exibicao", "conta", "ativo", "ordem")
    list_filter = ("ativo", "conta")
    search_fields = ("slug", "endereco", "nome_exibicao")
    list_editable = ("ordem", "ativo")
    fieldsets = (
        (None, {"fields": ("conta", "slug", "endereco", "nome_exibicao", "reply_to")}),
        ("Assinatura", {
            "fields": ("assinatura_html",),
            "description": (
                "HTML anexado ao fim de toda mensagem deste alias. Não passa pelo "
                "sanitizador — use estilo inline, como manda o e-mail."
            ),
        }),
        ("Exibição", {"fields": ("ativo", "ordem")}),
    )


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


@admin.register(EnvioAgendado)
class EnvioAgendadoAdmin(admin.ModelAdmin):
    """Só leitura, inclusive para apagar.

    Editar o corpo aqui passaria por cima da prévia — e a promessa do
    agendamento é justamente que sai o que foi conferido. Cancelar tem uma porta
    só, `/agendados/`, porque é a que também apaga os anexos que ficariam
    órfãos (ver `agendamento.cancelar`).
    """

    list_display = ("enviar_em", "alias", "para_resumido", "assunto", "selo", "tentativas")
    list_filter = ("status", "alias", "enviar_em")
    search_fields = ("assunto", "erro")
    date_hierarchy = "enviar_em"
    readonly_fields = [f.name for f in EnvioAgendado._meta.fields]

    fieldsets = (
        (None, {"fields": ("status", "enviar_em", "tentativas", "ultima_tentativa_em", "erro")}),
        ("Envelope", {"fields": ("alias", "para", "cc", "cco", "assunto")}),
        ("Cabeçalhos", {"fields": ("in_reply_to", "referencias")}),
        ("Conteúdo", {"fields": ("corpo_html", "citacao_html", "token_anexos")}),
        ("Resultado", {"fields": ("criado_em", "registro")}),
    )

    @admin.display(description="para")
    def para_resumido(self, obj):
        texto = obj.destinatarios
        return texto if len(texto) <= 60 else texto[:57] + "…"

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
