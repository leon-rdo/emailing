"""Formulários do app."""

from datetime import datetime
from email.utils import formataddr, getaddresses, parseaddr

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django_otp import devices_for_user
from django_otp.forms import OTPAuthenticationForm

from .montagem import DadosRedacao

# O `datetime-local` do navegador manda "2026-09-10T09:00", que não está nos
# DATETIME_INPUT_FORMATS do locale pt-br. Os outros formatos existem para a
# linha de comando (`manage.py enviar --em`), onde quem digita é gente.
FORMATOS_ENVIAR_EM = [
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M",
]


def analisar_enviar_em(bruto: str) -> datetime:
    """Texto → datetime com fuso, pelos mesmos formatos que a tela aceita.

    Levanta `ValidationError`. Existe para o `manage.py enviar --em` não ter um
    segundo parser de data: dois parsers acabam divergindo justamente no
    formato que você usa menos.
    """
    return forms.DateTimeField(input_formats=FORMATOS_ENVIAR_EM).clean(bruto)


def dados_do_formulario(form) -> DadosRedacao:
    """`DadosRedacao` a partir de um formulário já validado.

    Compartilhado pela view e pelo `manage.py enviar`: as duas rotas montam a
    mensagem a partir do mesmo objeto, então não existe campo que uma preenche
    e a outra esquece.
    """
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
    """Campo de texto único que vira lista de endereços validados.

    Em modo `tolerante`, endereço inválido é descartado em silêncio em vez de
    invalidar o formulário — é o que a prévia ao vivo precisa: quem digita um
    e-mail passa por "cliente@exe" antes de chegar em "cliente@exemplo.com", e
    a prévia não pode congelar no meio do caminho.
    """

    def __init__(self, *, minimo_um=False, tolerante=False, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("widget", forms.TextInput)
        super().__init__(**kwargs)
        self.minimo_um = minimo_um
        self.tolerante = tolerante

    def clean(self, valor):
        bruto = super().clean(valor)
        enderecos = dividir_enderecos(bruto)
        validar = EmailValidator()
        validos = []
        for item in enderecos:
            _, endereco = parseaddr(item)
            try:
                validar(endereco)
            except ValidationError:
                if self.tolerante:
                    continue
                raise ValidationError(f"Endereço inválido: {item}") from None
            validos.append(item)

        if self.minimo_um and not validos and not self.tolerante:
            raise ValidationError("Informe pelo menos um endereço válido.")
        return validos


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

    # Opcional mesmo no envio: o botão "Enviar" ignora e o "Agendar" exige. A
    # checagem de "já passou" fica na view, que é quem sabe qual botão foi
    # clicado — no campo, ela recusaria o formulário de um envio imediato só
    # porque sobrou uma data velha na tela.
    enviar_em = forms.DateTimeField(
        label="Enviar em", required=False, input_formats=FORMATOS_ENVIAR_EM,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
    )

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


class FormularioRascunho(FormularioRedacao):
    """Guardar não é enviar: nada precisa estar completo.

    Só o "Para" deixa de ser obrigatório — é a última coisa que se decide, pelo
    mesmo motivo de sempre. Endereço **inválido** continua sendo erro, ao
    contrário da prévia: descartá-lo em silêncio faria o rascunho voltar
    diferente do que foi salvo, e aqui não vem tecla nenhuma atrás para corrigir.

    O `getaddresses` do Python já descarta sozinho texto em que não reconhece
    endereço nenhum (`joao`, `isto-nao-e-email`), antes de o validador ver. Na
    tela de envio isso aparece como "informe um endereço"; aqui, sem
    obrigatoriedade, o campo simplesmente voltaria vazio. Por isso cada campo de
    endereço recusa o que foi digitado e não deixou nada.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["para"].minimo_um = False

    def _sem_perda(self, campo: str) -> list[str]:
        validos = self.cleaned_data.get(campo) or []
        digitado = (self.data.get(campo) or "").strip()
        if digitado and not validos:
            raise ValidationError(f"Endereço inválido: {digitado}")
        return validos

    def clean_para(self):
        return self._sem_perda("para")

    def clean_cc(self):
        return self._sem_perda("cc")

    def clean_cco(self):
        return self._sem_perda("cco")


class FormularioPrevia(FormularioRedacao):
    """A prévia é do conteúdo, não do envelope.

    Nada relacionado a destinatário pode invalidar uma prévia. Exigir "Para"
    deixava a prévia morta enquanto se escrevia o corpo (a ordem natural); e
    validar endereço a cada tecla a congelava no meio de cada digitação, já que
    todo e-mail passa por estados inválidos até terminar de ser escrito. Nos
    dois casos o sintoma era o mesmo: a prévia parecia só funcionar no botão.

    O envio continua estrito — lá quem valida é o `FormularioRedacao`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ("para", "cc", "cco"):
            self.fields[campo].minimo_um = False
            self.fields[campo].tolerante = True
        # Mesmo motivo, aplicado à data: "10/09/2026 0" é um estado pelo qual
        # toda digitação de data passa, e um erro de campo aqui devolveria
        # `ok:false` e congelaria a prévia. A data não é conteúdo — não entra no
        # HTML nem no hash — então a prévia simplesmente não a conhece.
        del self.fields["enviar_em"]
