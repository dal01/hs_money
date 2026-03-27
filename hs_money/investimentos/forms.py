from django import forms
from decimal import Decimal, InvalidOperation
from .models import Investimento, Movimentacao, SaldoInvestimento


class DecimalCommaField(forms.CharField):
    """Decimal field that accepts both '1.5' and '1,5'; displays without trailing zeros."""

    def to_python(self, value):
        value = super().to_python(value).strip()
        if not value:
            return None
        try:
            return Decimal(value.replace(',', '.'))
        except InvalidOperation:
            raise forms.ValidationError('Informe um número válido (ex: 1,5).')

    def prepare_value(self, value):
        if value in (None, ''):
            return ''
        if isinstance(value, Decimal):
            s = f'{value:f}'  # fixed-point notation, never scientific (e.g. 2800.00 not 2.8E+3)
            if '.' in s:
                s = s.rstrip('0').rstrip('.')
            return s.replace('.', ',')
        return str(value).replace('.', ',')


class InvestimentoForm(forms.ModelForm):
    projecao_percentual = DecimalCommaField(
        required=False,
        label='Variação mensal (%)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 1,5'}),
    )
    projecao_adicional = DecimalCommaField(
        required=False,
        label='Ajuste fixo mensal (R$)',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: -1000,00'}),
    )

    class Meta:
        model = Investimento
        fields = ['nome', 'tipo', 'tipo_financeiro', 'instituicao', 'membro', 'ativo',
                  'projecao_percentual', 'projecao_adicional']
        widgets = {
            'nome':            forms.TextInput(attrs={'class': 'form-control'}),
            'tipo':            forms.Select(attrs={'class': 'form-select'}),
            'tipo_financeiro': forms.RadioSelect(attrs={'class': 'form-check-input', 'style': 'margin-right: 8px; display: inline-block;'}),
            'instituicao':     forms.Select(attrs={'class': 'form-select'}),
            'membro':          forms.Select(attrs={'class': 'form-select'}),
            'ativo':           forms.CheckboxInput(attrs={'class': 'form-check-input'}),
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
