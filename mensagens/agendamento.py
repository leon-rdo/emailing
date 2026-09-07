"""Envio programado: criar, cancelar e despachar.

O despachante é um comando de `manage.py` rodando por cron — não há fila nem
broker, e continua não havendo (ver docs/decisoes.md). A diferença que importa
em relação ao envio pela tela não é técnica, é humana: **ninguém está olhando**.
Daí as três coisas que este módulo tem e o caminho da tela não precisa:

1. `reivindicar()` — trava de concorrência de verdade, porque não existe
   POST-redirect-GET nem um dedo em cima do botão;
2. retentativa com espera crescente, porque uma falha às 3h da manhã não vai
   ser reenviada à mão;
3. tolerância de atraso, porque disparar às cegas o acumulado de dois dias de
   servidor fora do ar é pior do que não disparar.

O envio em si é o mesmo `enviar_email()` da tela, com o mesmo `RegistroEnvio` —
uma trilha de auditoria só, independente de quem redigiu ou de quando saiu.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.utils.html import escape

from .aliases import alias_por_slug
from .anexos import limpar_rascunho, transferir_rascunho
from .envio import enviar_email
from .models import Alias, EnvioAgendado, RegistroEnvio
from .montagem import DadosRedacao

logger = logging.getLogger(__name__)

_PENDENTES = (EnvioAgendado.Status.AGENDADO, EnvioAgendado.Status.ENVIANDO)


# ---------------------------------------------------------------------------
# Criar, ler de volta, cancelar
# ---------------------------------------------------------------------------


def agendar(
    alias: Alias, dados: DadosRedacao, enviar_em: datetime, token_anexos: str = ""
) -> EnvioAgendado:
    """Registra a mensagem para sair em `enviar_em`.

    Guarda o corpo como saiu do editor, sem sanitizar nem expandir marcador —
    o porquê está na docstring de `EnvioAgendado`.

    Os anexos mudam de token: cada agendamento é dono dos seus arquivos, senão
    o despacho de um levaria os anexos do outro (ver
    `anexos.transferir_rascunho`).
    """
    return EnvioAgendado.objects.create(
        alias=alias,
        enviar_em=enviar_em,
        para=list(dados.para),
        cc=list(dados.cc),
        cco=list(dados.cco),
        assunto=dados.assunto,
        corpo_html=dados.corpo_html,
        citacao_html=dados.citacao_html,
        in_reply_to=dados.in_reply_to,
        referencias=dados.referencias,
        token_anexos=transferir_rascunho(token_anexos),
    )


def dados_de(agendado: EnvioAgendado) -> DadosRedacao:
    """O inverso de `agendar()`: o mesmo `DadosRedacao` que a tela montaria."""
    return DadosRedacao(
        para=list(agendado.para),
        cc=list(agendado.cc),
        cco=list(agendado.cco),
        assunto=agendado.assunto,
        corpo_html=agendado.corpo_html,
        citacao_html=agendado.citacao_html,
        in_reply_to=agendado.in_reply_to,
        referencias=agendado.referencias,
    )


def cancelar(pk: int) -> bool:
    """Cancela se ainda estiver esperando; `False` se já saiu ou já acabou.

    Quem decide é o `UPDATE`, não um `if` sobre um objeto lido antes: entre a
    tela desenhar o botão e alguém clicar, o cron pode ter despachado.
    """
    agendado = EnvioAgendado.objects.filter(pk=pk).first()
    if agendado is None:
        return False
    trocou = EnvioAgendado.objects.filter(
        pk=pk, status=EnvioAgendado.Status.AGENDADO
    ).update(status=EnvioAgendado.Status.CANCELADO)
    if not trocou:
        return False
    # Os anexos ficaram órfãos no mesmo instante. Só é seguro apagar aqui
    # porque o UPDATE acima garante que nenhum despacho está em curso.
    limpar_rascunho(agendado.token_anexos)
    return True


def tokens_pendentes() -> list[str]:
    """Tokens de anexo que a limpeza de rascunhos **não** pode apagar.

    Ver `anexos.limpar_rascunhos_expirados` — sem isto um agendamento longo sai
    sem anexo, em silêncio.
    """
    return list(
        EnvioAgendado.objects.filter(status__in=_PENDENTES)
        .exclude(token_anexos="")
        .values_list("token_anexos", flat=True)
    )


# ---------------------------------------------------------------------------
# Despacho
# ---------------------------------------------------------------------------


def reivindicar(agendado: EnvioAgendado) -> bool:
    """Marca como em despacho e diz se **este** processo ganhou a corrida.

    É a única trava de concorrência do projeto, e aqui ela é obrigatória. A
    decisão de não travar duplo envio (docs/decisoes.md) se apoia em
    POST-redirect-GET e num humano; no cron não há nem um nem outro, e duas
    execuções sobrepostas mandariam a mesma mensagem duas vezes. O
    `UPDATE … WHERE status='agendado'` é atômico (o banco abre transação em
    `IMMEDIATE`), e dono é quem vê `rowcount == 1`. O `flock` da linha do cron
    é o cinto; esta é a corda.
    """
    trocou = EnvioAgendado.objects.filter(
        pk=agendado.pk, status=EnvioAgendado.Status.AGENDADO
    ).update(
        status=EnvioAgendado.Status.ENVIANDO,
        tentativas=F("tentativas") + 1,
        ultima_tentativa_em=timezone.now(),
    )
    if trocou:
        # `F()` deixa o objeto em memória desatualizado, e o número de
        # tentativas é justamente o que decide retentativa vs. desistência.
        agendado.refresh_from_db()
    return bool(trocou)


def despachar_um(agendado: EnvioAgendado) -> RegistroEnvio | None:
    """Envia um agendamento **já reivindicado**. Nunca levanta.

    Devolve o `RegistroEnvio` da tentativa, ou `None` quando nem chegou a
    tentar. Cada tentativa gera o seu registro: `RegistroEnvio` é log de
    tentativas de envio, e três tentativas foram três tentativas.
    """
    alias = agendado.alias
    if not alias.ativo or not alias.conta.ativa:
        _desistir(
            agendado,
            f"O alias '{alias.slug}' ou a conta '{alias.conta.nome}' está inativo — "
            "reative e reagende.",
        )
        return None

    atraso = timezone.now() - agendado.enviar_em
    tolerancia = settings.AGENDADOS_TOLERANCIA_HORAS
    if tolerancia and atraso > timedelta(hours=tolerancia):
        horas = int(atraso.total_seconds() // 3600)
        _desistir(
            agendado,
            f"Atrasado {horas}h, acima da tolerância de {tolerancia}h. Não enviado de "
            "propósito: a mensagem foi escrita para um momento que já passou. Reagende "
            "se ainda fizer sentido.",
        )
        return None

    registro = enviar_email(alias, dados_de(agendado), token_anexos=agendado.token_anexos)
    agendado.registro = registro

    if registro.status == RegistroEnvio.Status.ENVIADO:
        agendado.status = EnvioAgendado.Status.ENVIADO
        agendado.erro = ""
        agendado.save(update_fields=["status", "erro", "registro"])
        logger.info("Agendamento %s enviado: %s", agendado.pk, registro.message_id)
        return registro

    if agendado.tentativas < settings.AGENDADOS_MAX_TENTATIVAS:
        espera = settings.AGENDADOS_BACKOFF_MINUTOS * 2 ** (agendado.tentativas - 1)
        agendado.status = EnvioAgendado.Status.AGENDADO
        agendado.enviar_em = timezone.now() + timedelta(minutes=espera)
        agendado.erro = registro.erro
        agendado.save(update_fields=["status", "enviar_em", "erro", "registro"])
        logger.warning(
            "Agendamento %s falhou na tentativa %s; tenta de novo em %s min: %s",
            agendado.pk, agendado.tentativas, espera, registro.erro,
        )
        return registro

    _desistir(agendado, registro.erro)
    return registro


def despachar_pendentes(limite: int | None = None, agora: datetime | None = None) -> list:
    """Despacha o que já venceu, um a um, até o teto da execução.

    Um a um, e não em paralelo, porque o limite que importa é o do provedor:
    Hostinger e Titan contam saída por hora e por dia, e um lote disparado de
    uma vez volta como uma fileira de FALHOU em vez de atraso.
    """
    limite = settings.AGENDADOS_MAX_POR_EXECUCAO if limite is None else limite
    agora = agora or timezone.now()
    vencidos = list(
        EnvioAgendado.objects.filter(
            status=EnvioAgendado.Status.AGENDADO, enviar_em__lte=agora
        )
        .select_related("alias__conta")
        .order_by("enviar_em")[:limite]
    )

    despachados = []
    for agendado in vencidos:
        if not reivindicar(agendado):
            continue  # outra execução chegou primeiro — e está tudo certo
        despachar_um(agendado)
        despachados.append(agendado)
    return despachados


def _desistir(agendado: EnvioAgendado, motivo: str) -> None:
    agendado.status = EnvioAgendado.Status.FALHOU
    agendado.erro = motivo
    agendado.save(update_fields=["status", "erro", "registro"])
    logger.error("Agendamento %s desistido: %s", agendado.pk, motivo)
    _avisar_falha(agendado, motivo)


def _avisar_falha(agendado: EnvioAgendado, motivo: str) -> None:
    """Avisa o operador que uma mensagem agendada não saiu.

    Falha em silêncio (com log) de propósito: um aviso que não consegue sair não
    pode virar uma segunda falha em cascata. E é por isso que existe
    `AGENDADOS_AVISAR_ALIAS` — se o alias do agendamento está com a credencial
    quebrada, avisar por ele também não funcionaria.
    """
    para = settings.AGENDADOS_AVISAR_PARA
    if not para:
        return
    try:
        alias_aviso = (
            alias_por_slug(settings.AGENDADOS_AVISAR_ALIAS)
            if settings.AGENDADOS_AVISAR_ALIAS
            else agendado.alias
        )
        quando = timezone.localtime(agendado.enviar_em).strftime("%d/%m/%Y %H:%M")
        enviar_email(
            alias_aviso,
            DadosRedacao(
                para=[para],
                assunto=f"[Emailing] Agendamento #{agendado.pk} não foi enviado",
                corpo_html=(
                    f"<p>O agendamento <strong>#{agendado.pk}</strong> esgotou as "
                    f"tentativas e não foi enviado.</p>"
                    f"<ul>"
                    f"<li>Alias: <code>{escape(agendado.alias.slug)}</code></li>"
                    f"<li>Para: {escape(agendado.destinatarios)}</li>"
                    f"<li>Assunto: {escape(agendado.assunto or '(sem assunto)')}</li>"
                    f"<li>Era para sair em: {quando}</li>"
                    f"<li>Tentativas: {agendado.tentativas}</li>"
                    f"</ul>"
                    f"<p>Último erro:</p><pre>{escape(motivo)}</pre>"
                ),
            ),
        )
    except Exception:
        logger.exception("Não consegui avisar sobre a falha do agendamento %s", agendado.pk)
