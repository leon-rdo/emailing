"""Envio programado: criar, editar, cancelar e despachar.

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

Editar e despachar disputam a mesma linha, e quem decide é sempre um
`UPDATE … WHERE status IN (…)` — nunca um `if` sobre um objeto lido antes. Entre
a tela abrir e o operador clicar em Salvar, o cron pode ter reivindicado a
mensagem; quem perde a corrida descobre pelo `rowcount`, não por sorte.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone
from django.utils.html import escape

from .aliases import alias_por_slug
from .anexos import limpar_rascunho, resumo_dos_anexos, transferir_rascunho
from .envio import enviar_email
from .models import Alias, EnvioAgendado, RegistroEnvio
from .montagem import DadosRedacao

logger = logging.getLogger(__name__)

# Quem ainda vai precisar dos arquivos. O rascunho entra porque, sem isso, a
# limpeza diária o deixaria sem anexo ao fim do TTL — e o rascunho só é aberto
# de novo quando o operador voltar a ele, que pode ser depois. Quem o limita é
# `expirar_rascunhos`, não o TTL dos anexos.
_COM_ANEXOS_VIVOS = (
    EnvioAgendado.Status.RASCUNHO,
    EnvioAgendado.Status.AGENDADO,
    EnvioAgendado.Status.ENVIANDO,
)


# ---------------------------------------------------------------------------
# Criar, ler de volta, cancelar
# ---------------------------------------------------------------------------


def _campos_de(dados: DadosRedacao) -> dict:
    """Os campos do modelo que vêm do formulário, para criar e para reescrever."""
    return {
        "para": list(dados.para),
        "cc": list(dados.cc),
        "cco": list(dados.cco),
        "assunto": dados.assunto,
        "corpo_html": dados.corpo_html,
        "citacao_html": dados.citacao_html,
        "in_reply_to": dados.in_reply_to,
        "referencias": dados.referencias,
    }


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
    token = transferir_rascunho(token_anexos)
    return EnvioAgendado.objects.create(
        alias=alias,
        enviar_em=enviar_em,
        token_anexos=token,
        anexos=resumo_dos_anexos(token),
        **_campos_de(dados),
    )


def guardar_rascunho(
    alias: Alias, dados: DadosRedacao, enviar_em: datetime | None = None, token_anexos: str = ""
) -> EnvioAgendado:
    """Guarda a mensagem para continuar depois. Nada é validado além do formulário.

    Nunca é despachada: o despacho só olha `status=agendado`. Os anexos mudam de
    token pelo mesmo motivo de `agendar()`.
    """
    token = transferir_rascunho(token_anexos)
    return EnvioAgendado.objects.create(
        alias=alias,
        enviar_em=enviar_em,
        status=EnvioAgendado.Status.RASCUNHO,
        token_anexos=token,
        anexos=resumo_dos_anexos(token),
        **_campos_de(dados),
    )


def reescrever(
    pk: int,
    alias: Alias,
    dados: DadosRedacao,
    *,
    de: tuple[str, ...],
    para: str,
    enviar_em: datetime | None,
    token_anexos: str,
) -> bool:
    """Troca o conteúdo de uma mensagem guardada e, se preciso, o seu status.

    Cobre três gestos, que só diferem em `de` → `para`: salvar alterações de um
    agendado (`agendado → agendado`), salvar um rascunho (`rascunho → rascunho`)
    e as duas viradas (`rascunho → agendado` ao agendar, `agendado → rascunho` ao
    tirar da fila). Devolve `False` — sem alterar nada — quando a mensagem já não
    estava em nenhum dos estados `de`, tipicamente porque o cron a reivindicou
    enquanto a tela estava aberta.

    `token_anexos` é a **cópia** em que a tela trabalhou (ver
    `anexos.copiar_rascunho`), não a pasta da mensagem. Ela só substitui a
    original depois que o `UPDATE` ganha; perdendo, a cópia é apagada e a
    original nunca foi tocada.

    Zera `tentativas` e `erro`: reescrever é prometer outra coisa, e herdar
    contagem de uma falha anterior gastaria as tentativas da promessa nova.
    """
    novo_token = transferir_rascunho(token_anexos)
    antigo = EnvioAgendado.objects.filter(pk=pk).values_list("token_anexos", flat=True).first()
    trocou = EnvioAgendado.objects.filter(pk=pk, status__in=de).update(
        alias=alias,
        enviar_em=enviar_em,
        status=para,
        token_anexos=novo_token,
        anexos=resumo_dos_anexos(novo_token),
        tentativas=0,
        erro="",
        atualizado_em=timezone.now(),
        **_campos_de(dados),
    )
    if not trocou:
        limpar_rascunho(novo_token)
        return False
    if antigo and antigo != novo_token:
        limpar_rascunho(antigo)
    return True


def descartar_rascunho(pk: int, *, parado_desde: datetime | None = None) -> bool:
    """Apaga o rascunho e os seus anexos. `False` se já não era um rascunho.

    Com `parado_desde`, só apaga se ele **continua** sem alteração desde então.
    É a condição da expiração: entre listar os vencidos e apagar, o operador pode
    ter voltado e salvado, e um rascunho recém-salvo não pode morrer por ter
    estado na lista.

    Apaga de verdade, não marca como cancelado: descartar é dizer "isto não
    existiu", e um cemitério de rascunhos em `Encerrados` seria ruído. Só
    rascunho — uma mensagem que já esteve na fila deixa rastro, e é por isso que
    ela se **cancela**.
    """
    alvo = EnvioAgendado.objects.filter(pk=pk, status=EnvioAgendado.Status.RASCUNHO)
    if parado_desde is not None:
        alvo = alvo.filter(atualizado_em__lt=parado_desde)
    linha = alvo.first()
    if linha is None:
        return False
    apagou, _ = alvo.delete()
    if apagou:
        limpar_rascunho(linha.token_anexos)
    return bool(apagou)


def expirar_rascunhos(dias: int, agora: datetime | None = None) -> int:
    """Apaga os rascunhos sem alteração há mais de `dias`. `0` desliga.

    Chamado antes da limpeza de pastas de anexos (ver `limpar_rascunhos`): assim
    os arquivos dos vencidos somem junto com eles e a pasta, já fora de
    `tokens_pendentes()`, nem precisa esperar o TTL dos anexos.
    """
    if not dias:
        return 0
    limite = (agora or timezone.now()) - timedelta(days=dias)
    vencidos = EnvioAgendado.objects.filter(
        status=EnvioAgendado.Status.RASCUNHO, atualizado_em__lt=limite
    ).values_list("pk", flat=True)
    return sum(descartar_rascunho(pk, parado_desde=limite) for pk in list(vencidos))


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
    # A foto dos anexos é tirada **antes** de a pasta sumir: é o que deixa a tela
    # de detalhe dizer o que estava anexado a uma mensagem já cancelada.
    resumo = resumo_dos_anexos(agendado.token_anexos)
    trocou = EnvioAgendado.objects.filter(
        pk=pk, status=EnvioAgendado.Status.AGENDADO
    ).update(
        status=EnvioAgendado.Status.CANCELADO,
        anexos=resumo or agendado.anexos,
        atualizado_em=timezone.now(),
    )
    if not trocou:
        return False
    # Os anexos ficaram órfãos no mesmo instante. Só é seguro apagar aqui
    # porque o UPDATE acima garante que nenhum despacho está em curso.
    limpar_rascunho(agendado.token_anexos)
    return True


def tokens_pendentes() -> list[str]:
    """Tokens de anexo que a limpeza de rascunhos **não** pode apagar.

    Ver `anexos.limpar_rascunhos_expirados` — sem isto um agendamento longo sai
    sem anexo, em silêncio. Vale também para a mensagem salva como rascunho:
    perderia os anexos ao fim do TTL, e dessa vez sem sequer haver um envio
    para falhar.
    """
    return list(
        EnvioAgendado.objects.filter(status__in=_COM_ANEXOS_VIVOS)
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
