"""
planejamento/views.py

Projection calendar + CRUD for planned entries + recurring-transaction suggestion tool.
"""
from __future__ import annotations

import calendar
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.template.loader import render_to_string
from django.http import JsonResponse

from hs_money.core.models import Categoria, Membro
from hs_money.planejamento.forms import AjusteCartaoMesForm, LancamentoPlanejadoForm
from hs_money.planejamento.models import AjusteCartaoMes, LancamentoPlanejado, PatrimonioInvestimento

ZERO = Decimal('0')

MESES_NOME = {
    1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
    5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
    9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _meses_atras(ref: date, n: int) -> date:
    """Return the 1st day of the month n months before ref."""
    month = ref.month - n
    year = ref.year
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _proximo_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _saldo_cc(membro_id=None) -> Decimal:
    """Sum of all visible conta_corrente transactions up to today."""
    from hs_money.conta_corrente.models import Transacao as TCC
    ids_fatura = list(
        Categoria.objects.filter(nome__icontains='fatura do cart')
        .values_list('pk', flat=True)
    )
    qs = TCC.objects.filter(oculta=False, data__lte=date.today()).exclude(
        categoria_id__in=ids_fatura
    )
    if membro_id:
        qs = qs.filter(extrato__conta__membro_id=membro_id)
    return qs.aggregate(t=Sum('valor'))['t'] or ZERO


def _saldo_investimentos_selecionados(membro_id=None) -> tuple[Decimal, list]:
    """
    Returns (total, list-of-dicts) for all investments marked in PatrimonioInvestimento.
    Uses the most recent SaldoInvestimento snapshot for each investment.
    tipo_financeiro='DEBITO' investments are subtracted (they are liabilities).
    """
    from hs_money.investimentos.models import SaldoInvestimento
    selecionados = (
        PatrimonioInvestimento.objects
        .select_related('investimento', 'investimento__membro')
        .all()
    )
    if membro_id:
        selecionados = selecionados.filter(
            Q(investimento__membro__isnull=True) |
            Q(investimento__membro_id=membro_id)
        )

    itens = []
    total = ZERO
    for pi in selecionados:
        inv = pi.investimento
        ultimo = (
            SaldoInvestimento.objects
            .filter(investimento=inv)
            .order_by('-data')
            .first()
        )
        saldo = ultimo.saldo if ultimo else ZERO
        if inv.tipo_financeiro == 'DEBITO':
            saldo = -abs(saldo)
        total += saldo
        itens.append({
            'nome': str(inv),
            'saldo': saldo,
            'data_ref': ultimo.data if ultimo else None,
            'projecao_percentual': inv.projecao_percentual,
            'projecao_adicional': inv.projecao_adicional,
            'tipo_financeiro': inv.tipo_financeiro,
        })
    return total, itens


def _patrimonio_liquido(membro_id=None) -> tuple[Decimal, list]:
    """Returns (total_patrimonio, investimentos_itens). CC balance is NOT included."""
    saldo_inv, itens = _saldo_investimentos_selecionados(membro_id)
    return saldo_inv, itens


def _media_mensal_cartao(membro_id=None) -> Decimal:
    """
    Mean of monthly CC *spending* over the last 3 complete months.
    Adjustments (AjusteCartaoMes) reduce the monthly total before averaging.
    Returns a positive Decimal representing average monthly spend.
    """
    from hs_money.cartao_credito.models import Transacao as TCC

    today = date.today()
    inicio = _meses_atras(today, 3)
    fim_excl = today.replace(day=1)       # exclude current (incomplete) month

    qs = TCC.objects.filter(
        oculta=False,
        valor__lt=0,
        fatura__competencia__gte=inicio,
        fatura__competencia__lt=fim_excl,
    )
    if membro_id:
        qs = qs.filter(fatura__cartao__membro_id=membro_id)

    # Aggregate by month
    monthly: dict[tuple, Decimal] = defaultdict(ZERO.__class__)
    for t in qs.select_related('fatura'):
        key = (t.fatura.competencia.year, t.fatura.competencia.month)
        monthly[key] += abs(t.valor)

    # Apply adjustments
    ajustes = AjusteCartaoMes.objects.filter(mes__gte=inicio, mes__lt=fim_excl)
    for aj in ajustes:
        key = (aj.mes.year, aj.mes.month)
        if key in monthly:
            monthly[key] = max(ZERO, monthly[key] - aj.valor)

    if not monthly:
        return ZERO
    return sum(monthly.values(), ZERO) / len(monthly)


# ---------------------------------------------------------------------------
# Calendar / projection view
# ---------------------------------------------------------------------------

def index(request):
    today = date.today()
    membro_id = request.GET.get('membro') or None
    if membro_id:
        try:
            membro_id = int(membro_id)
        except ValueError:
            membro_id = None

    membros = Membro.objects.all()
    patrimonio, inv_itens = _patrimonio_liquido(membro_id)
    media_cartao = _media_mensal_cartao(membro_id)

    lancamentos = list(
        LancamentoPlanejado.objects.filter(ativo=True)
        .select_related('categoria', 'membro')
    )
    if membro_id:
        lancamentos = [
            l for l in lancamentos
            if l.membro_id is None or l.membro_id == membro_id
        ]

    meses = []
    saldo_acumulado = patrimonio

    # Running projected saldo per investment (for those with projection rules)
    saldos_proj = {
        item['nome']: item['saldo']
        for item in inv_itens
        if item['projecao_percentual'] is not None or item['projecao_adicional'] is not None
    }

    for i in range(72):
        total_offset = (today.month - 1 + i)
        mes_num = total_offset % 12 + 1
        ano = today.year + total_offset // 12

        primeiro_dia = date(ano, mes_num, 1)
        ultimo_dia = date(ano, mes_num, calendar.monthrange(ano, mes_num)[1])
        e_passado = primo = date(ano, mes_num, 1) < today.replace(day=1)
        e_atual = (ano == today.year and mes_num == today.month)

        # Gather occurrences from planned entries
        ocorrencias = []
        for l in lancamentos:
            for d, v in l.ocorrencias_no_periodo(primeiro_dia, ultimo_dia):
                ocorrencias.append({
                    'data': d,
                    'descricao': l.descricao,
                    'valor': v,
                    'pk': l.pk,
                    'categoria': l.categoria,
                    'membro': l.membro,
                    'e_creditо': v > ZERO,
                })
        ocorrencias.sort(key=lambda x: x['data'])

        creditos = sum(o['valor'] for o in ocorrencias if o['valor'] > ZERO)
        debitos  = sum(o['valor'] for o in ocorrencias if o['valor'] < ZERO)
        # CC projection: negative (spending)
        total_cartao = -(media_cartao)

        # Investment projection: advance each investment's running saldo by one month
        crescimento_inv = ZERO
        crescimento_inv_detail = []
        for item in inv_itens:
            nome = item['nome']
            if nome not in saldos_proj:
                continue
            s = saldos_proj[nome]
            pct = item['projecao_percentual'] or ZERO
            adic = item['projecao_adicional'] or ZERO
            s_novo = s * (1 + pct / 100) + adic
            # For DEBITO investments (saldo is negative): clamp to 0 when fully paid off
            if item['tipo_financeiro'] == 'DEBITO' and s_novo >= ZERO:
                s_novo = ZERO
            rendimento = s_novo - s
            crescimento_inv += rendimento
            saldos_proj[nome] = s_novo
            crescimento_inv_detail.append({
                'nome': nome,
                'pct': float(pct),
                'adic': float(adic),
                'saldo_antes': float(s),
                'saldo_depois': float(s_novo),
                'rendimento': float(rendimento),
            })

        # debitos is a negative value (sum of negative transactions); include cartão
        debitos_total = debitos + total_cartao
        # parcial: créditos menos débitos (considera cartão) -> creditos + debitos_total
        parcial = creditos + debitos_total

        total_mes = parcial + crescimento_inv
        saldo_acumulado += total_mes

        ocorrencias_json = json.dumps(
            [{'data': o['data'].strftime('%d/%m'), 'descricao': o['descricao'], 'valor': float(o['valor'])} for o in ocorrencias],
            ensure_ascii=False,
        )

        meses.append({
            'ano': ano,
            'mes': mes_num,
            'mes_nome': MESES_NOME[mes_num],
            'e_passado': e_passado,
            'e_atual': e_atual,
            'ocorrencias': ocorrencias,
            'ocorrencias_json': ocorrencias_json,
            'creditos': creditos,
            'debitos': debitos_total,
            'total_cartao': total_cartao,
            'parcial': parcial,
            'crescimento_inv': crescimento_inv,
            'crescimento_inv_json': json.dumps(crescimento_inv_detail, ensure_ascii=False),
            'investimentos': crescimento_inv,
            'total_mes': total_mes,
            'saldo_final': saldo_acumulado,
        })

    # Build annual projection tables for the 5 next full calendar years
    anos_proj = []
    target_year = today.year + 1
    for yr in range(target_year, target_year + 5):
        yr_meses = [m for m in meses if m['ano'] == yr]
        if yr_meses:
            anos_proj.append({
                'ano': yr,
                'meses': yr_meses,
                'total_debitos': sum(m['debitos'] for m in yr_meses),
                'total_creditos': sum(m['creditos'] for m in yr_meses),
                'total_parcial': sum(m['parcial'] for m in yr_meses),
                'total_investimentos': sum(m['crescimento_inv'] for m in yr_meses),
                'total_saldo': sum(m['total_mes'] for m in yr_meses),
                # Patrimônio líquido ao final do ano (saldo acumulado no último mês do ano)
                'total_patrimonio': yr_meses[-1]['saldo_final'],
            })

    meses = meses[:12]

    # Current year remaining months table
    ano_atual_meses = [m for m in meses if m['ano'] == today.year]
    ano_atual = {
        'ano': today.year,
        'meses': ano_atual_meses,
        'total_debitos': sum(m['debitos'] for m in ano_atual_meses),
        'total_creditos': sum(m['creditos'] for m in ano_atual_meses),
        'total_parcial': sum(m['parcial'] for m in ano_atual_meses),
        'total_investimentos': sum(m['crescimento_inv'] for m in ano_atual_meses),
        'total_saldo': sum(m['total_mes'] for m in ano_atual_meses),
        # Patrimônio ao final do período exibido (último mês disponível) — fallback para patrimônio inicial
        'total_patrimonio': (ano_atual_meses[-1]['saldo_final'] if ano_atual_meses else patrimonio),
    }

    return render(request, 'planejamento/index.html', {
        'meses': meses,
        'anos_proj': anos_proj,
        'ano_atual': ano_atual,
        'patrimonio': patrimonio,
        'inv_itens': inv_itens,
        'media_cartao': media_cartao,
        'membros': membros,
        'membro_id': membro_id,
        'today': today,
    })


# ---------------------------------------------------------------------------
# Lancamento CRUD
# ---------------------------------------------------------------------------

def lancamento_lista(request):
    VALID_ORDERS = {'descricao', 'valor', 'dia'}
    order = request.GET.get('order', 'descricao')
    direction = request.GET.get('dir', 'asc')
    if order not in VALID_ORDERS:
        order = 'descricao'
    if direction not in ('asc', 'desc'):
        direction = 'asc'

    p = '-' if direction == 'desc' else ''
    if order == 'valor':
        sort_fields = [f'{p}valor']
    elif order == 'dia':
        sort_fields = [f'{p}dia_do_mes', f'{p}data']
    else:  # descricao (default)
        sort_fields = [f'{p}descricao']

    lancamentos_qs = (
        LancamentoPlanejado.objects
        .select_related('categoria', 'membro')
        .order_by('-ativo', 'tipo', *sort_fields)
    )

    lancamentos = list(lancamentos_qs)

    # Separate pontual and recorrente entries for clearer presentation
    pontual_list = [l for l in lancamentos if l.tipo == LancamentoPlanejado.TIPO_PONTUAL]
    recorrente_list = [l for l in lancamentos if l.tipo == LancamentoPlanejado.TIPO_RECORRENTE]

    periods = [
        (LancamentoPlanejado.PERIOD_ANUAL, 'Anual'),
        (LancamentoPlanejado.PERIOD_MENSAL, 'Mensal'),
        (LancamentoPlanejado.PERIOD_SEMANAL, 'Semanal'),
    ]

    rec_periods = []
    for key, label in periods:
        creditos = [l for l in recorrente_list if l.periodicidade == key and l.valor > ZERO]
        debitos = [l for l in recorrente_list if l.periodicidade == key and l.valor < ZERO]
        rec_periods.append({
            'key': key, 'label': label,
            'creditos': creditos, 'debitos': debitos,
            'total_creditos': sum((l.valor for l in creditos), ZERO),
            'total_debitos': sum((l.valor for l in debitos), ZERO),
        })

    return render(request, 'planejamento/lancamento_lista.html', {
        'lancamentos': lancamentos,
        'pontual_list': pontual_list,
        'rec_periods': rec_periods,
        'order': order,
        'dir': direction,
    })


def lancamento_criar(request):
    form = LancamentoPlanejadoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Lançamento salvo com sucesso.')
        return redirect('planejamento:lancamento_lista')
    return render(request, 'planejamento/lancamento_form.html', {
        'form': form,
        'titulo': 'Novo Lançamento',
    })


def lancamento_editar(request, pk):
    lancamento = get_object_or_404(LancamentoPlanejado, pk=pk)
    form = LancamentoPlanejadoForm(request.POST or None, instance=lancamento)
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, 'Lançamento atualizado.')
            if is_ajax:
                return JsonResponse({'ok': True})
            return redirect('planejamento:lancamento_lista')
        else:
            if is_ajax:
                # return rendered form fragment (with errors)
                html = render_to_string('planejamento/_lancamento_form_fragment.html', {'form': form, 'lancamento': lancamento}, request=request)
                return JsonResponse({'ok': False, 'html': html}, status=400)

    if is_ajax:
        # return only the form fragment for modal
        html = render_to_string('planejamento/_lancamento_form_fragment.html', {'form': form, 'lancamento': lancamento}, request=request)
        return JsonResponse({'html': html})

    return render(request, 'planejamento/lancamento_form.html', {
        'form': form,
        'lancamento': lancamento,
        'titulo': f'Editar: {lancamento.descricao}',
    })


@require_POST
def lancamento_excluir(request, pk):
    lancamento = get_object_or_404(LancamentoPlanejado, pk=pk)
    lancamento.delete()
    messages.success(request, 'Lançamento excluído.')
    return redirect('planejamento:lancamento_lista')


@require_POST
def lancamento_toggle_ativo(request, pk):
    lancamento = get_object_or_404(LancamentoPlanejado, pk=pk)
    lancamento.ativo = not lancamento.ativo
    lancamento.save(update_fields=['ativo'])
    return redirect(request.POST.get('next') or 'planejamento:lancamento_lista')


# ---------------------------------------------------------------------------
# Recurring-transaction suggestion from conta_corrente history
# ---------------------------------------------------------------------------

_NOISE = re.compile(
    r'\b(\d{2}/\d{2}(?:/\d{2,4})?|\d{4,}|parc\s*\d+/\d+|parcela\s*\d+)\b',
    re.IGNORECASE,
)


def _normalizar(descricao: str) -> str:
    """Strip variable parts (dates, codes) for grouping similar descriptions."""
    s = _NOISE.sub('', descricao)
    s = re.sub(r'\s{2,}', ' ', s).strip().upper()
    return s


def sugerir_recorrentes(request):
    """
    Analyse the last 12 months of conta_corrente transactions and suggest
    recurring payments (same normalised description, appearing in ≥3 months).
    POST with selected suggestions to create LancamentoPlanejado entries.
    """
    from hs_money.conta_corrente.models import Transacao as TCC
    from statistics import mean, stdev

    today = date.today()
    inicio = _meses_atras(today, 12)

    ids_fatura = list(
        Categoria.objects.filter(nome__icontains='fatura do cart')
        .values_list('pk', flat=True)
    )

    qs = (
        TCC.objects
        .filter(oculta=False, data__gte=inicio)
        .exclude(categoria_id__in=ids_fatura)
        .select_related('extrato__conta__membro', 'categoria')
        .order_by('data')
    )

    # Group by normalised description
    groups: dict[str, list] = defaultdict(list)
    for t in qs:
        key = _normalizar(t.descricao)
        if key:
            groups[key].append(t)

    candidates = []
    for key, txs in groups.items():
        # Must appear in at least 3 distinct months
        months = {(t.data.year, t.data.month) for t in txs}
        if len(months) < 3:
            continue

        values = [float(t.valor) for t in txs]
        avg = mean(values)
        sd = stdev(values) if len(values) > 1 else 0
        cv = abs(sd / avg) if avg else 1  # coefficient of variation

        # Skip if too variable  (cv > 0.3 = >30% variation)
        if cv > 0.3:
            continue

        # Infer probable day-of-month
        days = sorted({t.data.day for t in txs})
        dia_modal = max(set(days), key=days.count)
        dia_modal = min(dia_modal, 28)

        exemplo = txs[-1]  # most recent transaction as example
        candidates.append({
            'key': key,
            'descricao': exemplo.descricao,
            'valor_medio': Decimal(str(round(avg, 2))),
            'dia_do_mes': dia_modal,
            'n_meses': len(months),
            'cv': round(cv, 3),
            'categoria': exemplo.categoria,
            'membro': exemplo.extrato.conta.membro,
        })

    candidates.sort(key=lambda c: abs(float(c['valor_medio'])), reverse=True)

    if request.method == 'POST':
        criados = 0
        for c in candidates:
            if request.POST.get(f'sel_{c["key"]}'):
                dia = int(request.POST.get(f'dia_{c["key"]}') or c['dia_do_mes'])
                dia = max(1, min(28, dia))
                LancamentoPlanejado.objects.create(
                    descricao=c['descricao'],
                    valor=c['valor_medio'],
                    tipo=LancamentoPlanejado.TIPO_RECORRENTE,
                    dia_do_mes=dia,
                    data_inicio=today.replace(day=1),
                    categoria=c['categoria'],
                    membro=c['membro'],
                )
                criados += 1
        messages.success(request, f'{criados} lançamento(s) recorrente(s) criado(s).')
        return redirect('planejamento:lancamento_lista')

    return render(request, 'planejamento/sugerir.html', {
        'candidates': candidates,
    })


# ---------------------------------------------------------------------------
# Credit-card average adjustments
# ---------------------------------------------------------------------------

def ajuste_cartao_lista(request):
    from hs_money.cartao_credito.models import Transacao as TCC

    ajustes = AjusteCartaoMes.objects.all()
    form = AjusteCartaoMesForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Ajuste salvo.')
        return redirect('planejamento:ajuste_cartao_lista')

    today = date.today()
    inicio = _meses_atras(today, 3)
    fim_excl = today.replace(day=1)

    qs = TCC.objects.filter(
        oculta=False,
        valor__lt=0,
        fatura__competencia__gte=inicio,
        fatura__competencia__lt=fim_excl,
    ).select_related('fatura')

    monthly_bruto: dict[tuple, Decimal] = defaultdict(ZERO.__class__)
    for t in qs:
        key = (t.fatura.competencia.year, t.fatura.competencia.month)
        monthly_bruto[key] += abs(t.valor)

    ajustes_map: dict[tuple, Decimal] = defaultdict(ZERO.__class__)
    for aj in AjusteCartaoMes.objects.filter(mes__gte=inicio, mes__lt=fim_excl):
        key = (aj.mes.year, aj.mes.month)
        ajustes_map[key] += aj.valor

    breakdown = []
    cur = inicio
    while cur < fim_excl:
        key = (cur.year, cur.month)
        bruto = monthly_bruto.get(key, ZERO)
        ajuste = ajustes_map.get(key, ZERO)
        liquido = max(ZERO, bruto - ajuste)
        breakdown.append({
            'label': f"{MESES_NOME[cur.month][:3]}/{cur.year}",
            'mes_iso': cur.strftime('%Y-%m-%d'),
            'bruto': bruto,
            'ajuste': ajuste,
            'liquido': liquido,
        })
        m, y = cur.month + 1, cur.year
        if m > 12:
            m, y = 1, y + 1
        cur = date(y, m, 1)

    media = _media_mensal_cartao()
    return render(request, 'planejamento/ajuste_cartao.html', {
        'ajustes': ajustes,
        'form': form,
        'media_cartao': media,
        'breakdown': breakdown,
        'n_meses': len(breakdown),
    })


@require_POST
def ajuste_cartao_excluir(request, pk):
    ajuste = get_object_or_404(AjusteCartaoMes, pk=pk)
    ajuste.delete()
    messages.success(request, 'Ajuste excluído.')
    return redirect('planejamento:ajuste_cartao_lista')


# ---------------------------------------------------------------------------
# Patrimônio config — select which investments count
# ---------------------------------------------------------------------------

def patrimonio_config(request):
    from hs_money.investimentos.models import Investimento, SaldoInvestimento

    investimentos = (
        Investimento.objects
        .filter(ativo=True)
        .select_related('membro', 'instituicao')
        .order_by('membro__ordem', 'membro__nome', 'nome')
    )
    selecionados_ids = set(
        PatrimonioInvestimento.objects.values_list('investimento_id', flat=True)
    )

    if request.method == 'POST':
        novos_ids = set(int(v) for v in request.POST.getlist('investimentos'))
        # Remove unchecked
        PatrimonioInvestimento.objects.exclude(investimento_id__in=novos_ids).delete()
        # Add newly checked
        existentes = set(
            PatrimonioInvestimento.objects.values_list('investimento_id', flat=True)
        )
        for inv_id in novos_ids - existentes:
            PatrimonioInvestimento.objects.create(investimento_id=inv_id)
        messages.success(request, 'Configuração de patrimônio salva.')
        return redirect('planejamento:index')

    # Annotate with latest saldo for display
    rows = []
    for inv in investimentos:
        ultimo = (
            SaldoInvestimento.objects
            .filter(investimento=inv)
            .order_by('-data')
            .first()
        )
        rows.append({
            'inv': inv,
            'saldo': ultimo.saldo if ultimo else None,
            'data_ref': ultimo.data if ultimo else None,
            'selecionado': inv.pk in selecionados_ids,
        })

    return render(request, 'planejamento/patrimonio_config.html', {
        'rows': rows,
    })

