from django.contrib import admin
from .models import Membro


@admin.register(Membro)
class MembroAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'adulto')
