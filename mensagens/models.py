"""Contas de e-mail, aliases e o log de envios.

`ContaEmail` é uma caixa real que autentica no servidor de saída; `Alias` é um
endereço pelo qual se envia usando aquela conta. A separação existe porque uma
conta costuma servir vários aliases (é o motivo do projeto existir), e porque
contas diferentes moram em servidores diferentes — Titan, Hostinger, o que
for.

Nomes de domínio em português; `message_id`/`in_reply_to` em inglês porque são
nomes de cabeçalho da RFC 5322, não vocabulário do domínio.
"""

from email.utils import formataddr

from django.core.exceptions import ValidationError
from django.db import models

from .cripto import cifrar, decifrar


class ContaEmail(models.Model):
    """Uma caixa real que autentica no SMTP.

    A senha é guardada cifrada (ver `cripto.py`): o admin nunca a exibe, só
    aceita uma nova.
    """

    nome = models.CharField(
        "nome", max_length=100, unique=True,
        help_text='Só para você reconhecer, ex.: "Titan — leonardocosta.dev".',
    )
    host = models.CharField("servidor SMTP", max_length=255)
    porta = models.PositiveIntegerField("porta", default=587)
    usuario = models.CharField(
        "conta que autentica", max_length=320,
        help_text="A caixa real, não o alias. Ex.: me@leonardocosta.dev",
    )
    senha_cifrada = models.TextField("senha", blank=True)
    usar_tls = models.BooleanField("STARTTLS (porta 587)", default=True)
    usar_ssl = models.BooleanField("SSL/TLS direto (porta 465)", default=False)
    timeout = models.PositiveIntegerField("timeout (s)", default=20)

    dominios_permitidos = models.CharField(
        "domínios permitidos", max_length=500, blank=True,
        help_text=(
            "Separados por vírgula. Vazio = só o domínio da conta que autentica. "
            "Enviar com From: fora daqui quebra o alinhamento do DMARC e a "
            "mensagem cai em spam."
        ),
    )
    envelope_from = models.EmailField(
        "envelope fixo", blank=True,
        help_text=(
            "Deixe vazio (o normal): o envelope vira o próprio alias. Só preencha "
            "se este provedor recusar envelope de alias."
        ),
    )
    ativa = models.BooleanField("ativa", default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "conta de e-mail"
        verbose_name_plural = "contas de e-mail"

    def __str__(self):
        return f"{self.nome} ({self.usuario})"

    @property
    def senha(self) -> str:
        return decifrar(self.senha_cifrada)

    @senha.setter
    def senha(self, valor: str) -> None:
        self.senha_cifrada = cifrar(valor)

    @property
    def dominios(self) -> list[str]:
        if self.dominios_permitidos.strip():
            return [d.strip().lower() for d in self.dominios_permitidos.split(",") if d.strip()]
        return [self.usuario.rpartition("@")[2].lower()] if "@" in self.usuario else []

    def clean(self):
        if self.usar_tls and self.usar_ssl:
            raise ValidationError(
                {"usar_ssl": "STARTTLS e SSL direto são mutuamente exclusivos."}
            )
        if not self.usar_tls and not self.usar_ssl:
            raise ValidationError(
                {"usar_tls": "Escolha STARTTLS (587) ou SSL direto (465) — sem cifra, não."}
            )


class Alias(models.Model):
    """Um endereço pelo qual se envia, usando a conta associada."""

    conta = models.ForeignKey(
        ContaEmail, on_delete=models.PROTECT, related_name="aliases", verbose_name="conta"
    )
    slug = models.SlugField(
        "identificador", unique=True,
        help_text="Usado na URL e nos comandos. Ex.: financeiro",
    )
    endereco = models.EmailField("endereço", unique=True)
    nome_exibicao = models.CharField(
        "nome de exibição", max_length=200, blank=True,
        help_text="O que aparece antes do endereço no From:.",
    )
    reply_to = models.EmailField(
        "Reply-To", blank=True,
        help_text="Só se as respostas devem ir para outro endereço.",
    )
    assinatura_html = models.TextField(
        "assinatura (HTML)", blank=True,
        help_text="Anexada ao fim de toda mensagem deste alias. Não passa pelo sanitizador.",
    )
    ativo = models.BooleanField("ativo", default=True)
    ordem = models.PositiveIntegerField(
        "ordem", default=0, help_text="Ordem no seletor; o menor vem primeiro e já vem escolhido."
    )

    class Meta:
        ordering = ["ordem", "endereco"]
        verbose_name = "alias"
        verbose_name_plural = "aliases"

    def __str__(self):
        return f"{self.slug} <{self.endereco}>"

    # --- a interface que o resto do app consome -------------------------
    #
    # Estes nomes são os mesmos de quando os aliases vinham do ambiente, de
    # propósito: montagem.py, envio.py e as views não precisaram saber que a
    # origem mudou.

    @property
    def nome(self) -> str:
        return self.nome_exibicao

    @property
    def dominio(self) -> str:
        return self.endereco.rpartition("@")[2]

    @property
    def remetente(self) -> str:
        """O valor do cabeçalho `From:`.

        Sempre via `formataddr`: montar `"Nome <addr>"` à mão produz cabeçalho
        inválido quando o nome tem acento.
        """
        if not self.nome_exibicao:
            return self.endereco
        return formataddr((self.nome_exibicao, self.endereco))

    @property
    def envelope(self) -> str:
        """O `MAIL FROM` do SMTP — independente do cabeçalho `From:`."""
        return self.conta.envelope_from or self.endereco

    @property
    def dominio_message_id(self) -> str:
        """Vários filtros conferem se o domínio do Message-ID bate com o From."""
        return self.dominio

    @property
    def smtp(self) -> dict:
        """Kwargs prontos para `django.core.mail.get_connection`."""
        return {
            "host": self.conta.host,
            "port": self.conta.porta,
            "username": self.conta.usuario,
            "password": self.conta.senha,
            "use_tls": self.conta.usar_tls,
            "use_ssl": self.conta.usar_ssl,
            "timeout": self.conta.timeout,
        }

    def clean(self):
        if not self.conta_id:
            return
        dominios = self.conta.dominios
        if dominios and self.dominio.lower() not in dominios:
            raise ValidationError({
                "endereco": (
                    f"O domínio '{self.dominio}' não está entre os permitidos da conta "
                    f"({', '.join(dominios)}). Enviar com From: fora do domínio "
                    "autenticado quebra o alinhamento do DMARC e a mensagem vai para spam."
                )
            })


class RegistroEnvio(models.Model):
    class Status(models.TextChoices):
        ENVIANDO = "enviando", "Enviando"
        ENVIADO = "enviado", "Enviado"
        FALHOU = "falhou", "Falhou"

    criado_em = models.DateTimeField(auto_now_add=True)
    alias = models.CharField("alias", max_length=100)
    remetente = models.CharField("remetente", max_length=320)
    para = models.TextField("para")
    cc = models.TextField("cc", blank=True)
    cco = models.TextField("cco", blank=True)
    assunto = models.CharField("assunto", max_length=200, blank=True)

    message_id = models.CharField("message_id", max_length=255, unique=True)
    in_reply_to = models.CharField("in_reply_to", max_length=255, blank=True)
    referencias = models.TextField("referências", blank=True)

    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.ENVIANDO
    )
    erro = models.TextField("erro", blank=True)

    # Lista de {"nome": str, "tamanho": int, "tipo": str} — ver mensagens/anexos.py.
    anexos = models.JSONField("anexos", default=list, blank=True)

    # Atrás de settings.GUARDAR_CORPO_ENVIADO.
    corpo_html = models.TextField("corpo enviado", blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "registro de envio"
        verbose_name_plural = "registros de envio"

    def __str__(self):
        return f"{self.assunto or '(sem assunto)'} → {self.para}"

    @property
    def selo_css(self) -> str:
        return {"enviado": "enviado", "falhou": "falhou"}.get(self.status, "enviando")


class EnvioAgendado(models.Model):
    """Uma mensagem já conferida, esperando a hora de sair.

    Guarda os mesmos campos de `DadosRedacao` (ver `montagem.py`), e guarda o
    corpo **como saiu do editor** — HTML bruto, não sanitizado, com os
    marcadores `{{ … }}` intactos. Não é desleixo, são duas garantias:

    - o despacho chama `enviar_email()` exatamente como a tela chama, então
      sanitização, assinatura e montagem acontecem por um caminho só. Guardar o
      HTML já pronto seria uma segunda versão da verdade — a mesma razão pela
      qual a prévia não persiste rascunho (ver `views.redigir`);
    - `{{ data }}` e `{{ hora }}` expandem no **despacho**, que é o que se quer
      de um agendamento: a hora que interessa é a da entrega, não a de quem
      escreveu. Isso cai pronto da separação autoral/final que já existia.

    Os anexos continuam onde os do navegador ficam (`RASCUNHOS_DIR/<token>/`),
    e por isso `limpar_rascunhos` precisa saber destes tokens — ver
    `anexos.limpar_rascunhos_expirados`.
    """

    class Status(models.TextChoices):
        AGENDADO = "agendado", "Agendado"
        ENVIANDO = "enviando", "Enviando"
        ENVIADO = "enviado", "Enviado"
        FALHOU = "falhou", "Falhou"
        CANCELADO = "cancelado", "Cancelado"

    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    enviar_em = models.DateTimeField("enviar em", db_index=True)

    # FK, não o slug como no `RegistroEnvio`: aquele é log histórico e precisa
    # sobreviver ao alias; este é uma promessa futura, e apagar o alias de uma
    # mensagem que ainda vai sair tem que ser barrado, não registrado.
    alias = models.ForeignKey(
        Alias, on_delete=models.PROTECT, related_name="agendamentos", verbose_name="alias"
    )

    # Listas, não texto separado por vírgula: o que entrou tem que voltar
    # idêntico no despacho, sem passar por um segundo parser de endereço.
    para = models.JSONField("para", default=list)
    cc = models.JSONField("cc", default=list, blank=True)
    cco = models.JSONField("cco", default=list, blank=True)
    assunto = models.CharField("assunto", max_length=200, blank=True)

    corpo_html = models.TextField("corpo (HTML do editor)", blank=True)
    citacao_html = models.TextField("citação", blank=True)
    in_reply_to = models.CharField("in_reply_to", max_length=255, blank=True)
    referencias = models.TextField("referências", blank=True)
    token_anexos = models.CharField("token de anexos", max_length=64, blank=True)

    status = models.CharField(
        "status", max_length=10, choices=Status.choices, default=Status.AGENDADO
    )
    tentativas = models.PositiveIntegerField("tentativas", default=0)
    ultima_tentativa_em = models.DateTimeField("última tentativa", null=True, blank=True)
    erro = models.TextField("erro", blank=True)

    registro = models.ForeignKey(
        RegistroEnvio, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="agendamento", verbose_name="registro do envio",
    )

    class Meta:
        ordering = ["enviar_em"]
        verbose_name = "envio agendado"
        verbose_name_plural = "envios agendados"
        indexes = [models.Index(fields=["status", "enviar_em"], name="agendado_status_quando")]

    def __str__(self):
        quando = self.enviar_em.strftime("%d/%m/%Y %H:%M")
        return f"{self.assunto or '(sem assunto)'} → {self.destinatarios} em {quando}"

    @property
    def destinatarios(self) -> str:
        return ", ".join(self.para)

    @property
    def pendente(self) -> bool:
        return self.status == self.Status.AGENDADO

    @property
    def selo_css(self) -> str:
        return {
            self.Status.ENVIADO: "enviado",
            self.Status.FALHOU: "falhou",
            self.Status.CANCELADO: "cancelado",
        }.get(self.status, "agendado")
