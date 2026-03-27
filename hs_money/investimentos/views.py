import calendar
from datetime import date
from decimal import Decimal
from collections import defaultdict

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.urls import reverse

from .models import Investimento, Movimentacao, SaldoInvestimento
from .forms import InvestimentoForm, MovimentacaoForm, SaldoForm


def _meses_no_periodo(inicio: date, fim: date):
    """Retorna lista de (date_inicio, date_fim, label) entre inicio e fim."""
    meses = []
    y, m = inicio.year, inicio.month
    while (y, m) <= (fim.year, fim.month):
        ultimo_dia = calendar.monthrange(y, m)[1]
        meses.append((date(y, m, 1), date(y, m, ultimo_dia), f'{m:02d}/{y}'))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return meses


def _parse_periodo(request, selected_ids):
    """
    Lê os parâmetros GET 'inicio' e 'fim' (YYYY-MM-DD).
    Retorna (inicio, fim) como date. Se inválidos usa últimos 12 meses.
    """
    today = date.today()
    atalho = request.GET.get('atalho', '')

    if atalho == 'ano_atual':
        inicio = date(today.year, 1, 1)
        fim = date(today.year, 12, 31)
    elif atalho == 'ano_anterior':
        inicio = date(today.year - 1, 1, 1)
        fim = date(today.year - 1, 12, 31)
    elif atalho == 'historico':
        from .models import SaldoInvestimento
        primeiro = SaldoInvestimento.objects.filter(
            investimento_id__in=selected_ids,
            saldo__gt=0
        ).order_by('data').first()
        
        if primeiro:
            inicio = primeiro.data.replace(day=1)
        else:
            inicio = date(today.year, 1, 1)
        fim = today
    else:
        # Tenta ler params manuais; cai no default de 12 meses
        try:
            inicio = date.fromisoformat(request.GET['inicio'])
        except (KeyError, ValueError):
            inicio = None
        try:
            fim = date.fromisoformat(request.GET['fim'])
        except (KeyError, ValueError):
            fim = None

        if not inicio or not fim or inicio > fim:
            # default: últimos 12 meses
            total = today.year * 12 + today.month - 1 - 11
            y_i, m_i = divmod(total, 12)
            m_i += 1
            inicio = date(y_i, m_i, 1)
            fim = today
            atalho = 'ultimos12'

    return inicio, fim, atalho


def index(request):
    investimentos = list(Investimento.objects.select_related('instituicao', 'membro').order_by('membro', 'nome'))

    # Filtro: quais investimentos incluir nos totais
    if 'filtrado' in request.GET:
        selected_ids = [int(i) for i in request.GET.getlist('inv') if i.isdigit()]
    elif request.GET.getlist('inv'):
        selected_ids = [int(i) for i in request.GET.getlist('inv') if i.isdigit()]
    else:
        selected_ids = [inv.pk for inv in investimentos]

    inicio, fim, atalho = _parse_periodo(request, selected_ids)
    meses = _meses_no_periodo(inicio, fim)
    data_limite = meses[-1][1] if meses else fim

    all_saldos = list(
        SaldoInvestimento.objects
        .filter(data__lte=data_limite, investimento_id__in=selected_ids)
        .order_by('investimento_id', 'data')
        .values('investimento_id', 'data', 'saldo')
    )

    inv_saldos = defaultdict(list)
    for s in all_saldos:
        inv_saldos[s['investimento_id']].append((s['data'], s['saldo']))

    # Mapeia id do investimento para tipo_financeiro
    tipo_map = {inv.pk: inv.tipo_financeiro for inv in investimentos}

    monthly_totals = []
    for primeiro, ultimo, label in meses:
        total = Decimal('0')
        for inv_id, saldo_list in inv_saldos.items():
            best = None
            for d, v in saldo_list:
                if d <= ultimo:
                    best = v
            if best is not None:
                sinal = 1 if tipo_map.get(inv_id) == 'CREDITO' else -1
                total += sinal * best
        monthly_totals.append({'label': label, 'total': total})

    return render(request, 'investimentos/index.html', {
        'investimentos': investimentos,
        'monthly_totals': monthly_totals,
        'selected_ids': selected_ids,
        'periodo_inicio': inicio.isoformat(),
        'periodo_fim': fim.isoformat(),
        'periodo_label': f'{inicio.strftime("%m/%Y")} → {fim.strftime("%m/%Y")}',
        'atalho': atalho,
    })



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

    # Estrutura para tabela: {ano: {mes: {'saldo': valor, 'pk': pk}}}
    from collections import defaultdict
    tabela = defaultdict(dict)
    for s in saldos:
        tabela[s.data.year][s.data.month] = {'saldo': s.saldo, 'pk': s.pk, 'data': s.data.isoformat()}

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


def saldo_editar(request, inv_pk, saldo_pk):
    investimento = get_object_or_404(Investimento, pk=inv_pk)
    saldo = get_object_or_404(SaldoInvestimento, pk=saldo_pk, investimento=investimento)
    form = SaldoForm(request.POST or None, instance=saldo)
    if form.is_valid():
        form.save()
        messages.success(request, 'Saldo atualizado com sucesso.')
        return redirect(reverse('investimentos:detalhe', args=[inv_pk]))
    return render(request, 'investimentos/saldo_form.html', {
        'form': form,
        'investimento': investimento,
        'titulo': f'Editar Saldo — {investimento.nome}',
    })


def saldo_excluir(request, inv_pk, saldo_pk):
    saldo = get_object_or_404(SaldoInvestimento, pk=saldo_pk, investimento_id=inv_pk)
    if request.method == 'POST':
        saldo.delete()
        messages.success(request, 'Saldo excluído.')
        return redirect(reverse('investimentos:detalhe', args=[inv_pk]))
    return render(request, 'investimentos/saldo_confirmar_excluir.html', {
        'saldo': saldo,
        'investimento': saldo.investimento,
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
