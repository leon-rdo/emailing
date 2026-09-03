"""Log de envios.

Os quatro campos pedidos pelo requisito são `criado_em`, `remetente`, `para` e
`assunto`. Os demais se pagam sozinhos: `message_id` é o que transforma este
log num armazém de threads (usado para "responder a algo que eu enviei" — ver
`eml.py` e a Etapa 8) e o que permite achar a mensagem na caixa real;
`in_reply_to`/`referencias` são o que torna uma thread depurável; `status` e
`erro` são o que impede acreditar que um envio funcionou quando falhou —
`status=ENVIANDO`, gravado antes da chamada SMTP, é o registro de que o envio
foi tentado.

Nomes de domínio em português; `message_id`/`in_reply_to` em inglês porque são
nomes de cabeçalho da RFC 5322, não vocabulário do domínio.
"""

from django.db import models


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
