from django import forms
from .models import Membro, InstituicaoFinanceira


class InstituicaoFinanceiraForm(forms.ModelForm):
    class Meta:
        model = InstituicaoFinanceira
        fields = ["nome", "codigo", "tipo"]
        widgets = {
            "nome":   forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
            "codigo": forms.TextInput(attrs={"class": "form-control"}),
            "tipo":   forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "nome":   "Nome",
            "codigo": "Código (usado para importação OFX)",
            "tipo":   "Tipo",
        }


class MembroForm(forms.ModelForm):
    class Meta:
        model = Membro
        fields = ["nome", "adulto"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
            "adulto": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nome": "Nome",
            "adulto": "Adulto",
        }
