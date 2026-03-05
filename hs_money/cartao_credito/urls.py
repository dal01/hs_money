from django.urls import path
from . import views

app_name = 'cartao_credito'

urlpatterns = [
    path('',           views.listar_faturas_disco, name='listar_faturas'),
    path('processar/', views.processar_faturas,    name='processar_faturas'),
]
