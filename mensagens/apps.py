from django.apps import AppConfig


class MensagensConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "mensagens"
    verbose_name = "Mensagens"

    # Nada de validar aliases aqui: eles vivem no banco, e o `ready()` roda
    # antes de qualquer migração ter rodado. Quem valida agora é o `clean()`
    # dos modelos (no admin, na hora de salvar) e o `manage.py verificar_config`.
    #
    # O ajuste do DNS_NAME (Message-ID e EHLO) também saiu daqui: com contas em
    # domínios diferentes, ele passou a ser por envio — ver `envio.py`.
