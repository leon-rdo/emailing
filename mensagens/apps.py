from django.apps import AppConfig
from django.conf import settings


class MensagensConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mensagens"
    verbose_name = "Mensagens"

    def ready(self):
        from . import checks  # noqa: F401  — registra os system checks dos aliases

        self._fixar_dns_name()

    @staticmethod
    def _fixar_dns_name():
        """Conserta de uma vez o Message-ID e o nome do EHLO.

        O Django gera o `Message-ID` a partir de `django.core.mail.utils.DNS_NAME`,
        que é `socket.getfqdn()`. Numa máquina qualquer isso vira algo como
        `<...@leonardo-costa>` — ruim para entregabilidade. E o mesmo `DNS_NAME`
        também é o `local_hostname` do `EHLO` do SMTP, então o problema é duplo.

        O domínio certo é o do remetente (vários filtros conferem se ele bate
        com o `From:`), não o host onde o app roda.
        """
        from django.core.mail.utils import DNS_NAME

        from .aliases import montar_aliases

        dominio = settings.MESSAGE_ID_DOMAIN
        if not dominio:
            aliases, _ = montar_aliases()
            dominio = aliases[0].dominio if aliases else ""
        if dominio:
            DNS_NAME._fqdn = dominio
