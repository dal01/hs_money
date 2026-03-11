from django.urls import path
from . import views

app_name = 'investimentos'

urlpatterns = [
    path('',                                   views.index,                name='index'),
    path('novo/',                              views.investimento_criar,   name='investimento_criar'),
    path('<int:pk>/',                          views.investimento_detalhe, name='detalhe'),
    path('<int:pk>/editar/',                   views.investimento_editar,  name='investimento_editar'),
    path('<int:pk>/movimentacao/nova/',        views.movimentacao_criar,   name='movimentacao_criar'),
    path('<int:pk>/saldo/',                              views.saldo_registrar, name='saldo_registrar'),
    path('<int:inv_pk>/saldo/<int:saldo_pk>/editar/',  views.saldo_editar,     name='saldo_editar'),
    path('<int:inv_pk>/saldo/<int:saldo_pk>/excluir/', views.saldo_excluir,    name='saldo_excluir'),
]
