"""Views do app."""

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator

from .aliases import alias_por_slug, carregar_aliases
from .anexos import ErroAnexo, criar_token, ler_anexos, listar_anexos, remover_anexo, salvar_anexo
from .forms import FormularioLogin, FormularioRedacao
from .models import RegistroEnvio
from .montagem import DadosRedacao, calcular_hash_previa, montar_email


@method_decorator(login_not_required, name="dispatch")
class Entrar(LoginView):
    """Login de página única: usuário, senha e código TOTP no mesmo formulário.

    O `OTPAuthenticationForm` do django-otp já faz a verificação do token com
    janela de drift e prevenção de replay (`TOTPDevice.last_t`) — é exatamente a
    roda que não vale a pena reinventar.
    """

    template_name = "mensagens/login.html"
    redirect_authenticated_user = True

    def get_form_class(self):
        return FormularioLogin if settings.OTP_OBRIGATORIO else AuthenticationForm


class Sair(LogoutView):
    pass


def redigir(request):
    """Redigir, anexar, pré-visualizar. O envio de verdade entra na Etapa 7.

    `montar_email()` é função pura, então a prévia mostra exatamente o HTML
    sanitizado e assinado que sairia — sem depender de rascunho guardado em
    lugar nenhum (ver `montagem.py` e `CLAUDE.md`). Os anexos são a única
    exceção que precisa mesmo de um estado guardado entre requisições: o
    arquivo em si não cabe de volta num campo oculto do formulário, então fica
    no disco, sob o token do campo `rascunho`, e sobrevive entre uma prévia e
    a próxima até o envio (ou até `limpar_rascunhos` expirá-lo).
    """
    aliases = carregar_aliases()
    anexos_lista = []

    if request.method == "POST":
        form = FormularioRedacao(request.POST, request.FILES, aliases=aliases)
        token = request.POST.get("rascunho", "").strip()

        # Anexos são processados em QUALQUER POST — prévia, remoção, ou (na
        # Etapa 7) envio — não existe uma rota de upload separada.
        novos = request.FILES.getlist("novo_anexo")
        if novos and not token:
            token = criar_token()
        for arquivo in novos:
            try:
                salvar_anexo(token, arquivo)
            except ErroAnexo as exc:
                form.add_error(None, str(exc))

        remover = request.POST.get("remover_anexo")
        if remover:
            remover_anexo(token, remover)

        if token:
            form.data = form.data.copy()
            form.data["rascunho"] = token
            anexos_lista = listar_anexos(token)
    else:
        inicial = {"alias": aliases[0].slug} if aliases else {}
        responder_a = request.GET.get("responder")
        if responder_a:
            original = get_object_or_404(RegistroEnvio, pk=responder_a)
            # Respondendo a algo que EU enviei: o destinatário da resposta é
            # quem recebeu a mensagem original, não o meu próprio remetente.
            inicial["para"] = original.para
            inicial["assunto"] = (
                original.assunto if original.assunto.lower().startswith("re:")
                else f"Re: {original.assunto}"
            )
            inicial["in_reply_to"] = original.message_id
            inicial["referencias"] = (original.referencias + " " + original.message_id).strip()
        form = FormularioRedacao(aliases=aliases, initial=inicial)

    previa = None
    if request.method == "POST" and form.is_valid():
        alias = alias_por_slug(form.cleaned_data["alias"])
        dados = DadosRedacao(
            para=form.cleaned_data["para"],
            cc=form.cleaned_data["cc"],
            cco=form.cleaned_data["cco"],
            assunto=form.cleaned_data["assunto"],
            corpo_html=form.cleaned_data["corpo"],
            citacao_html=form.cleaned_data["citacao_html"],
            in_reply_to=form.cleaned_data["in_reply_to"],
            referencias=form.cleaned_data["referencias"],
        )
        mensagem = montar_email(dados, alias, anexos=ler_anexos(token))
        html_final = mensagem.alternatives[0][0]
        previa = {
            "html": html_final,
            "texto": mensagem.body,
            "hash": calcular_hash_previa(html_final, [a.id for a in anexos_lista]),
        }

    return render(
        request, "mensagens/redigir.html",
        {"form": form, "previa": previa, "anexos": anexos_lista},
    )


def historico(request):
    lista = RegistroEnvio.objects.all()
    pagina = Paginator(lista, 25).get_page(request.GET.get("pagina"))
    return render(request, "mensagens/historico.html", {"pagina": pagina})


def registro(request, pk):
    item = get_object_or_404(RegistroEnvio, pk=pk)
    return render(request, "mensagens/registro.html", {"registro": item})
