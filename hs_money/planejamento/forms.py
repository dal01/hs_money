from django import forms

from hs_money.planejamento.models import AjusteCartaoMes, LancamentoPlanejado

_WIDGET_CLASS = {'class': 'form-control'}
_SELECT_CLASS = {'class': 'form-select'}
_CHECK_CLASS  = {'class': 'form-check-input'}
_DATE_CLASS   = {'class': 'form-control', 'type': 'date'}

MES_CHOICES = [
    (1, 'Janeiro'), (2, 'Fevereiro'), (3, 'Março'), (4, 'Abril'),
    (5, 'Maio'), (6, 'Junho'), (7, 'Julho'), (8, 'Agosto'),
    (9, 'Setembro'), (10, 'Outubro'), (11, 'Novembro'), (12, 'Dezembro'),
]

DIA_SEMANA_CHOICES = [
    ('', '---'),
    (0, 'Segunda-feira'),
    (1, 'Terça-feira'),
    (2, 'Quarta-feira'),
    (3, 'Quinta-feira'),
    (4, 'Sexta-feira'),
    (5, 'Sábado'),
    (6, 'Domingo'),
]


class LancamentoPlanejadoForm(forms.ModelForm):
    mes_do_ano = forms.ChoiceField(
        label='Mês',
        choices=[('', '---')] + MES_CHOICES,
        required=False,
        widget=forms.Select(attrs=_SELECT_CLASS),
    )
    dia_da_semana = forms.ChoiceField(
        label='Dia da semana',
        choices=DIA_SEMANA_CHOICES,
        required=False,
        widget=forms.Select(attrs=_SELECT_CLASS),
    )

    class Meta:
        model = LancamentoPlanejado
        fields = [
            'descricao', 'valor', 'tipo',
            'data',
            'periodicidade', 'dia_do_mes', 'mes_do_ano', 'dia_da_semana', 'data_inicio', 'data_fim',
            'ativo',
        ]
        widgets = {
            'descricao':     forms.TextInput(attrs={**_WIDGET_CLASS, 'autofocus': True}),
            'valor':         forms.NumberInput(attrs={**_WIDGET_CLASS, 'step': '0.01'}),
            'tipo':          forms.Select(attrs=_SELECT_CLASS),
            'data':          forms.DateInput(attrs=_DATE_CLASS),
            'periodicidade': forms.Select(attrs=_SELECT_CLASS),
            'dia_do_mes':    forms.NumberInput(attrs={**_WIDGET_CLASS, 'min': 1, 'max': 28}),
            'data_inicio':   forms.DateInput(attrs=_DATE_CLASS),
            'data_fim':      forms.DateInput(attrs=_DATE_CLASS),
            'ativo':         forms.CheckboxInput(attrs=_CHECK_CLASS),
        }

    def clean_mes_do_ano(self):
        v = self.cleaned_data.get('mes_do_ano')
        if v == '' or v is None:
            return None
        return int(v)

    def clean_dia_da_semana(self):
        v = self.cleaned_data.get('dia_da_semana')
        if v == '' or v is None:
            return None
        return int(v)


class AjusteCartaoMesForm(forms.ModelForm):
    class Meta:
        model = AjusteCartaoMes
        fields = ['mes', 'valor', 'descricao']
        widgets = {
            'mes':       forms.DateInput(attrs=_DATE_CLASS),
            'valor':     forms.NumberInput(attrs={**_WIDGET_CLASS, 'step': '0.01', 'min': '0'}),
            'descricao': forms.TextInput(attrs=_WIDGET_CLASS),
        }
