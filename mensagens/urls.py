from django.urls import path

from . import views
from . import views_configuracoes as config

app_name = "mensagens"

urlpatterns = [
    path("", views.redigir, name="inicio"),
    path("previa-ajax/", views.previa_ajax, name="previa_ajax"),
    path("importar/", views.importar_eml, name="importar"),
    path("entrar/", views.Entrar.as_view(), name="entrar"),
    path("sair/", views.Sair.as_view(), name="sair"),
    path("agendados/", views.agendados, name="agendados"),
    path("agendados/<int:pk>/", views.agendado, name="agendado"),
    path("agendados/<int:pk>/cancelar/", views.cancelar_agendado, name="cancelar_agendado"),
    path("mensagens/<int:pk>/editar/", views.redigir, name="editar"),
    path("rascunhos/", views.rascunhos, name="rascunhos"),
    path("rascunhos/<int:pk>/descartar/", views.descartar, name="descartar_rascunho"),
    path("historico/", views.historico, name="historico"),
    path("historico/<int:pk>/", views.registro, name="registro"),
    path("configuracoes/", config.indice, name="configuracoes"),
    path("configuracoes/contas/", config.contas, name="config_contas"),
    path("configuracoes/contas/nova/", config.conta_form, name="config_conta_nova"),
    path("configuracoes/contas/testar/", config.testar_conta, name="config_conta_testar"),
    path("configuracoes/contas/<int:pk>/", config.conta_form, name="config_conta"),
    path("configuracoes/aliases/", config.aliases, name="config_aliases"),
    path("configuracoes/aliases/novo/", config.alias_form, name="config_alias_novo"),
    path("configuracoes/aliases/<int:pk>/", config.alias_form, name="config_alias"),
    path(
        "configuracoes/assinatura-previa/", config.assinatura_previa,
        name="config_assinatura_previa",
    ),
]
