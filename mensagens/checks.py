"""System checks da configuração de aliases.

Como check (e não como exceção no `ready()`), um alias mal configurado derruba
`manage.py check`, `migrate`, `runserver` e o boot do gunicorn — mas ainda deixa
`manage.py verificar_config` rodar para explicar o que está errado, porque
aquele comando desliga os checks de propósito.
"""

from django.core.checks import Error, register

from .aliases import montar_aliases


@register()
def verificar_aliases(app_configs, **kwargs):
    _, erros = montar_aliases()
    return [
        Error(msg, hint="Rode `manage.py verificar_config` para o diagnóstico completo.",
              id="mensagens.E001")
        for msg in erros
    ]
