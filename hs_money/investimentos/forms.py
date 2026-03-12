from django import forms
from .models import Investimento, Movimentacao, SaldoInvestimento


class InvestimentoForm(forms.ModelForm):
    class Meta:
        model = Investimento
        fields = ['nome', 'tipo', 'tipo_financeiro', 'instituicao', 'membro', 'ativo']
        widgets = {
            'nome':        forms.TextInput(attrs={'class': 'form-control'}),
            'tipo':        forms.Select(attrs={'class': 'form-select'}),
            'tipo_financeiro': forms.RadioSelect(attrs={'class': 'form-check-input', 'style': 'margin-right: 8px; display: inline-block;'}),
            'instituicao': forms.Select(attrs={'class': 'form-select'}),
            'membro':      forms.Select(attrs={'class': 'form-select'}),
            'ativo':       forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class MovimentacaoForm(forms.ModelForm):
    class Meta:
        model = Movimentacao
        fields = ['data', 'tipo', 'valor', 'descricao', 'anotacao']
        widgets = {
            'data':      forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'tipo':      forms.Select(attrs={'class': 'form-select'}),
            'valor':     forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'descricao': forms.TextInput(attrs={'class': 'form-control'}),
            'anotacao':  forms.TextInput(attrs={'class': 'form-control'}),
        }


class SaldoForm(forms.ModelForm):
    class Meta:
        model = SaldoInvestimento
        fields = ['data', 'saldo']
        widgets = {
            'data':  forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'saldo': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }
