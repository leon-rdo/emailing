"""Views do app."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.files.uploadhandler import MemoryFileUploadHandler
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, csrf_protect

from .aliases import alias_por_slug, carregar_aliases
from .anexos import ErroAnexo, criar_token, listar_anexos, remover_anexo, salvar_anexo
from .eml import ErroImportacaoEML, analisar_eml, normalizar_message_id, referencias_para_resposta
from .envio import enviar_email
from .forms import FormularioLogin, FormularioPrevia, FormularioRedacao
from .models import RegistroEnvio
from .montagem import DadosRedacao, calcular_hash_previa, montar_email


def _dados_do_formulario(form) -> DadosRedacao:
    return DadosRedacao(
        para=form.cleaned_data["para"],
        cc=form.cleaned_data["cc"],
        cco=form.cleaned_data["cco"],
        assunto=form.cleaned_data["assunto"],
        corpo_html=form.cleaned_data["corpo"],
        citacao_html=form.cleaned_data["citacao_html"],
        in_reply_to=form.cleaned_data["in_reply_to"],
        referencias=form.cleaned_data["referencias"],
    )


def _previa_de(form, token: str) -> dict:
    """Prévia a partir de um formulário já validado — usada tanto pelo POST
    completo quanto pelo endpoint de prévia ao vivo, para as duas rotas nunca
    divergirem sobre o que seria enviado.

    Não lê o conteúdo dos anexos: o corpo HTML não depende deles (viram parte
    MIME separada, nunca aparecem no HTML), só os ids entram no hash. Ler
    bytes de anexo a cada pausa de digitação seria caro à toa.
    """
    alias = alias_por_slug(form.cleaned_data["alias"])
    dados = _dados_do_formulario(form)
    ids_anexos = [a.id for a in listar_anexos(token)]
    mensagem = montar_email(dados, alias)
    html_final = mensagem.alternatives[0][0]
    return {
        "dados": dados,
        "alias": alias,
        "html": html_final,
        "texto": mensagem.body,
        "hash": calcular_hash_previa(dados, alias, html_final, ids_anexos),
    }


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
    """Redigir, anexar, pré-visualizar e enviar.

    `montar_email()` é função pura, então a prévia mostra exatamente o HTML
    sanitizado e assinado que sairia — sem depender de rascunho guardado em
    lugar nenhum (ver `montagem.py` e `CLAUDE.md`). Os anexos são a única
    exceção que precisa mesmo de um estado guardado entre requisições: o
    arquivo em si não cabe de volta num campo oculto do formulário, então fica
    no disco, sob o token do campo `rascunho`, e sobrevive entre uma prévia e
    a próxima até o envio (ou até `limpar_rascunhos` expirá-lo).

    O envio só acontece quando `hash_previa` (calculado sobre o mesmo HTML
    final + os mesmos anexos) bate com o que a última prévia mostrou — editar
    o corpo ou trocar um anexo depois de pré-visualizar e clicar Enviar volta
    para uma prévia atualizada, em vez de mandar algo que não foi conferido.
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

        importado = request.session.pop("rascunho_importado", None)
        if importado:
            inicial.update({k: v for k, v in importado.items() if v})

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
            referencias_originais = original.referencias.split() if original.referencias else []
            inicial["referencias"] = referencias_para_resposta(
                referencias_originais, original.message_id
            )
        form = FormularioRedacao(aliases=aliases, initial=inicial)

    previa = None
    if request.method == "POST" and form.is_valid():
        acao = request.POST.get("acao")
        resultado = _previa_de(form, token)

        if acao == "enviar" and request.POST.get("hash_previa") == resultado["hash"]:
            registro = enviar_email(resultado["alias"], resultado["dados"], token_anexos=token)
            if registro.status == RegistroEnvio.Status.ENVIADO:
                messages.success(request, "E-mail enviado.")
            else:
                messages.error(request, f"Falha ao enviar: {registro.erro}")
            return redirect("mensagens:registro", pk=registro.pk)

        if acao == "enviar":
            messages.warning(
                request,
                "O conteúdo mudou desde a última prévia. Confira a prévia atualizada "
                "antes de enviar.",
            )

        previa = resultado

    return render(
        request, "mensagens/redigir.html",
        {"form": form, "previa": previa, "anexos": anexos_lista},
    )


def previa_ajax(request):
    """Mesmo cálculo de `redigir()`, só que devolvendo JSON em vez de HTML —
    o que a prévia ao vivo do template chama a cada pausa de digitação. Nunca
    envia nada nem toca em anexos; só reflete o que `_previa_de` calcularia.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "erros": ["método inválido"]}, status=405)

    form = FormularioPrevia(request.POST, aliases=carregar_aliases())
    if not form.is_valid():
        erros = list(form.non_field_errors()) + [
            str(erro)
            for campo, lista in form.errors.items()
            if campo != "__all__"
            for erro in lista
        ]
        return JsonResponse({"ok": False, "erros": erros})

    token = request.POST.get("rascunho", "").strip()
    resultado = _previa_de(form, token)
    return JsonResponse({
        "ok": True,
        "html": resultado["html"],
        "texto": resultado["texto"],
        "hash": resultado["hash"],
    })


@csrf_exempt
def importar_eml(request):
    """Extrai `.eml`/`.txt` para pré-preencher uma resposta, ou aceita um
    `Message-ID` digitado à mão quando não há arquivo nenhum à mão.

    A troca de upload handler precisa acontecer aqui, na view externa, antes
    de qualquer leitura de `request.POST` — inclusive a que o próprio
    `@csrf_protect` da view interna faz para achar o token do CSRF. Depois
    desse ponto não tem mais como forçar o arquivo a ficar só em memória
    (mesmo padrão do `gloryrics`, que existe pelo mesmo motivo: a
    correspondência importada aqui é de terceiros e nunca deveria tocar
    disco).
    """
    request.upload_handlers = [MemoryFileUploadHandler(request)]
    if request.method == "POST":
        tamanho = int(request.META.get("CONTENT_LENGTH") or 0)
        if tamanho > settings.EML_MAX_BYTES:
            messages.error(request, "Arquivo grande demais para importar.")
            return redirect("mensagens:inicio")
    return _importar_eml(request)


@csrf_protect
def _importar_eml(request):
    if request.method != "POST":
        return redirect("mensagens:inicio")

    arquivo = request.FILES.get("arquivo")
    message_id_manual = request.POST.get("message_id_manual", "").strip()

    if arquivo:
        if arquivo.size > settings.EML_MAX_BYTES:
            messages.error(request, f"{arquivo.name} passa do limite de importação.")
            return redirect("mensagens:inicio")
        try:
            resultado = analisar_eml(arquivo.read())
        except ErroImportacaoEML as exc:
            messages.error(request, str(exc))
            return redirect("mensagens:inicio")

        for aviso in resultado.avisos:
            messages.warning(request, aviso)
        request.session["rascunho_importado"] = {
            "para": resultado.para,
            "assunto": resultado.assunto,
            "in_reply_to": resultado.message_id,
            "referencias": resultado.referencias,
            "citacao_html": resultado.citacao_html,
        }
        return redirect("mensagens:inicio")

    if message_id_manual:
        normalizado = normalizar_message_id(message_id_manual)
        request.session["rascunho_importado"] = {
            "in_reply_to": normalizado,
            "referencias": normalizado,
        }
        return redirect("mensagens:inicio")

    messages.error(request, "Envie um arquivo .eml/.txt ou informe um Message-ID.")
    return redirect("mensagens:inicio")


def historico(request):
    lista = RegistroEnvio.objects.all()
    pagina = Paginator(lista, 25).get_page(request.GET.get("pagina"))
    return render(request, "mensagens/historico.html", {"pagina": pagina})


def registro(request, pk):
    item = get_object_or_404(RegistroEnvio, pk=pk)
    return render(request, "mensagens/registro.html", {"registro": item})
