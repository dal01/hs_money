from django.urls import path
from . import views

app_name = 'cartao_credito'

urlpatterns = [
    path('',            views.index,                    name='index'),

    # Cartões
    path('cartoes/',                        views.cartao_lista,           name='cartao_lista'),
    path('cartoes/novo/',                   views.cartao_criar,           name='cartao_criar'),
    path('cartoes/<int:pk>/editar/',        views.cartao_editar,          name='cartao_editar'),

    # Upload de fatura PDF
    path('upload/',                                views.upload_fatura,   name='upload_fatura'),
    path('cartoes/<int:cartao_pk>/upload/',        views.upload_fatura,   name='upload_por_cartao'),

    # Faturas no disco
    path('faturas/',    views.listar_faturas_disco,     name='listar_faturas'),
    path('processar/',  views.processar_faturas,        name='processar_faturas'),
    path('excluir/',    views.excluir_faturas_disco,    name='excluir_faturas'),
    path('normalizar/', views.normalizar_faturas_disco, name='normalizar_faturas'),

    # Transações
    path('transacoes/',                              views.transacoes_lista,          name='transacoes_lista'),
    path('parcelados/',                              views.parcelados,                name='parcelados'),
    path('transacoes/<int:pk>/ocultar/',             views.transacao_toggle_oculta,   name='transacao_toggle_oculta'),
    path('transacoes/bulk/',                         views.transacoes_bulk_action,    name='transacoes_bulk_action'),
    path('transacoes/<int:pk>/anotacao/',            views.transacao_anotacao,        name='transacao_anotacao'),
]
