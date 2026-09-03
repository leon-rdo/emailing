"""Formulários do app."""

from email.utils import formataddr, getaddresses, parseaddr

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django_otp import devices_for_user
from django_otp.forms import OTPAuthenticationForm


class FormularioLogin(OTPAuthenticationForm):
    """Login numa etapa só: usuário, senha e código no mesmo envio.

    O django-otp 1.7 passou a exigir que o dispositivo seja escolhido
    explicitamente: antes ele tentava todos com `match_token()`, o que
    registrava falha de verificação em dispositivos que nem estavam sendo
    usados e podia estrangular, por exemplo, os códigos de recuperação.

    Esse motivo não existe quando o usuário tem um dispositivo só — não há
    outro para estrangular. Então, se nada foi escolhido e existe exatamente um
    disponível, é ele. Com dois ou mais o comportamento padrão volta a valer e o
    seletor aparece, que é o certo: aí a escolha importa.
    """

    def _chosen_device(self, user):
        dispositivo = super()._chosen_device(user)
        if dispositivo is None:
            disponiveis = list(devices_for_user(user, for_verify=True))
            if len(disponiveis) == 1:
                dispositivo = disponiveis[0]
        return dispositivo


def dividir_enderecos(bruto: str) -> list[str]:
    """"Nome <a@b.com>, c@d.com" → ["Nome <a@b.com>", "c@d.com"].

    `getaddresses` já sabe separar por vírgula respeitando nomes com vírgula
    entre aspas — reimplementar isso com `.split(",")` quebraria nesse caso.
    Endereços sem `@` (lixo de vírgula sobrando, grupos como
    "undisclosed-recipients:;") viram `("", "")` e são descartados.
    """
    if not bruto or not bruto.strip():
        return []
    enderecos = []
    for nome, endereco in getaddresses([bruto]):
        if not endereco or "@" not in endereco:
            continue
        enderecos.append(formataddr((nome, endereco)) if nome else endereco)
    return enderecos


class ListaEnderecosField(forms.CharField):
    """Campo de texto único que vira lista de endereços validados."""

    def __init__(self, *, minimo_um=False, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("widget", forms.TextInput)
        super().__init__(**kwargs)
        self.minimo_um = minimo_um

    def clean(self, valor):
        bruto = super().clean(valor)
        enderecos = dividir_enderecos(bruto)
        if self.minimo_um and not enderecos:
            raise ValidationError("Informe pelo menos um endereço válido.")
        validar = EmailValidator()
        for item in enderecos:
            _, endereco = parseaddr(item)
            try:
                validar(endereco)
            except ValidationError:
                raise ValidationError(f"Endereço inválido: {item}") from None
        return enderecos


class EntradaMultiploArquivo(forms.ClearableFileInput):
    allow_multiple_selected = True


class CampoMultiploArquivo(forms.FileField):
    """Receita da documentação do Django: `FileField` não aceita `multiple`
    sozinho desde a 5.0 — é preciso um widget e um `clean()` próprios."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("widget", EntradaMultiploArquivo)
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        limpar_um = super().clean
        if isinstance(data, (list, tuple)):
            return [limpar_um(item, initial) for item in data]
        return limpar_um(data, initial)


class FormularioRedacao(forms.Form):
    alias = forms.ChoiceField(label="De")
    para = ListaEnderecosField(label="Para", minimo_um=True)
    cc = ListaEnderecosField(label="Cc")
    cco = ListaEnderecosField(label="Cco")
    assunto = forms.CharField(label="Assunto", max_length=200, required=False)
    corpo = forms.CharField(label="Mensagem", required=False, widget=forms.HiddenInput)
    novo_anexo = CampoMultiploArquivo(label="Anexar arquivo")

    # Passthrough entre prévia e envio — preenchidos por código, não digitados.
    rascunho = forms.CharField(required=False, widget=forms.HiddenInput)
    in_reply_to = forms.CharField(required=False, widget=forms.HiddenInput)
    referencias = forms.CharField(required=False, widget=forms.HiddenInput)
    citacao_html = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, aliases, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["alias"].choices = [(a.slug, str(a)) for a in aliases]

    def clean(self):
        limpos = super().clean()
        total = len(limpos.get("para") or []) + len(limpos.get("cc") or []) + len(
            limpos.get("cco") or []
        )
        if total > settings.MAX_DESTINATARIOS:
            raise ValidationError(
                f"{total} destinatários somados excede o limite de "
                f"{settings.MAX_DESTINATARIOS}. Confira se não colou a lista errada."
            )
        return limpos


class FormularioPrevia(FormularioRedacao):
    """A prévia é do conteúdo, não do envelope.

    Exigir destinatário para pré-visualizar deixava a prévia ao vivo morta
    justamente no começo — quem escreve um e-mail normalmente escreve o corpo
    antes de preencher o "Para", e até lá nada aparecia. O envio continua
    exigindo destinatário: quem valida ali é o `FormularioRedacao`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["para"].minimo_um = False
