"""Hasher de senha.

O padrão do `Argon2PasswordHasher` do Django é `memory_cost=102400` — 100 MiB de
RAM por hash. Com 2 workers × 4 threads no gunicorn isso são 800 MB que um bot
consegue queimar só batendo na tela de login. O perfil recomendado pela OWASP
(m=19456, t=2, p=1) custa 19 MiB por hash e é o suficiente aqui, ainda mais
porque o django-axes corta a tentativa antes do hash rodar.
"""

from django.conf import settings
from django.contrib.auth.hashers import Argon2PasswordHasher


class Argon2PerfilOWASP(Argon2PasswordHasher):
    memory_cost = settings.ARGON2_MEMORY_KIB
    time_cost = 2
    parallelism = 1
