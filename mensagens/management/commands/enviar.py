"""Envia — ou agenda — um e-mail por um alias, da linha de comando.

Existe para o operador e para um agente com acesso ssh ao servidor. A
autenticação é a chave ssh de propósito: um endpoint HTTP capaz de enviar como
estes domínios seria, se o token vazasse, um relay aberto **com DMARC
alinhado**. Ver docs/decisoes.md.

Três coisas que este comando não tem, todas de propósito:

- **corpo por argumento.** O corpo vem de arquivo ou do stdin. HTML em `argv`
  aparece no `ps` de qualquer outro usuário da máquina — e esta VPS roda outros
  serviços — e ainda vai para o histórico do shell.
- **trava de `hash_previa`.** Na tela ela existe porque há um intervalo humano
  entre pré-visualizar e clicar, e o conteúdo pode mudar nesse intervalo. Aqui
  é um processo e uma entrada, sem intervalo: a trava não protegeria de nada.
  Quem quer conferir antes usa `--conferir`, que não envia.
- **validação própria.** Endereços, limite de destinatários, escolha de alias e
  formato de data saem todos do `FormularioRedacao`, o mesmo da tela. Duas
  validações acabam divergindo, e o sintoma seria "funciona no navegador e não
  no terminal".
"""

import json
import sys
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mensagens.agendamento import agendar
from mensagens.aliases import alias_por_slug, carregar_aliases
from mensagens.anexos import ErroAnexo, criar_token, guardar_caminhos, inspecionar_caminhos
from mensagens.envio import enviar_email
from mensagens.forms import FormularioRedacao, analisar_enviar_em, dados_do_formulario
from mensagens.models import RegistroEnvio
from mensagens.montagem import montar_email


class Command(BaseCommand):
    help = "Envia ou agenda um e-mail por um alias. O corpo vem de arquivo ou do stdin."

    def add_arguments(self, parser):
        parser.add_argument("--alias", required=True, help="slug do alias, ex.: financeiro")
        parser.add_argument("--para", default="", help="destinatários separados por vírgula")
        parser.add_argument("--cc", default="")
        parser.add_argument("--cco", default="")
        parser.add_argument("--assunto", default="")
        parser.add_argument(
            "--corpo-arquivo", dest="corpo_arquivo", default=None,
            help="arquivo com o HTML do corpo; '-' lê do stdin (o padrão quando há stdin).",
        )
        parser.add_argument(
            "--anexo", action="append", default=[], metavar="CAMINHO",
            help="pode repetir; vale os mesmos limites do formulário.",
        )
        parser.add_argument("--in-reply-to", dest="in_reply_to", default="")
        parser.add_argument("--referencias", default="")
        parser.add_argument(
            "--em", default="",
            help='agenda em vez de enviar. Ex.: "2026-09-10 09:00" ou "10/09/2026 09:00".',
        )
        parser.add_argument(
            "--conferir", action="store_true",
            help="mostra o que sairia (envelope, HTML e texto finais) e não envia nada.",
        )
        parser.add_argument(
            "--json", action="store_true", dest="como_json",
            help="saída legível por máquina.",
        )

    def handle(self, *args, **options):
        conferir = options["conferir"]
        como_json = options["como_json"]

        alias = self._alias(options["alias"])
        corpo = self._corpo(options["corpo_arquivo"])
        quando = self._quando(options["em"]) if options["em"] else None

        form = FormularioRedacao(
            data={
                "alias": alias.slug,
                "para": options["para"],
                "cc": options["cc"],
                "cco": options["cco"],
                "assunto": options["assunto"],
                "corpo": corpo,
                "in_reply_to": options["in_reply_to"],
                "referencias": options["referencias"],
                "citacao_html": "",
            },
            aliases=carregar_aliases(),
        )
        if conferir:
            # As duas tolerâncias da prévia da tela se separam aqui. "Sem
            # destinatário" continua valendo — conferir é do conteúdo, e o
            # destinatário costuma ser a última coisa que se decide. "Endereço
            # inválido" não: na tela ele é descartado porque vem outra tecla
            # atrás; aqui não vem nada atrás, e um endereço torto tem que doer
            # agora, não no envio.
            form.fields["para"].minimo_um = False
        if not form.is_valid():
            raise CommandError(self._erros(form))

        dados = dados_do_formulario(form)

        if conferir:
            self._mostrar_conferencia(alias, dados, options["anexo"], quando, como_json)
            return

        token = self._guardar_anexos(options["anexo"])

        if quando:
            agendado = agendar(alias, dados, quando, token_anexos=token)
            self._relatar_agendamento(agendado, como_json)
            return

        registro = enviar_email(alias, dados, token_anexos=token)
        self._relatar_envio(registro, como_json)

    # --- entradas -------------------------------------------------------

    def _alias(self, slug: str):
        disponiveis = carregar_aliases()
        if not disponiveis:
            raise CommandError(
                "Nenhum alias ativo cadastrado. Cadastre no admin ou rode "
                "`manage.py verificar_config` para ver o que está faltando."
            )
        try:
            return alias_por_slug(slug)
        except KeyError as exc:
            nomes = ", ".join(a.slug for a in disponiveis)
            raise CommandError(f"Alias desconhecido: {slug!r}. Disponíveis: {nomes}.") from exc

    def _corpo(self, caminho: str | None) -> str:
        if caminho == "-":
            return sys.stdin.read()
        if caminho:
            try:
                return Path(caminho).expanduser().read_text(encoding="utf-8")
            except OSError as exc:
                raise CommandError(f"Não consegui ler o corpo em {caminho}: {exc}") from exc
        if not sys.stdin.isatty():
            return sys.stdin.read()
        raise CommandError(
            "Sem corpo. Use --corpo-arquivo <arquivo>, ou mande o HTML pelo stdin "
            "(o corpo não entra por argumento: HTML em argv vaza no `ps` e no "
            "histórico do shell)."
        )

    def _quando(self, bruto: str):
        try:
            quando = analisar_enviar_em(bruto)
        except ValidationError as exc:
            raise CommandError(
                f"--em: {' '.join(exc.messages)} Formatos aceitos: "
                '"2026-09-10 09:00", "10/09/2026 09:00", "2026-09-10T09:00".'
            ) from exc
        if quando <= timezone.now():
            local = timezone.localtime(quando).strftime("%d/%m/%Y %H:%M")
            raise CommandError(f"--em: {local} já passou (fuso {settings.TIME_ZONE}).")
        return quando

    def _guardar_anexos(self, caminhos: list[str]) -> str:
        if not caminhos:
            return ""
        token = criar_token()
        try:
            guardar_caminhos(token, caminhos)
        except ErroAnexo as exc:
            raise CommandError(str(exc)) from exc
        return token

    def _erros(self, form) -> str:
        partes = list(form.non_field_errors())
        for campo, lista in form.errors.items():
            if campo == "__all__":
                continue
            partes += [f"--{campo.replace('_', '-')}: {erro}" for erro in lista]
        return "\n".join(partes)

    # --- saídas ---------------------------------------------------------

    def _mostrar_conferencia(self, alias, dados, caminhos_anexos, quando, como_json):
        """Como a prévia da tela, e pelo mesmo caminho de código: `montar_email`
        é função pura, então isto é literalmente o que sairia.

        Não lê os bytes dos anexos, só os descreve — anexo nunca entra no corpo
        HTML, vira parte MIME separada (mesma razão de `views._previa_de`).
        """
        try:
            anexos = inspecionar_caminhos(caminhos_anexos)
        except ErroAnexo as exc:
            raise CommandError(str(exc)) from exc

        mensagem = montar_email(dados, alias)
        html = mensagem.alternatives[0][0]

        if como_json:
            self.stdout.write(json.dumps({
                "ok": True,
                "acao": "conferir",
                "alias": alias.slug,
                "remetente": alias.remetente,
                "envelope": alias.envelope,
                "reply_to": alias.reply_to,
                "para": dados.para,
                "cc": dados.cc,
                "cco": dados.cco,
                "assunto": dados.assunto,
                "in_reply_to": dados.in_reply_to,
                "referencias": dados.referencias,
                "agendar_para": quando.isoformat() if quando else None,
                "anexos": [
                    {"nome": a.nome, "tamanho": a.tamanho, "tipo": a.tipo} for a in anexos
                ],
                "html": html,
                "texto": mensagem.body,
            }, ensure_ascii=False))
            return

        escrever = self.stdout.write
        escrever(self.style.MIGRATE_HEADING("envelope"))
        escrever(f"  From: ......... {alias.remetente}")
        escrever(f"  envelope ...... {alias.envelope}")
        if alias.reply_to:
            escrever(f"  Reply-To ...... {alias.reply_to}")
        escrever(f"  Para .......... {', '.join(dados.para) or '(nenhum)'}")
        if dados.cc:
            escrever(f"  Cc ............ {', '.join(dados.cc)}")
        if dados.cco:
            escrever(f"  Cco ........... {', '.join(dados.cco)}")
        escrever(f"  Assunto ....... {dados.assunto or '(sem assunto)'}")
        if dados.in_reply_to:
            escrever(f"  In-Reply-To ... {dados.in_reply_to}")
        if quando:
            local = timezone.localtime(quando).strftime("%d/%m/%Y %H:%M")
            escrever(f"  agendaria para  {local} ({settings.TIME_ZONE})")
        for anexo in anexos:
            escrever(f"  anexo ......... {anexo.nome} ({anexo.tamanho_legivel}, {anexo.tipo})")
        escrever("")
        escrever(self.style.MIGRATE_HEADING("html final"))
        escrever(html)
        escrever("")
        escrever(self.style.MIGRATE_HEADING("texto final"))
        escrever(mensagem.body)
        escrever("")
        escrever(self.style.WARNING("Nada foi enviado (--conferir)."))

    def _relatar_envio(self, registro, como_json):
        ok = registro.status == RegistroEnvio.Status.ENVIADO
        if como_json:
            self.stdout.write(json.dumps({
                "ok": ok,
                "acao": "enviar",
                "status": registro.status,
                "message_id": registro.message_id,
                "registro": registro.pk,
                "historico": f"/historico/{registro.pk}/",
                "erro": registro.erro,
            }, ensure_ascii=False))
        elif ok:
            self.stdout.write(self.style.SUCCESS(f"Enviado. Message-ID: {registro.message_id}"))
            self.stdout.write(f"Histórico: /historico/{registro.pk}/")
        else:
            self.stderr.write(self.style.ERROR(f"Falha ao enviar: {registro.erro}"))
            self.stderr.write(f"Registrado em /historico/{registro.pk}/")
        if not ok:
            raise SystemExit(1)

    def _relatar_agendamento(self, agendado, como_json):
        local = timezone.localtime(agendado.enviar_em).strftime("%d/%m/%Y %H:%M")
        if como_json:
            self.stdout.write(json.dumps({
                "ok": True,
                "acao": "agendar",
                "agendado": agendado.pk,
                "enviar_em": agendado.enviar_em.isoformat(),
                "status": agendado.status,
                "token_anexos": agendado.token_anexos,
            }, ensure_ascii=False))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Agendado #{agendado.pk} para {local} ({settings.TIME_ZONE})."
                )
            )
            self.stdout.write("Quem despacha é o cron, por `manage.py despachar_agendados`.")
