from django.urls import path

from hs_money.planejamento import views

app_name = 'planejamento'

urlpatterns = [
    # Calendar / projection
    path('',                                 views.index,                  name='index'),

    # Lancamentos
    path('lancamentos/',                     views.lancamento_lista,       name='lancamento_lista'),
    path('lancamentos/novo/',                views.lancamento_criar,       name='lancamento_criar'),
    path('lancamentos/<int:pk>/editar/',     views.lancamento_editar,      name='lancamento_editar'),
    path('lancamentos/<int:pk>/excluir/',    views.lancamento_excluir,     name='lancamento_excluir'),
    path('lancamentos/<int:pk>/toggle/',     views.lancamento_toggle_ativo, name='lancamento_toggle_ativo'),

    # Suggestion tool
    path('sugerir/',                         views.sugerir_recorrentes,    name='sugerir'),

    # CC average adjustments
    path('ajustes-cartao/',                  views.ajuste_cartao_lista,    name='ajuste_cartao_lista'),
    path('ajustes-cartao/<int:pk>/excluir/', views.ajuste_cartao_excluir,  name='ajuste_cartao_excluir'),

    # Net-worth config
    path('patrimonio/',                      views.patrimonio_config,       name='patrimonio_config'),
]
