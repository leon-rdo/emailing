"""Acesso aos aliases cadastrados.

Os aliases já moraram no ambiente (`ALIASES` + `ALIAS_<SLUG>_*`). Agora moram
no banco, gerenciados pelo admin — cadastrar um alias não exige mais ssh no
servidor nem reiniciar o serviço, e uma conta nova (outro provedor, outro
domínio) é um formulário em vez de seis variáveis.

Este módulo continua existindo, e com os mesmos nomes de antes, porque é o que
`montagem.py`, `envio.py` e as views importam: a origem dos dados mudou, a
interface não. O comando `importar_aliases_do_env` traz o que estava no
ambiente para o banco uma única vez.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from .models import Alias


def carregar_aliases() -> list[Alias]:
    """Aliases ativos, na ordem do seletor."""
    return list(Alias.objects.filter(ativo=True).select_related("conta"))


def alias_por_slug(slug: str) -> Alias:
    try:
        return Alias.objects.select_related("conta").get(slug=slug, ativo=True)
    except Alias.DoesNotExist as exc:
        raise KeyError(f"Alias desconhecido: {slug!r}") from exc


def verificar_aliases() -> list[str]:
    """Problemas de configuração, em linguagem de gente. Lista vazia = tudo certo.

    Não levanta: quem chama (o `verificar_config`) quer mostrar todos os
    problemas de uma vez, não morrer no primeiro.
    """
    problemas = []
    aliases = carregar_aliases()

    if not aliases:
        problemas.append(
            "Nenhum alias ativo cadastrado. Cadastre uma conta e um alias no admin "
            "(/admin/mensagens/contaemail/), ou rode `manage.py importar_aliases_do_env`."
        )

    for alias in aliases:
        if not alias.conta.ativa:
            problemas.append(f"Alias '{alias.slug}': a conta '{alias.conta.nome}' está inativa.")
        if not alias.conta.senha_cifrada:
            problemas.append(f"Conta '{alias.conta.nome}': sem senha cadastrada.")
        else:
            try:
                _ = alias.conta.senha  # só para ver se decifra
            except Exception as exc:  # SenhaIlegivel, e qualquer surpresa do Fernet
                problemas.append(f"Conta '{alias.conta.nome}': {exc}")

        dominios = alias.conta.dominios
        if dominios and alias.dominio.lower() not in dominios:
            problemas.append(
                f"Alias '{alias.slug}': domínio '{alias.dominio}' fora dos permitidos "
                f"da conta ({', '.join(dominios)}) — o DMARC não vai alinhar."
            )

    return problemas


def exigir_aliases() -> list[Alias]:
    """Como `carregar_aliases`, mas explode se não houver nenhum utilizável."""
    aliases = carregar_aliases()
    if not aliases:
        raise ImproperlyConfigured(
            "Nenhum alias ativo cadastrado — cadastre um no admin antes de enviar."
        )
    return aliases
