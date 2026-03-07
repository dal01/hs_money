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
    path('extratos/',                     views.listar_extratos_disco,   name='listar_extratos'),
    path('extratos/excluir/',             views.excluir_extratos_disco,  name='excluir_extratos'),
    # Transações
    path('contas/<int:pk>/transacoes/',   views.transacoes_conta,  name='transacoes_conta'),
    path('transacoes/',                         views.transacoes_lista,         name='transacoes_lista'),
    path('transacoes/nova/',                    views.transacao_criar,           name='transacao_criar'),
    path('transacoes/<int:pk>/editar/',         views.transacao_editar,          name='transacao_editar'),
    path('transacoes/<int:pk>/ocultar/',          views.transacao_toggle_oculta,  name='transacao_toggle_oculta'),
    path('transacoes/bulk/',                      views.transacoes_bulk_action,   name='transacoes_bulk_action'),
        path('transacoes/<int:pk>/anotacao/',        views.transacao_anotacao,       name='transacao_anotacao'),
]
