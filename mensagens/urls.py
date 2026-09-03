from django.urls import path

from . import views

app_name = "mensagens"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("entrar/", views.Entrar.as_view(), name="entrar"),
    path("sair/", views.Sair.as_view(), name="sair"),
    path("historico/", views.historico, name="historico"),
    path("historico/<int:pk>/", views.registro, name="registro"),
]
