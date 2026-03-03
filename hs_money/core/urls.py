from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.index, name='index'),

    # Membros
    path('membros/',                     views.membro_lista,       name='membro_lista'),
    path('membros/novo/',                views.membro_criar,       name='membro_criar'),
    path('membros/<int:pk>/editar/',     views.membro_editar,      name='membro_editar'),
    path('membros/<int:pk>/excluir/',    views.membro_excluir,     name='membro_excluir'),

    # Instituições Financeiras
    path('instituicoes/',                views.instituicao_lista,  name='instituicao_lista'),
    path('instituicoes/nova/',           views.instituicao_criar,  name='instituicao_criar'),
    path('instituicoes/<int:pk>/editar/',  views.instituicao_editar, name='instituicao_editar'),
    path('instituicoes/<int:pk>/excluir/', views.instituicao_excluir, name='instituicao_excluir'),
]
