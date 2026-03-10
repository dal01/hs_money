from django.contrib import admin
from .models import Investimento, Movimentacao, SaldoInvestimento


@admin.register(Investimento)
class InvestimentoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'tipo', 'instituicao', 'membro', 'ativo')
    list_filter = ('tipo', 'ativo', 'instituicao', 'membro')
    search_fields = ('nome',)


@admin.register(Movimentacao)
class MovimentacaoAdmin(admin.ModelAdmin):
    list_display = ('id', 'investimento', 'data', 'tipo', 'valor', 'descricao')
    list_filter = ('tipo', 'investimento')
    search_fields = ('descricao', 'anotacao')
    date_hierarchy = 'data'


@admin.register(SaldoInvestimento)
class SaldoInvestimentoAdmin(admin.ModelAdmin):
    list_display = ('id', 'investimento', 'data', 'saldo')
    list_filter = ('investimento',)
    date_hierarchy = 'data'
