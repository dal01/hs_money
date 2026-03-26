from django.contrib import admin

from hs_money.planejamento.models import AjusteCartaoMes, LancamentoPlanejado


@admin.register(LancamentoPlanejado)
class LancamentoPlanejadoAdmin(admin.ModelAdmin):
    list_display = ['descricao', 'tipo', 'valor', 'data', 'dia_do_mes', 'membro', 'ativo']
    list_filter = ['tipo', 'ativo', 'membro']
    search_fields = ['descricao']


@admin.register(AjusteCartaoMes)
class AjusteCartaoMesAdmin(admin.ModelAdmin):
    list_display = ['mes', 'descricao', 'valor', 'criado_em']
