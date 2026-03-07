from __future__ import annotations

from django import forms
from .models import Transacao

class TransacaoManualForm(forms.ModelForm):
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