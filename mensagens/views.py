"""Views do app."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.files.uploadhandler import MemoryFileUploadHandler
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST

from .agendamento import (
    agendar,
    cancelar,
    dados_de,
    descartar_rascunho,
    guardar_rascunho,
    reescrever,
)
from .aliases import alias_por_slug, carregar_aliases
from .anexos import (
    ErroAnexo,
    copiar_rascunho,
    criar_token,
    listar_anexos,
    remover_anexo,
    resumo_dos_anexos,
    salvar_anexo,
)
from .eml import ErroImportacaoEML, analisar_eml, normalizar_message_id, referencias_para_resposta
from .envio import enviar_email
from .forms import (
    FormularioLogin,
    FormularioPrevia,
    FormularioRascunho,
    FormularioRedacao,
    dados_do_formulario,
)
from .marcadores import GLOSSARIO
from .models import EnvioAgendado, RegistroEnvio
from .montagem import (
    calcular_hash_previa,
    emoldurar_para_previa,
    montar_corpo,
    montar_email,
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
    dados = dados_do_formulario(form)
    ids_anexos = [a.id for a in listar_anexos(token)]
    mensagem = montar_email(dados, alias)
    html_final = mensagem.alternatives[0][0]
    # O hash é do conteúdo AUTORAL, com os marcadores ainda intactos: sobre o
    # expandido, `{{ hora }}` mudaria sozinho entre a prévia e o clique em
    # Enviar e o envio seria recusado por "o conteúdo mudou".
    html_autoral, _ = montar_corpo(dados, alias)
    return {
        "dados": dados,
        "alias": alias,
        "html": html_final,
        # O que vai para o iframe leva a moldura; o que é enviado (e o que
        # entra no hash) é o html_final puro.
        "html_previa": emoldurar_para_previa(html_final),
        "texto": mensagem.body,
        "hash": calcular_hash_previa(dados, alias, html_autoral, ids_anexos),
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


def _formulario_da_linha(linha: EnvioAgendado, token: str) -> dict:
    """Os campos da tela para uma mensagem guardada, como texto de formulário.

    Serve às duas pontas da abertura: é o `initial` do formulário que o operador
    vai editar e é também o `data` do formulário-sonda que calcula a prévia
    inicial (ver `_previa_inicial`).
    """
    return {
        "alias": linha.alias.slug,
        "para": ", ".join(linha.para),
        "cc": ", ".join(linha.cc),
        "cco": ", ".join(linha.cco),
        "assunto": linha.assunto,
        "corpo": linha.corpo_html,
        "citacao_html": linha.citacao_html,
        "in_reply_to": linha.in_reply_to,
        "referencias": linha.referencias,
        "rascunho": token,
        "enviar_em": (
            timezone.localtime(linha.enviar_em).strftime("%Y-%m-%dT%H:%M")
            if linha.enviar_em else ""
        ),
    }


def _previa_inicial(dados_formulario: dict, token: str, aliases):
    """Prévia da mensagem recém-aberta para edição, ou `None` se ela não valida.

    Sem isto, abrir um agendamento para corrigir uma vírgula deixaria "Salvar
    alterações" escondido até o operador provocar uma prévia. A sonda é só um
    formulário comum sobre os dados guardados: se o rascunho estiver incompleto
    ela falha em silêncio e a tela abre sem prévia, como uma redação nova.
    """
    sonda = FormularioRedacao(dados_formulario, aliases=aliases)
    return _previa_de(sonda, token) if sonda.is_valid() else None


def redigir(request, pk=None):
    """Redigir, anexar, pré-visualizar, enviar, agendar e guardar rascunho.

    Com `pk`, é a mesma tela aberta sobre uma mensagem guardada (rascunho ou
    ainda na fila): editar e redigir são o mesmo gesto, então não há um segundo
    formulário para divergir do primeiro.

    `montar_email()` é função pura, então a prévia mostra exatamente o HTML
    sanitizado e assinado que sairia — sem depender de rascunho guardado em
    lugar nenhum (ver `montagem.py` e `CLAUDE.md`). Um rascunho **salvo** não
    contradiz isso: é uma escolha explícita do operador e nunca serve para
    calcular a prévia, que continua sendo recalculada sobre o mesmo POST. Os
    anexos são a única exceção que precisa mesmo de um estado guardado entre
    requisições: o arquivo em si não cabe de volta num campo oculto do
    formulário, então fica no disco, sob o token do campo `rascunho`, e
    sobrevive entre uma prévia e a próxima até o envio (ou até
    `limpar_rascunhos` expirá-lo).

    Ao editar, esse token é de uma **cópia** dos anexos da mensagem, nunca da
    pasta dela (ver `anexos.copiar_rascunho`): abandonar a tela não muda nada, e
    o despacho nunca enxerga uma edição pela metade.

    O envio só acontece quando `hash_previa` (calculado sobre o mesmo HTML
    final + os mesmos anexos) bate com o que a última prévia mostrou — editar
    o corpo ou trocar um anexo depois de pré-visualizar e clicar Enviar volta
    para uma prévia atualizada, em vez de mandar algo que não foi conferido.
    Guardar um rascunho é a única ação que dispensa a trava: nada sai.
    """
    aliases = carregar_aliases()
    anexos_lista = []
    previa = None
    linha = None

    if pk is not None:
        linha = get_object_or_404(
            EnvioAgendado.objects.select_related("alias__conta"), pk=pk
        )
        if not linha.editavel:
            messages.warning(
                request,
                f"A mensagem #{pk} está “{linha.get_status_display().lower()}” e já não "
                "pode ser editada.",
            )
            return redirect("mensagens:agendado", pk=pk)

    if request.method == "POST":
        acao = request.POST.get("acao")
        classe = FormularioRascunho if acao == "salvar_rascunho" else FormularioRedacao
        form = classe(request.POST, request.FILES, aliases=aliases)
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
    elif linha is not None:
        token = copiar_rascunho(linha.token_anexos)
        campos = _formulario_da_linha(linha, token)
        form = FormularioRedacao(aliases=aliases, initial=campos)
        anexos_lista = listar_anexos(token)
        previa = _previa_inicial(campos, token, aliases)
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

    if request.method == "POST" and form.is_valid():
        resultado = _previa_de(form, token)
        # A mesma trava vale para agendar e para salvar alterações: o que vai
        # para a fila é o que foi conferido. Um agendamento é mais perigoso
        # nesse aspecto, não menos — ninguém vai reler a mensagem no momento em
        # que ela sai.
        conferido = request.POST.get("hash_previa") == resultado["hash"]
        destino = _executar(request, acao, form, resultado, token, conferido, linha)
        if destino is not None:
            return destino
        previa = resultado

    fundo, fundo_itens = _fundo_do_modal(linha)
    return render(
        request, "mensagens/redigir.html",
        {
            "form": form,
            "previa": previa,
            "anexos": anexos_lista,
            "marcadores": GLOSSARIO,
            "linha": linha,
            "fundo": fundo,
            "fundo_itens": fundo_itens,
            "menu_ativo": fundo,
        },
    )


def _fundo_do_modal(linha):
    """A lista que fica atrás do modal de escrita: de onde a pessoa veio.

    Só cenário (a tela marca `inert`), mas é a lista de verdade — o modal abre
    sobre o contexto, não sobre um vazio. Poucas linhas bastam: o que passa da
    borda do modal não aparece.
    """
    Status = EnvioAgendado.Status
    if linha is None:
        return "enviados", RegistroEnvio.objects.all()[:14]
    base = EnvioAgendado.objects.select_related("alias")
    if linha.status == Status.RASCUNHO:
        return "rascunhos", base.filter(status=Status.RASCUNHO).order_by("-atualizado_em")[:14]
    return "agendados", base.filter(status=Status.AGENDADO)[:14]


def _executar(request, acao, form, resultado, token, conferido, linha):
    """Faz o que o botão clicado pede e devolve o redirect, ou `None` para
    ficar na tela (prévia, aviso de conteúdo mudado, erro de data).

    Quem está na fila (`linha` agendada) só salva alterações ou volta a
    rascunho: "Enviar" e "Agendar" não se aplicam a quem já está agendado, e um
    POST forjado pedindo isso é ignorado em vez de enviar por fora da fila.
    """
    if acao == "salvar_rascunho":
        return _salvar_rascunho(request, form, resultado, token, linha)

    if acao in ("enviar", "agendar", "salvar") and not conferido:
        messages.warning(
            request,
            "O conteúdo mudou desde a última prévia. Confira a prévia atualizada "
            "antes de enviar.",
        )
        return None

    na_fila = linha is not None and linha.status == EnvioAgendado.Status.AGENDADO
    if na_fila:
        if acao == "salvar":
            return _salvar_alteracoes(request, form, resultado, token, linha)
        return None
    if acao == "enviar":
        return _enviar(request, resultado, token, linha)
    if acao == "agendar":
        return _agendar(request, form, resultado, token, linha)
    return None


def _enviar(request, resultado, token, linha):
    registro = enviar_email(resultado["alias"], resultado["dados"], token_anexos=token)
    if registro.status == RegistroEnvio.Status.ENVIADO:
        if linha is not None:
            # Saiu: o rascunho cumpriu o papel dele. O rastro é o RegistroEnvio.
            descartar_rascunho(linha.pk)
        messages.success(request, "E-mail enviado.")
    else:
        messages.error(request, f"Falha ao enviar: {registro.erro}")
    return redirect("mensagens:registro", pk=registro.pk)


def _data_futura(request, form):
    """A data do formulário, se der para agendar nela; senão `None` e o aviso.

    A checagem de "já passou" mora aqui e não no campo do formulário: no campo,
    ela recusaria também um envio imediato só porque sobrou uma data velha na
    tela — e o campo é o mesmo para todos os botões.
    """
    quando = form.cleaned_data.get("enviar_em")
    if not quando:
        messages.error(request, "Para agendar, informe a data e a hora do envio.")
        return None
    if quando <= timezone.now():
        messages.error(request, "Essa data já passou. Escolha um momento no futuro.")
        return None
    return quando


def _perdeu_a_corrida(request, pk):
    messages.warning(
        request,
        f"A mensagem #{pk} já não estava esperando — pode ter sido despachada ou "
        "cancelada antes deste clique. O que você editou não foi salvo.",
    )
    return redirect("mensagens:agendado", pk=pk)


def _agendar(request, form, resultado, token, linha):
    """Põe a mensagem na fila, ou devolve `None` deixando o erro na tela.

    Não chama `limpar_rascunho`: os anexos têm que continuar em disco até o
    despacho. Quem garante que a limpeza diária não os leve é
    `agendamento.tokens_pendentes()`.
    """
    quando = _data_futura(request, form)
    if quando is None:
        return None

    if linha is None:
        agendar(resultado["alias"], resultado["dados"], quando, token_anexos=token)
    elif not reescrever(
        linha.pk, resultado["alias"], resultado["dados"],
        de=(EnvioAgendado.Status.RASCUNHO,), para=EnvioAgendado.Status.AGENDADO,
        enviar_em=quando, token_anexos=token,
    ):
        return _perdeu_a_corrida(request, linha.pk)

    local = timezone.localtime(quando).strftime("%d/%m/%Y às %H:%M")
    messages.success(request, f"Agendado para {local}.")
    return redirect("mensagens:agendados")


def _salvar_alteracoes(request, form, resultado, token, linha):
    """Grava a edição de um agendamento que ainda não saiu."""
    quando = _data_futura(request, form)
    if quando is None:
        return None
    if not reescrever(
        linha.pk, resultado["alias"], resultado["dados"],
        de=(EnvioAgendado.Status.AGENDADO,), para=EnvioAgendado.Status.AGENDADO,
        enviar_em=quando, token_anexos=token,
    ):
        return _perdeu_a_corrida(request, linha.pk)

    local = timezone.localtime(quando).strftime("%d/%m/%Y às %H:%M")
    messages.success(request, f"Alterações salvas. Sai em {local}.")
    return redirect("mensagens:agendados")


def _salvar_rascunho(request, form, resultado, token, linha):
    """Guarda como rascunho: sem trava de prévia, sem exigir destinatário e sem
    julgar a data — nada sai daqui, então nada disso protegeria de coisa alguma.

    Vale também para quem está na fila: tira-o de lá sem cancelar, mantendo o
    conteúdo (cancelar é definitivo, e a mensagem ficaria só para consulta).
    """
    quando = form.cleaned_data.get("enviar_em")
    if linha is None:
        linha = guardar_rascunho(
            resultado["alias"], resultado["dados"], quando, token_anexos=token
        )
        messages.success(request, "Rascunho salvo.")
    else:
        estava_na_fila = linha.status == EnvioAgendado.Status.AGENDADO
        if not reescrever(
            linha.pk, resultado["alias"], resultado["dados"],
            de=(EnvioAgendado.Status.RASCUNHO, EnvioAgendado.Status.AGENDADO),
            para=EnvioAgendado.Status.RASCUNHO, enviar_em=quando, token_anexos=token,
        ):
            return _perdeu_a_corrida(request, linha.pk)
        messages.success(
            request,
            "Tirado da fila e salvo como rascunho." if estava_na_fila else "Rascunho salvo.",
        )
    return redirect("mensagens:editar", pk=linha.pk)


def agendados(request):
    """A fila: o que ainda vai sair, e o que já saiu ou falhou.

    Os pendentes vêm inteiros (a fila de um usuário só não cresce sem limite) e
    o resto é uma cauda curta, para achar o que falhou de madrugada. Rascunho
    não é nem uma coisa nem outra — tem página própria.
    """
    Status = EnvioAgendado.Status
    pendentes = EnvioAgendado.objects.filter(status=Status.AGENDADO).select_related("alias")
    encerrados = (
        EnvioAgendado.objects.exclude(status__in=(Status.AGENDADO, Status.RASCUNHO))
        .select_related("alias")
        .order_by("-enviar_em")[:25]
    )
    return render(
        request, "mensagens/agendados.html",
        {
            "pendentes": pendentes,
            "encerrados": encerrados,
            "total_rascunhos": EnvioAgendado.objects.filter(status=Status.RASCUNHO).count(),
        },
    )


def agendado(request, pk):
    """Tudo sobre uma mensagem guardada, esteja ela em que estado estiver —
    inclusive cancelada, que é o caso em que não há mais nada a editar mas
    ainda há o que consultar.

    O corpo mostrado é o **autoral**: sanitizado e com a assinatura, mas com os
    marcadores como foram escritos. É o que está guardado; o valor deles só
    existe no instante do despacho (e, para o que já saiu, em `RegistroEnvio`).
    """
    item = get_object_or_404(
        EnvioAgendado.objects.select_related("alias__conta", "registro"), pk=pk
    )
    html_autoral, _ = montar_corpo(dados_de(item), item.alias)
    em_disco = resumo_dos_anexos(item.token_anexos)
    return render(
        request, "mensagens/agendado.html",
        {
            "item": item,
            "html_previa": emoldurar_para_previa(html_autoral),
            # Os arquivos somem ao cancelar e ao expirar; a foto da última
            # gravação continua dizendo quais eram.
            "anexos": em_disco or item.anexos,
            "anexos_sem_arquivo": bool(item.anexos) and not em_disco,
        },
    )


@require_POST
def cancelar_agendado(request, pk):
    if cancelar(pk):
        messages.success(request, f"Agendamento #{pk} cancelado.")
    else:
        messages.warning(
            request,
            f"O agendamento #{pk} já não estava esperando — pode ter sido despachado "
            "ou cancelado antes deste clique.",
        )
    return redirect("mensagens:agendados")


def rascunhos(request):
    lista = (
        EnvioAgendado.objects.filter(status=EnvioAgendado.Status.RASCUNHO)
        .select_related("alias")
        .order_by("-atualizado_em")
    )
    return render(request, "mensagens/rascunhos.html", {"rascunhos": lista})


@require_POST
def descartar(request, pk):
    if descartar_rascunho(pk):
        messages.success(request, "Rascunho descartado.")
    else:
        messages.warning(request, f"A mensagem #{pk} não é (ou já não é) um rascunho.")
    return redirect("mensagens:rascunhos")


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
        "html": resultado["html_previa"],
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
    q = request.GET.get("q", "").strip()[:100]
    if q:
        lista = lista.filter(
            Q(assunto__icontains=q) | Q(para__icontains=q)
            | Q(cc__icontains=q) | Q(alias__icontains=q)
        )
    pagina = Paginator(lista, 25).get_page(request.GET.get("pagina"))
    return render(request, "mensagens/historico.html", {"pagina": pagina, "q": q})


def registro(request, pk):
    item = get_object_or_404(RegistroEnvio, pk=pk)
    # A mesma moldura da prévia: sem ela o iframe cairia na fonte serifada do
    # navegador, que nenhum cliente de e-mail usa.
    return render(
        request, "mensagens/registro.html",
        {"registro": item, "corpo_previa": emoldurar_para_previa(item.corpo_html)},
    )
