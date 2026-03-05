"""
relatorios/views.py — Dashboard consolidado (Conta Corrente + Cartão de Crédito).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from django.shortcuts import render

from hs_money.conta_corrente.models import Transacao as TransacaoCC
from hs_money.cartao_credito.models import Transacao as TransacaoCartao
from hs_money.core.models import Membro

ZERO = Decimal('0')

MESES = [
    (1, 'Jan'), (2, 'Fev'), (3, 'Mar'), (4, 'Abr'),
    (5, 'Mai'), (6, 'Jun'), (7, 'Jul'), (8, 'Ago'),
    (9, 'Set'), (10, 'Out'), (11, 'Nov'), (12, 'Dez'),
]
MESES_NOME = {n: label for n, label in MESES}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cc_qs(ano, mes, membro_id):
    qs = (TransacaoCC.objects
          .filter(oculta=False)
          .select_related('extrato__conta__membro', 'categoria'))
    if ano:
        qs = qs.filter(data__year=ano)
    if mes:
        qs = qs.filter(data__month=mes)
    if membro_id:
        qs = qs.filter(extrato__conta__membro_id=membro_id)
    return qs


def _cartao_qs(ano, mes, membro_id):
    qs = (TransacaoCartao.objects
          .filter(oculta=False)
          .select_related('fatura__cartao__membro', 'categoria'))
    if ano:
        qs = qs.filter(fatura__competencia__year=ano)
    if mes:
        qs = qs.filter(fatura__competencia__month=mes)
    if membro_id:
        qs = qs.filter(fatura__cartao__membro_id=membro_id)
    return qs


def _totais(lista):
    creditos = sum((t.valor for t in lista if t.valor > ZERO), ZERO)
    debitos  = sum((t.valor for t in lista if t.valor < ZERO), ZERO)
    return creditos, debitos, creditos + debitos


def _por_mes(lista_cc, lista_cartao):
    """Retorna lista de dicts com breakdown mensal, meses ordenados."""
    cc_mes: dict     = defaultdict(lambda: [ZERO, ZERO])   # mes -> [creditos, debitos]
    cartao_mes: dict = defaultdict(lambda: [ZERO, ZERO])

    for t in lista_cc:
        m = t.data.month
        if t.valor > 0:
            cc_mes[m][0] += t.valor
        else:
            cc_mes[m][1] += t.valor

    for t in lista_cartao:
        m = t.fatura.competencia.month
        if t.valor > 0:
            cartao_mes[m][0] += t.valor
        else:
            cartao_mes[m][1] += t.valor

    meses_presentes = sorted(set(cc_mes) | set(cartao_mes))
    rows = []
    for m in meses_presentes:
        cc_cred, cc_deb   = cc_mes[m]
        ca_cred, ca_deb   = cartao_mes[m]
        saldo_cc     = cc_cred + cc_deb
        saldo_cartao = ca_cred + ca_deb
        rows.append({
            'mes':         m,
            'mes_nome':    MESES_NOME[m],
            'cc_creditos': cc_cred,
            'cc_debitos':  cc_deb,
            'cc_saldo':    saldo_cc,
            'ca_gastos':   ca_deb,
            'ca_creditos': ca_cred,
            'ca_saldo':    saldo_cartao,
            'total':       saldo_cc + saldo_cartao,
        })
    return rows


def _por_categoria(lista_cc, lista_cartao):
    """Top categorias por valor absoluto (despesas), combinando as duas fontes."""
    cat_map: dict = defaultdict(lambda: {'nome': '', 'cc': ZERO, 'cartao': ZERO})

    for t in lista_cc:
        if t.valor >= ZERO:
            continue
        key = t.categoria_id or 0
        cat_map[key]['nome']   = str(t.categoria) if t.categoria else '— Sem categoria —'
        cat_map[key]['cc']    += t.valor

    for t in lista_cartao:
        if t.valor >= ZERO:
            continue
        key = t.categoria_id or 0
        cat_map[key]['nome']    = str(t.categoria) if t.categoria else '— Sem categoria —'
        cat_map[key]['cartao'] += t.valor

    rows = []
    for data in cat_map.values():
        total = data['cc'] + data['cartao']
        rows.append({
            'nome':   data['nome'],
            'cc':     data['cc'],
            'cartao': data['cartao'],
            'total':  total,
        })

    rows.sort(key=lambda r: r['total'])   # mais negativo primeiro
    return rows[:20]


def _por_membro(lista_cc, lista_cartao, membros):
    """Breakdown por membro (despesas)."""
    membro_map = {m.pk: {'nome': m.nome, 'cc': ZERO, 'cartao': ZERO}
                  for m in membros}
    sem = {'nome': '— Sem membro —', 'cc': ZERO, 'cartao': ZERO}

    for t in lista_cc:
        membro_id = t.extrato.conta.membro_id
        bucket = membro_map.get(membro_id, sem)
        bucket['cc'] += t.valor

    for t in lista_cartao:
        membro_id = t.fatura.cartao.membro_id
        bucket = membro_map.get(membro_id, sem)
        bucket['cartao'] += t.valor

    rows = list(membro_map.values())
    if sem['cc'] or sem['cartao']:
        rows.append(sem)

    for r in rows:
        r['total'] = r['cc'] + r['cartao']
        r['gastos_cc']     = r['cc']
        r['gastos_cartao'] = r['cartao']

    return rows


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

def dashboard(request):
    from django.db.models.functions import TruncYear
    from hs_money.cartao_credito.models import FaturaCartao
    from hs_money.conta_corrente.models import Transacao as _TCC

    # --- filtros ---
    import datetime
    ano_atual = datetime.date.today().year
    ano_sel    = request.GET.get('ano',    str(ano_atual))
    mes_sel    = request.GET.get('mes',    '')
    membro_sel = request.GET.get('membro', '')

    # anos disponíveis (união de CC e cartão)
    anos_cc     = set(d.year for d in _TCC.objects.dates('data', 'year'))
    anos_cartao = set(d.year for d in FaturaCartao.objects.dates('competencia', 'year'))
    anos_disponiveis = sorted(anos_cc | anos_cartao, reverse=True)

    membros = Membro.objects.order_by('ordem', 'nome')

    # --- querysets ---
    lista_cc     = list(_cc_qs(ano_sel, mes_sel, membro_sel))
    lista_cartao = list(_cartao_qs(ano_sel, mes_sel, membro_sel))

    # --- totais ---
    cc_cred,  cc_deb,  cc_saldo  = _totais(lista_cc)
    ca_cred,  ca_deb,  ca_saldo  = _totais(lista_cartao)
    total_creditos = cc_cred + ca_cred
    total_debitos  = cc_deb  + ca_deb
    total_saldo    = cc_saldo + ca_saldo

    # --- breakdowns ---
    por_mes       = _por_mes(lista_cc, lista_cartao) if not mes_sel else []
    por_categoria = _por_categoria(lista_cc, lista_cartao)
    por_membro    = _por_membro(lista_cc, lista_cartao, membros)

    context = {
        'ano_sel':         ano_sel,
        'mes_sel':         mes_sel,
        'membro_sel':      membro_sel,
        'anos_disponiveis': anos_disponiveis,
        'meses':           MESES,
        'membros':         membros,
        # totais globais
        'cc_creditos':     cc_cred,
        'cc_debitos':      cc_deb,
        'cc_saldo':        cc_saldo,
        'ca_creditos':     ca_cred,
        'ca_debitos':      ca_deb,
        'ca_saldo':        ca_saldo,
        'total_creditos':  total_creditos,
        'total_debitos':   total_debitos,
        'total_saldo':     total_saldo,
        'qtd_cc':          len(lista_cc),
        'qtd_cartao':      len(lista_cartao),
        # breakdowns
        'por_mes':         por_mes,
        'por_categoria':   por_categoria,
        'por_membro':      por_membro,
    }
    return render(request, 'relatorios/dashboard.html', context)
