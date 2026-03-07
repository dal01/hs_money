from __future__ import annotations

import re
from django.db.models import Q
from django import forms
from .models import Transacao

def normalize_descricao(descricao: str) -> str:
    # Remove números e caracteres especiais, deixa só letras e espaços
    return re.sub(r'[^a-zA-Z\s]', '', descricao).strip().lower()

class TransacaoManualForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sugestão automática de anotação
        descricao = self.initial.get('descricao') or self.data.get('descricao') or (self.instance.descricao if self.instance else None)
        if descricao:
            desc_norm = normalize_descricao(descricao)
            anotacao_sugerida = (
                Transacao.objects
                .filter(anotacao__isnull=False)
                .exclude(anotacao='')
                .filter(descricao__isnull=False)
                .filter(descricao__iregex=re.escape(desc_norm))
                .values_list('anotacao', flat=True)
                .first()
            )
            if anotacao_sugerida and not (self.initial.get('anotacao') or self.data.get('anotacao')):
                self.fields['anotacao'].initial = anotacao_sugerida

    class Meta:
        model = Transacao
        fields = [
            'extrato', 'data', 'tipo', 'descricao', 'valor', 'categoria', 'membros', 'anotacao'
        ]
        widgets = {
            'extrato': forms.Select(attrs={'class': 'form-select'}),
            'data': forms.DateInput(attrs={'type': 'date'}),
            'descricao': forms.TextInput(attrs={'class': 'form-control'}),
            'valor': forms.NumberInput(attrs={'class': 'form-control'}),
            'anotacao': forms.TextInput(attrs={'class': 'form-control'}),
            'membros': forms.SelectMultiple(attrs={'class': 'form-select'}),
        }