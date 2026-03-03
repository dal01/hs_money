from django.urls import path
from . import views

app_name = 'conta_corrente'

urlpatterns = [
    path('',                              views.index,          name='index'),

    # Contas Correntes
    path('contas/',                       views.conta_lista,    name='conta_lista'),
    path('contas/nova/',                  views.conta_criar,    name='conta_criar'),
    path('contas/<int:pk>/editar/',       views.conta_editar,   name='conta_editar'),

    # Upload genérico
    path('upload/',                       views.upload_extrato, name='upload_extrato'),
    # Upload pré-selecionado por conta
    path('contas/<int:conta_pk>/upload/', views.upload_extrato, name='upload_por_conta'),
    # Processar OFX (disco → banco)
    path('processar/',                    views.processar_extratos,    name='processar_extratos'),
    # Listagem de OFX no disco
    path('extratos/',                     views.listar_extratos_disco, name='listar_extratos'),
    # Transações
    path('contas/<int:pk>/transacoes/',   views.transacoes_conta,  name='transacoes_conta'),
    path('transacoes/',                   views.transacoes_lista,  name='transacoes_lista'),
]
