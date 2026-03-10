from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse

from .models import Investimento, Movimentacao, SaldoInvestimento
from .forms import InvestimentoForm, MovimentacaoForm, SaldoForm


def index(request):
    investimentos = Investimento.objects.select_related('instituicao', 'membro').order_by('membro', 'nome')
    return render(request, 'investimentos/index.html', {'investimentos': investimentos})


def investimento_criar(request):
    form = InvestimentoForm(request.POST or None)
    if form.is_valid():
        inv = form.save()
        messages.success(request, f'Investimento "{inv.nome}" criado com sucesso.')
        return redirect(reverse('investimentos:detalhe', args=[inv.pk]))
    return render(request, 'investimentos/investimento_form.html', {
        'form': form,
        'titulo': 'Novo Investimento',
    })


def investimento_editar(request, pk):
    investimento = get_object_or_404(Investimento, pk=pk)
    form = InvestimentoForm(request.POST or None, instance=investimento)
    if form.is_valid():
        form.save()
        messages.success(request, f'Investimento "{investimento.nome}" atualizado.')
        return redirect(reverse('investimentos:detalhe', args=[pk]))
    return render(request, 'investimentos/investimento_form.html', {
        'form': form,
        'titulo': f'Editar — {investimento.nome}',
        'investimento': investimento,
    })


def investimento_detalhe(request, pk):
    import json
    from datetime import date

    investimento = get_object_or_404(
        Investimento.objects.select_related('instituicao', 'membro'), pk=pk
    )

    ano_min = date.today().year - 2  # últimos 3 anos
    saldos = (
        investimento.saldos
        .filter(data__year__gte=ano_min)
        .order_by('data')
    )

    # Estrutura para tabela: {ano: {mes: saldo}}
    from collections import defaultdict
    tabela = defaultdict(dict)
    for s in saldos:
        tabela[s.data.year][s.data.month] = s.saldo

    anos = sorted(tabela.keys(), reverse=True)
    meses = list(range(1, 13))

    # Dados para o gráfico (ordem cronológica)
    chart_labels = [s.data.strftime('%b/%Y') for s in saldos]
    chart_data   = [float(s.saldo) for s in saldos]

    return render(request, 'investimentos/detalhe.html', {
        'investimento': investimento,
        'saldos': saldos,
        'tabela': dict(tabela),
        'anos': anos,
        'meses': meses,
        'chart_labels': json.dumps(chart_labels),
        'chart_data':   json.dumps(chart_data),
    })


def movimentacao_criar(request, pk):
    investimento = get_object_or_404(Investimento, pk=pk)
    form = MovimentacaoForm(request.POST or None)
    if form.is_valid():
        mov = form.save(commit=False)
        mov.investimento = investimento
        mov.save()
        messages.success(request, 'Movimentação registrada com sucesso.')
        return redirect(reverse('investimentos:detalhe', args=[pk]))
    return render(request, 'investimentos/movimentacao_form.html', {
        'form': form,
        'investimento': investimento,
        'titulo': f'Nova Movimentação — {investimento.nome}',
    })


def saldo_registrar(request, pk):
    investimento = get_object_or_404(Investimento, pk=pk)
    form = SaldoForm(request.POST or None)
    if form.is_valid():
        data = form.cleaned_data['data']
        saldo_valor = form.cleaned_data['saldo']
        SaldoInvestimento.objects.update_or_create(
            investimento=investimento,
            data=data,
            defaults={'saldo': saldo_valor},
        )
        messages.success(request, 'Saldo registrado com sucesso.')
        return redirect(reverse('investimentos:detalhe', args=[pk]))
    return render(request, 'investimentos/saldo_form.html', {
        'form': form,
        'investimento': investimento,
        'titulo': f'Registrar Saldo — {investimento.nome}',
    })
