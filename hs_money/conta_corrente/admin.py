from django.contrib import admin
from .models import ContaCorrente, Extrato, Transacao


@admin.register(ContaCorrente)
class ContaCorrenteAdmin(admin.ModelAdmin):
    list_display = ('id', 'instituicao', 'membro', 'agencia', 'numero', 'ativa')
    list_filter = ('ativa', 'instituicao')
    search_fields = ('numero', 'membro__nome')


@admin.register(Extrato)
class ExtratoAdmin(admin.ModelAdmin):
    list_display = ('id', 'conta', 'data_inicio', 'data_fim', 'criado_em')
    list_filter = ('conta',)


@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = ('id', 'extrato', 'data', 'tipo', 'descricao', 'valor', 'categoria', 'oculta')
    list_filter = ('categoria', 'oculta')
    search_fields = ('tipo', 'descricao')
