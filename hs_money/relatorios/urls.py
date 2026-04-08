from django.urls import path
from . import views

app_name = 'relatorios'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('graficos/', views.graficos, name='graficos'),
    path('individual/', views.individual, name='individual'),
    path('membro-transacoes/', views.membro_transacoes_json, name='membro_transacoes_json'),
    path('categoria-transacoes/', views.categoria_transacoes_json, name='categoria_transacoes_json'),
    path('mes-transacoes/', views.mes_transacoes_json, name='mes_transacoes_json'),
]
