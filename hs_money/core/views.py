from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import Membro, InstituicaoFinanceira, Categoria
from .forms import MembroForm, InstituicaoFinanceiraForm, MacroCategoriaForm, SubCategoriaForm


def index(request):
    return redirect('core:membro_lista')


# ---- Membros ----

def membro_lista(request):
    membros = Membro.objects.all()
    return render(request, 'core/membros/lista.html', {'membros': membros})


def membro_criar(request):
    form = MembroForm(request.POST or None)
    if form.is_valid():
        membro = form.save()
        messages.success(request, f'Membro "{membro.nome}" criado com sucesso.')
        return redirect('core:membro_lista')
    return render(request, 'core/membros/form.html', {'form': form, 'titulo': 'Novo Membro'})


def membro_editar(request, pk):
    membro = get_object_or_404(Membro, pk=pk)
    form = MembroForm(request.POST or None, instance=membro)
    if form.is_valid():
        form.save()
        messages.success(request, f'Membro "{membro.nome}" atualizado.')
        return redirect('core:membro_lista')
    return render(request, 'core/membros/form.html', {'form': form, 'titulo': f'Editar — {membro.nome}', 'membro': membro})


def membro_excluir(request, pk):
    membro = get_object_or_404(Membro, pk=pk)
    if request.method == 'POST':
        nome = membro.nome
        membro.delete()
        messages.success(request, f'Membro "{nome}" excluído.')
        return redirect('core:membro_lista')
    return render(request, 'core/membros/confirmar_exclusao.html', {'membro': membro})


# ---- Instituições Financeiras ----

def instituicao_lista(request):
    instituicoes = InstituicaoFinanceira.objects.order_by('nome')
    return render(request, 'core/instituicoes/lista.html', {'instituicoes': instituicoes})


def instituicao_criar(request):
    form = InstituicaoFinanceiraForm(request.POST or None)
    if form.is_valid():
        inst = form.save()
        messages.success(request, f'Instituição "{inst.nome}" criada com sucesso.')
        return redirect('core:instituicao_lista')
    return render(request, 'core/instituicoes/form.html', {'form': form, 'titulo': 'Nova Instituição Financeira'})


def instituicao_editar(request, pk):
    inst = get_object_or_404(InstituicaoFinanceira, pk=pk)
    form = InstituicaoFinanceiraForm(request.POST or None, instance=inst)
    if form.is_valid():
        form.save()
        messages.success(request, f'Instituição "{inst.nome}" atualizada.')
        return redirect('core:instituicao_lista')
    return render(request, 'core/instituicoes/form.html', {'form': form, 'titulo': f'Editar — {inst.nome}', 'inst': inst})


def instituicao_excluir(request, pk):
    inst = get_object_or_404(InstituicaoFinanceira, pk=pk)
    if request.method == 'POST':
        nome = inst.nome
        inst.delete()
        messages.success(request, f'Instituição "{nome}" excluída.')
        return redirect('core:instituicao_lista')
    return render(request, 'core/instituicoes/confirmar_exclusao.html', {'inst': inst})


# ---- Categorias ----

def categoria_lista(request):
    macros = (
        Categoria.objects
        .filter(nivel=1)
        .prefetch_related('subcategorias')
        .order_by('nome')
    )
    macro_form = MacroCategoriaForm()
    sub_form = SubCategoriaForm()
    return render(request, 'core/categorias/lista.html', {
        'macros': macros,
        'macro_form': macro_form,
        'sub_form': sub_form,
    })


def categoria_criar_macro(request):
    if request.method == 'POST':
        form = MacroCategoriaForm(request.POST)
        if form.is_valid():
            cat = form.save()
            messages.success(request, f'Categoria "{cat.nome}" criada com sucesso.')
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
    return redirect('core:categoria_lista')


def categoria_criar_sub(request):
    if request.method == 'POST':
        form = SubCategoriaForm(request.POST)
        if form.is_valid():
            cat = form.save()
            messages.success(request, f'Subcategoria "{cat.nome}" criada em "{cat.categoria_pai}".') 
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
    return redirect('core:categoria_lista')


def categoria_editar(request, pk):
    cat = get_object_or_404(Categoria, pk=pk)
    form_class = MacroCategoriaForm if cat.nivel == 1 else SubCategoriaForm
    form = form_class(request.POST or None, instance=cat)
    if form.is_valid():
        form.save()
        messages.success(request, f'Categoria "{cat.nome}" atualizada.')
        return redirect('core:categoria_lista')
    return render(request, 'core/categorias/form.html', {
        'form': form,
        'categoria': cat,
        'titulo': f'Editar — {cat}',
    })


def categoria_excluir(request, pk):
    cat = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        nome = str(cat)
        cat.delete()
        messages.success(request, f'Categoria "{nome}" excluída.')
        return redirect('core:categoria_lista')
    return render(request, 'core/categorias/confirmar_exclusao.html', {'categoria': cat})
