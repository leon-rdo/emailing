"""Configurações: contas SMTP, aliases e assinaturas.

Substituem o uso cotidiano do `/admin/` (que continua existindo). Nada aqui
apaga: para parar de usar uma conta ou um alias, desativa-se — o histórico e os
agendamentos apontam para eles, e um alias apagado deixaria o histórico sem
saber de que endereço saiu cada mensagem.
"""

from __future__ import annotations

import smtplib
import ssl

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import FormularioAlias, FormularioConta
from .models import Alias, ContaEmail
from .montagem import DadosRedacao, emoldurar_para_previa, montar_corpo

_AMOSTRA = (
    "<p>Olá, tudo bem?</p>"
    "<p>Este é um texto de exemplo para você ver a assinatura no fim de uma mensagem.</p>"
)


def indice(request):
    return redirect("mensagens:config_contas")


# ---------------------------------------------------------------- contas


def contas(request):
    lista = ContaEmail.objects.annotate(total_aliases=Count("aliases")).order_by("nome")
    return render(request, "mensagens/config_contas.html", {"contas": lista})


def conta_form(request, pk=None):
    conta = get_object_or_404(ContaEmail, pk=pk) if pk is not None else None
    form = FormularioConta(request.POST or None, instance=conta)
    if request.method == "POST" and form.is_valid():
        salva = form.save()
        messages.success(request, f"Conta “{salva.nome}” salva.")
        return redirect("mensagens:config_contas")
    return render(request, "mensagens/config_conta_form.html", {"form": form, "conta": conta})


def _explicar(exc: Exception, host: str, porta: int) -> str:
    """O erro do SMTP em português, dizendo o que fazer."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "O servidor recusou o usuário ou a senha."
    if isinstance(exc, ssl.SSLError):
        return (
            "A conexão segura falhou. Confira a cifra: 465 costuma ser SSL/TLS direto "
            "e 587, STARTTLS."
        )
    if isinstance(exc, TimeoutError):
        return f"{host}:{porta} não respondeu a tempo. Confira o servidor e a porta."
    if isinstance(exc, OSError):
        return f"Não foi possível conectar a {host}:{porta} ({exc.strerror or exc})."
    if isinstance(exc, smtplib.SMTPException):
        return f"O servidor respondeu com erro: {exc}"
    return f"Falha inesperada: {exc}"


@require_POST
def testar_conta(request):
    """Abre a conexão e autentica, **sem enviar nada**.

    Serve para conferir os dados da conta antes de salvá-la. Senha em branco
    usa a que já está guardada (quando se está editando uma conta existente).
    """
    host = request.POST.get("host", "").strip()
    usuario = request.POST.get("usuario", "").strip()
    senha = request.POST.get("senha", "")
    try:
        porta = int(request.POST.get("porta", ""))
        timeout = min(max(int(request.POST.get("timeout") or 20), 3), 30)
    except ValueError:
        return JsonResponse({"ok": False, "erro": "Porta e timeout precisam ser números."})
    ssl_direto = request.POST.get("cifra") == "ssl"

    if not senha and request.POST.get("pk", "").isdigit():
        guardada = ContaEmail.objects.filter(pk=request.POST["pk"]).first()
        senha = guardada.senha if guardada else ""
    if not (host and usuario and senha):
        return JsonResponse({"ok": False, "erro": "Preencha servidor, conta e senha para testar."})

    classe = smtplib.SMTP_SSL if ssl_direto else smtplib.SMTP
    try:
        with classe(host, porta, timeout=timeout) as servidor:
            if not ssl_direto:
                servidor.starttls()
            servidor.login(usuario, senha)
    except Exception as exc:  # o que importa é a explicação, não o tipo
        return JsonResponse({"ok": False, "erro": _explicar(exc, host, porta)})
    return JsonResponse({"ok": True})


# --------------------------------------------------------------- aliases


def aliases(request):
    lista = ContaEmail.objects.prefetch_related("aliases").order_by("nome")
    return render(request, "mensagens/config_aliases.html", {"contas": lista})


def alias_form(request, pk=None):
    alias = get_object_or_404(Alias, pk=pk) if pk is not None else None
    inicial = {}
    if alias is None and request.GET.get("conta", "").isdigit():
        inicial["conta"] = request.GET["conta"]
    form = FormularioAlias(request.POST or None, instance=alias, initial=inicial)
    if request.method == "POST" and form.is_valid():
        salvo = form.save()
        messages.success(request, f"Alias {salvo.endereco} salvo.")
        return redirect("mensagens:config_aliases")
    hosts = [h.replace("https://", "") for h in settings.HOSTS_IMAGENS_ASSINATURA.split()]
    return render(
        request, "mensagens/config_alias_form.html",
        {"form": form, "alias": alias, "hosts_imagens": hosts},
    )


@require_POST
def assinatura_previa(request):
    """A assinatura como ficaria no fim de uma mensagem, pela mesma montagem do
    envio e na mesma moldura da prévia. O HTML vai para um iframe `sandbox`:
    nada do que se digita aqui executa."""
    html, _ = montar_corpo(
        DadosRedacao(para=[], corpo_html=_AMOSTRA),
        Alias(assinatura_html=request.POST.get("assinatura_html", "")[:60000]),
    )
    return JsonResponse({"ok": True, "html": emoldurar_para_previa(html)})
