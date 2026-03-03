from django.contrib import admin
from .models import Cartao, FaturaCartao, Lancamento, RegraMembroCartao


@admin.register(Cartao)
class CartaoAdmin(admin.ModelAdmin):
    list_display = ('id', 'instituicao', 'bandeira', 'cartao_final', 'membro', 'ativo')
    list_filter = ('ativo', 'bandeira')
    search_fields = ('membro__nome', 'cartao_final')


@admin.register(FaturaCartao)
class FaturaCartaoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cartao', 'competencia', 'fechado_em', 'vencimento_em', 'total')
    list_filter = ('competencia',)


@admin.register(Lancamento)
class LancamentoAdmin(admin.ModelAdmin):
    list_display = ('id', 'fatura', 'data', 'descricao', 'valor', 'categoria', 'oculta')
    list_filter = ('oculta', 'categoria')
    search_fields = ('descricao',)


@admin.register(RegraMembroCartao)
class RegraMembroCartaoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'ativo', 'prioridade')
    list_filter = ('ativo',)
