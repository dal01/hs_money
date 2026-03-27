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

def _cc_qs(ano, mes, membro_id, excluir_cats=None):
    # Exclui pagamentos de fatura de cartão (já contabilizados no app cartão de crédito)
    from django.db.models import Q
    from hs_money.core.models import Categoria as _Cat
    ids_fatura = list(
        _Cat.objects.filter(nome__icontains='fatura do cart')
        .values_list('pk', flat=True)
    )
    qs = (TransacaoCC.objects
          .filter(oculta=False)
          .exclude(categoria_id__in=ids_fatura)
          .select_related('extrato__conta__membro', 'categoria', 'categoria__categoria_pai')
          .prefetch_related('membros'))
    if excluir_cats:
        qs = qs.exclude(
            Q(categoria_id__in=excluir_cats) |
            Q(categoria__categoria_pai_id__in=excluir_cats)
        )
    if ano:
        qs = qs.filter(data__year=ano)
    if mes:
        qs = qs.filter(data__month=mes)
    if membro_id:
        qs = qs.filter(extrato__conta__membro_id=membro_id)
    return qs


def _cartao_qs(ano, mes, membro_id, excluir_cats=None):
    from django.db.models import Q
    qs = (TransacaoCartao.objects
          .filter(oculta=False)
          .select_related('fatura__cartao__membro', 'categoria', 'categoria__categoria_pai')
          .prefetch_related('membros'))
    if excluir_cats:
        qs = qs.exclude(
            Q(categoria_id__in=excluir_cats) |
            Q(categoria__categoria_pai_id__in=excluir_cats)
        )
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


def _por_categoria(lista_cc, lista_cartao, agrupar='sub'):
    """Top categorias por valor absoluto (despesas), combinando as duas fontes.
    agrupar='sub'  → usa a categoria/subcategoria da transação (comportamento original)
    agrupar='mac'  → agrupa pela categoria-pai (macro); subcategorias são somadas ao pai
    """
    cat_map: dict = defaultdict(lambda: {'nome': '', 'cc': ZERO, 'cartao': ZERO})

    def _key_and_nome(t):
        cat = t.categoria
        if not cat:
            return 0, '— Sem categoria —'
        if agrupar == 'mac' and cat.categoria_pai_id:
            # subcategoria → agrupa no pai
            pai = cat.categoria_pai
            return pai.pk, pai.nome
        return cat.pk, cat.nome

    for t in lista_cc:
        if t.valor >= ZERO:
            continue
        key, nome = _key_and_nome(t)
        cat_map[key]['nome']  = nome
        cat_map[key]['cc']   += t.valor

    for t in lista_cartao:
        if t.valor >= ZERO:
            continue
        key, nome = _key_and_nome(t)
        cat_map[key]['nome']    = nome
        cat_map[key]['cartao'] += t.valor

    rows = []
    for key, data in cat_map.items():
        total = data['cc'] + data['cartao']
        rows.append({
            'pk':     key,
            'nome':   data['nome'],
            'cc':     data['cc'],
            'cartao': data['cartao'],
            'total':  total,
        })

    rows.sort(key=lambda r: r['total'])   # mais negativo primeiro
    return rows[:20]


def _por_membro(lista_cc, lista_cartao, membros):
    """Breakdown por membro usando a atribuição M2M das transações.
    Se uma transação tem N membros, divide o valor igualmente entre eles.
    Transações sem nenhum membro vão para 'Sem membro'.
    """
    membro_map = {m.pk: {'pk': m.pk, 'nome': m.nome, 'cc': ZERO, 'cartao': ZERO}
                  for m in membros}
    sem = {'pk': None, 'nome': '— Sem membro —', 'cc': ZERO, 'cartao': ZERO}

    for t in lista_cc:
        if t.valor >= ZERO:
            continue
        ms = list(t.membros.all())
        if ms:
            parte = t.valor / len(ms)
            for m in ms:
                bucket = membro_map.get(m.pk)
                if bucket:
                    bucket['cc'] += parte
        else:
            sem['cc'] += t.valor

    for t in lista_cartao:
        if t.valor >= ZERO:
            continue
        ms = list(t.membros.all())
        if ms:
            parte = t.valor / len(ms)
            for m in ms:
                bucket = membro_map.get(m.pk)
                if bucket:
                    bucket['cartao'] += parte
        else:
            sem['cartao'] += t.valor

    rows = list(membro_map.values())
    if sem['cc'] or sem['cartao']:
        rows.append(sem)

    for r in rows:
        r['total'] = r['cc'] + r['cartao']

    return rows


def _kpi_membros(lista_cc, lista_cartao, membros):
    """Totais de entradas e saídas (CC e Cartão separados) por membro para os KPI cards."""
    def _bucket():
        return {'cc_cred': ZERO, 'cc_deb': ZERO, 'ca_deb': ZERO}

    membro_map = {m.pk: dict(pk=m.pk, nome=m.nome, **_bucket()) for m in membros}
    sem = dict(pk=None, nome='— Sem membro —', **_bucket())

    for t in lista_cc:
        ms = list(t.membros.all())
        n = len(ms) or 1
        if t.valor > ZERO:
            if ms:
                parte = t.valor / n
                for m in ms:
                    if m.pk in membro_map:
                        membro_map[m.pk]['cc_cred'] += parte
            else:
                sem['cc_cred'] += t.valor
        elif t.valor < ZERO:
            if ms:
                parte = t.valor / n
                for m in ms:
                    if m.pk in membro_map:
                        membro_map[m.pk]['cc_deb'] += parte
            else:
                sem['cc_deb'] += t.valor

    for t in lista_cartao:
        if t.valor >= ZERO:
            continue
        ms = list(t.membros.all())
        n = len(ms) or 1
        if ms:
            parte = t.valor / n
            for m in ms:
                if m.pk in membro_map:
                    membro_map[m.pk]['ca_deb'] += parte
        else:
            sem['ca_deb'] += t.valor

    rows = list(membro_map.values())
    if any(sem[k] for k in ('cc_cred', 'cc_deb', 'ca_deb')):
        rows.append(sem)

    for r in rows:
        r['total_cred'] = r['cc_cred']
        r['total_deb']  = r['cc_deb'] + r['ca_deb']
        if r['total_cred']:
            r['pct'] = abs(r['total_deb']) / r['total_cred'] * 100
        else:
            r['pct'] = None

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
    ano_sel    = request.GET.get('ano',       str(ano_atual))
    mes_sel    = request.GET.get('mes',       '')
    membro_sel = request.GET.get('membro',    '')
    cat_nivel  = request.GET.get('cat_nivel', 'sub')   # 'sub' ou 'mac'
    excluir_cats = {int(x) for x in request.GET.getlist('excluir_cat') if x.isdigit()}

    # anos disponíveis (união de CC e cartão)
    anos_cc     = set(d.year for d in _TCC.objects.dates('data', 'year'))
    anos_cartao = set(d.year for d in FaturaCartao.objects.dates('competencia', 'year'))
    anos_disponiveis = sorted(anos_cc | anos_cartao, reverse=True)

    from hs_money.core.models import Categoria as _Cat
    membros = Membro.objects.order_by('ordem', 'nome')
    macros_cats = list(_Cat.objects.filter(nivel=1).prefetch_related('subcategorias').order_by('nome'))
    
    excluir_cats_nomes = []
    if excluir_cats:
        excluir_cats_nomes = list(_Cat.objects.filter(pk__in=excluir_cats).values('pk', 'nome'))

    # --- querysets ---
    lista_cc     = list(_cc_qs(ano_sel, mes_sel, membro_sel, excluir_cats))
    lista_cartao = list(_cartao_qs(ano_sel, mes_sel, membro_sel, excluir_cats))

    # --- totais ---
    cc_cred,  cc_deb,  cc_saldo  = _totais(lista_cc)
    ca_cred,  ca_deb,  ca_saldo  = _totais(lista_cartao)
    total_creditos = cc_cred + ca_cred
    total_debitos  = cc_deb  + ca_deb
    total_saldo    = cc_saldo + ca_saldo

    # --- breakdowns ---
    por_mes       = _por_mes(lista_cc, lista_cartao) if not mes_sel else []
    por_categoria = _por_categoria(lista_cc, lista_cartao, agrupar=cat_nivel)
    por_membro    = _por_membro(lista_cc, lista_cartao, membros)
    _km           = _kpi_membros(lista_cc, lista_cartao, membros)
    for r in _km:
        r['pct_cred'] = round(r['total_cred'] / total_creditos * 100, 1) if total_creditos else None
        r['pct_deb']  = round(abs(r['total_deb']) / abs(total_debitos) * 100, 1) if total_debitos else None
    kpi_membros_cred = [r for r in _km if r['cc_cred']]
    kpi_membros_deb  = [r for r in _km if r['cc_deb'] or r['ca_deb']]
    kpi_membros      = [r for r in _km if r['total_cred'] or r['total_deb']]

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
        'kpi_membros_cred': kpi_membros_cred,
        'kpi_membros_deb':  kpi_membros_deb,
        'kpi_membros':      kpi_membros,
        'cat_nivel':        cat_nivel,
        'macros_cats':      macros_cats,
        'excluir_cats':     excluir_cats,
        'excluir_cats_nomes': excluir_cats_nomes,
    }
    return render(request, 'relatorios/dashboard.html', context)


def membro_transacoes_json(request):
    """Retorna JSON com lançamentos de gastos de um membro (CC ou Cartão) para a modal."""
    from django.http import JsonResponse
    from hs_money.core.models import Categoria as _Cat

    membro_id = request.GET.get('membro_id', '')
    fonte     = request.GET.get('fonte', 'cc')
    ano       = request.GET.get('ano', '')
    mes       = request.GET.get('mes', '')

    def _fmt_brl(v):
        abs_v = abs(v)
        s = f"{abs_v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"R$ {'-' if v < 0 else ''}{s}"

    rows = []
    total = ZERO

    if fonte == 'cc':
        ids_fatura = list(
            _Cat.objects.filter(nome__icontains='fatura do cart')
            .values_list('pk', flat=True)
        )
        qs = (TransacaoCC.objects
              .filter(oculta=False, valor__lt=0)
              .exclude(categoria_id__in=ids_fatura)
              .select_related('categoria')
              .prefetch_related('membros'))
        if ano:
            qs = qs.filter(data__year=ano)
        if mes:
            qs = qs.filter(data__month=mes)
        if membro_id:
            qs = qs.filter(membros__pk=membro_id)
        else:
            qs = qs.filter(membros__isnull=True)
        for t in qs.order_by('data'):
            num_membros = t.membros.count() or 1
            valor_parte = t.valor / num_membros
            total += valor_parte
            rows.append({
                'data': t.data.strftime('%d/%m/%Y'),
                'descricao': t.descricao,
                'categoria': t.categoria.nome if t.categoria else '—',
                'valor_fmt': _fmt_brl(valor_parte),
                'divisao': f'÷{num_membros}' if num_membros > 1 else '',
            })
    else:
        qs = (TransacaoCartao.objects
              .filter(oculta=False, valor__lt=0)
              .select_related('categoria')
              .prefetch_related('membros'))
        if ano:
            qs = qs.filter(fatura__competencia__year=ano)
        if mes:
            qs = qs.filter(fatura__competencia__month=mes)
        if membro_id:
            qs = qs.filter(membros__pk=membro_id)
        else:
            qs = qs.filter(membros__isnull=True)
        for t in qs.order_by('data'):
            num_membros = t.membros.count() or 1
            valor_parte = t.valor / num_membros
            total += valor_parte
            rows.append({
                'data': t.data.strftime('%d/%m/%Y'),
                'descricao': t.descricao,
                'categoria': t.categoria.nome if t.categoria else '—',
                'valor_fmt': _fmt_brl(valor_parte),
                'divisao': f'÷{num_membros}' if num_membros > 1 else '',
            })

    return JsonResponse({
        'transacoes': rows,
        'total_fmt': _fmt_brl(total),
    })


def categoria_transacoes_json(request):
    """Retorna JSON com lançamentos de gastos de uma categoria para a modal."""
    from django.http import JsonResponse
    from django.db.models import Q
    from hs_money.core.models import Categoria as _Cat

    cat_pk    = request.GET.get('cat_pk', '0')
    cat_nivel = request.GET.get('cat_nivel', 'sub')
    fonte     = request.GET.get('fonte', 'total')
    ano       = request.GET.get('ano', '')
    mes       = request.GET.get('mes', '')
    membro_id = request.GET.get('membro_id', '')

    try:
        cat_pk = int(cat_pk)
    except (ValueError, TypeError):
        cat_pk = 0

    def _fmt_brl(v):
        abs_v = abs(v)
        s = f"{abs_v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"R$ {'-' if v < 0 else ''}{s}"

    def _filter_cat(qs):
        if cat_pk == 0:
            return qs.filter(categoria__isnull=True)
        if cat_nivel == 'mac':
            return qs.filter(Q(categoria_id=cat_pk) | Q(categoria__categoria_pai_id=cat_pk))
        return qs.filter(categoria_id=cat_pk)

    rows = []
    total = ZERO

    if fonte in ('cc', 'total'):
        ids_fatura = list(
            _Cat.objects.filter(nome__icontains='fatura do cart')
            .values_list('pk', flat=True)
        )
        qs_cc = (TransacaoCC.objects
                 .filter(oculta=False, valor__lt=0)
                 .exclude(categoria_id__in=ids_fatura)
                 .select_related('categoria')
                 .prefetch_related('membros'))
        if ano:
            qs_cc = qs_cc.filter(data__year=ano)
        if mes:
            qs_cc = qs_cc.filter(data__month=mes)
        if membro_id:
            qs_cc = qs_cc.filter(extrato__conta__membro_id=membro_id)
        qs_cc = _filter_cat(qs_cc)
        for t in qs_cc.order_by('data'):
            total += t.valor
            membros_nomes = ', '.join(m.nome for m in t.membros.all()) or '—'
            rows.append({
                'data':      t.data.strftime('%d/%m/%Y'),
                'descricao': t.descricao,
                'membros':   membros_nomes,
                'valor_fmt': _fmt_brl(t.valor),
                'fonte':     'CC',
            })

    if fonte in ('cartao', 'total'):
        qs_ca = (TransacaoCartao.objects
                 .filter(oculta=False, valor__lt=0)
                 .select_related('categoria')
                 .prefetch_related('membros'))
        if ano:
            qs_ca = qs_ca.filter(fatura__competencia__year=ano)
        if mes:
            qs_ca = qs_ca.filter(fatura__competencia__month=mes)
        if membro_id:
            qs_ca = qs_ca.filter(fatura__cartao__membro_id=membro_id)
        qs_ca = _filter_cat(qs_ca)
        for t in qs_ca.order_by('data'):
            total += t.valor
            membros_nomes = ', '.join(m.nome for m in t.membros.all()) or '—'
            rows.append({
                'data':      t.data.strftime('%d/%m/%Y'),
                'descricao': t.descricao,
                'membros':   membros_nomes,
                'valor_fmt': _fmt_brl(t.valor),
                'fonte':     'Cartão',
            })

    rows.sort(key=lambda r: r['data'])
    return JsonResponse({
        'transacoes': rows,
        'total_fmt': _fmt_brl(total),
    })


def mes_transacoes_json(request):
    """Retorna JSON com lançamentos de um mês específico para a modal de evolução mensal."""
    from django.http import JsonResponse
    from hs_money.core.models import Categoria as _Cat

    ano       = request.GET.get('ano', '')
    mes       = request.GET.get('mes', '')
    fonte     = request.GET.get('fonte', 'cc')   # cc_creditos|cc_debitos|ca_creditos|ca_gastos
    membro_id = request.GET.get('membro_id', '')

    def _fmt_brl(v):
        abs_v = abs(v)
        s = f"{abs_v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f"R$ {'-' if v < 0 else ''}{s}"

    rows = []
    total = ZERO

    if fonte in ('cc_creditos', 'cc_debitos'):
        ids_fatura = list(
            _Cat.objects.filter(nome__icontains='fatura do cart')
            .values_list('pk', flat=True)
        )
        qs = (TransacaoCC.objects
              .filter(oculta=False)
              .exclude(categoria_id__in=ids_fatura)
              .select_related('categoria'))
        if ano:
            qs = qs.filter(data__year=ano)
        if mes:
            qs = qs.filter(data__month=mes)
        if membro_id:
            qs = qs.filter(extrato__conta__membro_id=membro_id)
        if fonte == 'cc_creditos':
            qs = qs.filter(valor__gt=0)
        else:
            qs = qs.filter(valor__lt=0)
        for t in qs.order_by('data'):
            total += t.valor
            rows.append({
                'data':      t.data.strftime('%d/%m/%Y'),
                'descricao': t.descricao,
                'categoria': t.categoria.nome if t.categoria else '—',
                'valor_fmt': _fmt_brl(t.valor),
            })
    else:  # ca_creditos | ca_gastos
        qs = (TransacaoCartao.objects
              .filter(oculta=False)
              .select_related('categoria'))
        if ano:
            qs = qs.filter(fatura__competencia__year=ano)
        if mes:
            qs = qs.filter(fatura__competencia__month=mes)
        if membro_id:
            qs = qs.filter(fatura__cartao__membro_id=membro_id)
        if fonte == 'ca_creditos':
            qs = qs.filter(valor__gt=0)
        else:
            qs = qs.filter(valor__lt=0)
        for t in qs.order_by('data'):
            total += t.valor
            rows.append({
                'data':      t.data.strftime('%d/%m/%Y'),
                'descricao': t.descricao,
                'categoria': t.categoria.nome if t.categoria else '—',
                'valor_fmt': _fmt_brl(t.valor),
            })

    return JsonResponse({
        'transacoes': rows,
        'total_fmt': _fmt_brl(total),
    })
