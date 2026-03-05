from django import forms
from .models import Membro, InstituicaoFinanceira, Categoria


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
        fields = ["nome", "adulto", "ordem"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
            "adulto": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "ordem": forms.NumberInput(attrs={"class": "form-control"}),
        }
        labels = {
            "nome": "Nome",
            "adulto": "Adulto",
            "ordem": "Ordem",
        }

class MacroCategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nome"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "autofocus": True, "placeholder": "Nome da Categoria"}),  
        }
        labels = {"nome": "Nome"}

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.nivel = 1
        obj.categoria_pai = None
        if commit:
            obj.save()
        return obj


class SubCategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nome", "categoria_pai"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome da Subcategoria"}),
            "categoria_pai": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "nome": "Nome",
            "categoria_pai": "Categoria",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria_pai"].queryset = Categoria.objects.filter(nivel=1).order_by("nome")
        self.fields["categoria_pai"].empty_label = "--- Selecione a Categoria ---"
        self.fields["categoria_pai"].required = True

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.nivel = 2
        if commit:
            obj.save()
        return obj