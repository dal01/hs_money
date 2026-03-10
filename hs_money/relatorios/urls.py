from django.urls import path
from . import views

app_name = 'relatorios'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('membro-transacoes/', views.membro_transacoes_json, name='membro_transacoes_json'),
]
