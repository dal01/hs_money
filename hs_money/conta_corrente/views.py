from __future__ import annotations

import re
import hashlib
from io import BytesIO
from pathlib import Path
from itertools import groupby

from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings

from unidecode import unidecode

from hs_money.core.models import Membro, InstituicaoFinanceira
from hs_money.conta_corrente.models import ContaCorrente, Extrato, Transacao
from hs_money.conta_corrente.services.importar import importar_arquivo_ofx, hash_arquivo_ofx


# ---------------------------------------------------------------------------
# Form inline
# ---------------------------------------------------------------------------

class ContaCorrenteForm(forms.ModelForm):
    class Meta:
        model = ContaCorrente
        fields = ['instituicao', 'membro', 'agencia', 'numero', 'ativa']
        widgets = {
            'instituicao': forms.Select(attrs={'class': 'form-select'}),
            'membro':      forms.Select(attrs={'class': 'form-select'}),
            'agencia':     forms.TextInput(attrs={'class': 'form-control'}),
            'numero':      forms.TextInput(attrs={'class': 'form-control'}),
            'ativa':       forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


def index(request):
    return redirect('conta_corrente:conta_lista')


# ---------------------------------------------------------------------------
# Extratos no disco → listagem para processamento
# ---------------------------------------------------------------------------

def _sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def listar_extratos_disco(request):
    """
    Varre DADOS_DIR/conta_corrente/**/*.ofx e mostra quais já foram
    importados (via Extrato.arquivo_hash) e quais ainda estão pendentes.
    """
    dados_dir = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    raiz_cc   = dados_dir / 'conta_corrente'

    # hashes já importados — set para lookup O(1)
    hashes_importados = set(Extrato.objects.values_list('arquivo_hash', flat=True))

    arquivos = sorted(raiz_cc.rglob('*.ofx')) if raiz_cc.exists() else []

    itens = []
    for arq in arquivos:
        try:
            raw = arq.read_bytes()
            sha = hash_arquivo_ofx(raw)   # mesmo algoritmo do service
        except OSError:
            raw, sha = b'', ''

        partes = arq.relative_to(raiz_cc).parts
        membro_slug = partes[0] if len(partes) > 1 else '—'
        ano         = partes[1] if len(partes) > 2 else '—'
        banco_slug  = partes[2] if len(partes) > 3 else '—'

        caminho_rel = str(arq.relative_to(dados_dir))

        itens.append({
            'caminho':    caminho_rel,
            'nome':       arq.name,
            'membro':     membro_slug.replace('-', ' ').title(),
            'ano':        ano,
            'banco':      banco_slug.replace('-', ' ').title(),
            'importado':  sha in hashes_importados,
            'tamanho_kb': round(len(raw) / 1024, 1) if raw else 0,
        })

    grupos = {}
    for item in itens:
        g1 = grupos.setdefault(item['membro'], {})
        g2 = g1.setdefault(item['ano'], {})
        g2.setdefault(item['banco'], []).append(item)

    pendentes = sum(1 for i in itens if not i['importado'])

    return render(request, 'conta_corrente/extratos/lista_disco.html', {
        'grupos':      grupos,
        'total':       len(itens),
        'pendentes':   pendentes,
        'raiz_existe': raiz_cc.exists(),
    })


# ---------------------------------------------------------------------------
# Processar extratos (OFX já salvos em disco → banco de dados)
# ---------------------------------------------------------------------------

def processar_extratos(request):
    """
    POST: recebe lista de caminhos relativos (em relação a DADOS_DIR),
    processa cada .ofx e retorna a página de resultado.
    GET redireciona para a lista de contas.
    """
    if request.method != 'POST':
        return redirect('conta_corrente:conta_lista')

    dados_dir   = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    caminhos_rel = request.POST.getlist('caminhos')
    dry_run      = bool(request.POST.get('dry_run'))

    resultados = []
    for rel in caminhos_rel:
        caminho = (dados_dir / rel).resolve()
        if not caminho.exists() or caminho.suffix.lower() != '.ofx':
            resultados.append({
                'arquivo':  rel,
                'status':   'erro',
                'erro':     'Arquivo não encontrado ou não é OFX.',
                'novos':    0,
                'pulados':  0,
                'periodo':  '',
                'conta_str': '',
                'avisos':   [],
            })
            continue
        r = importar_arquivo_ofx(caminho, dry_run=dry_run)
        resultados.append({
            'arquivo':      r.arquivo,
            'status':       r.status,
            'erro':         r.erro,
            'novos':        r.novos,
            'pulados':      r.pulados,
            'periodo':      r.periodo,
            'conta_str':    r.conta_str,
            'conta_criada': r.conta_criada,
            'avisos':       r.avisos,
            'dry_run':      dry_run,
        })

    totais = {
        'novos':   sum(r['novos']   for r in resultados),
        'pulados': sum(r['pulados'] for r in resultados),
        'erros':   sum(1 for r in resultados if r['status'] == 'erro'),
    }

    return render(request, 'conta_corrente/processar/resultado.html', {
        'resultados': resultados,
        'totais':     totais,
        'dry_run':    dry_run,
        # repassa caminhos para permitir "processar de verdade" após dry-run
        'caminhos':   caminhos_rel,
    })


# ---------------------------------------------------------------------------
# Helpers de deteção
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', unidecode((s or '').lower().strip())).strip('_')


def _normalizar_nome(filename: str) -> str:
    """extrato conta corrente - 012024.ofx  →  extrato_cc_012024.ofx"""
    stem, _, ext = filename.rpartition('.')
    stem = unidecode(stem)
    stem = re.sub(r'[^a-zA-Z0-9]+', '_', stem).strip('_').lower()
    # compacta duplos underscores
    stem = re.sub(r'_+', '_', stem)
    return f"{stem}.{ext.lower()}" if ext else stem


def _detectar_ofx(raw: bytes) -> dict:
    """
    Extrai do cabeçalho OFX (SGML ou XML):
      - org: valor de <FI><ORG>
      - fid: valor de <FI><FID>
      - acctid: número da conta
      - dtstart / dtend: período do extrato
    """
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        text = raw.decode('latin-1', errors='replace')

    def _tag(tag):
        m = re.search(rf'<{tag}>\s*([^<\r\n]+)', text, re.IGNORECASE)
        return m.group(1).strip() if m else ''

    return {
        'org':     _tag('ORG'),
        'fid':     _tag('FID'),
        'acctid':  _tag('ACCTID'),
        'branchid': _tag('BRANCHID'),
        'dtstart': _tag('DTSTART')[:8],  # YYYYMMDD
        'dtend':   _tag('DTEND')[:8],
    }


def _match_instituicao(org: str, fid: str) -> InstituicaoFinanceira | None:
    """Tenta casar <FI><ORG> ou <FID> com InstituicaoFinanceira."""
    if org:
        inst = InstituicaoFinanceira.objects.filter(nome__iexact=org.strip()).first()
        if inst:
            return inst
        # tenta pelo slug do nome
        org_slug = _slug(org)
        for inst in InstituicaoFinanceira.objects.all():
            if _slug(inst.nome) == org_slug or (inst.codigo and _slug(inst.codigo) in org_slug):
                return inst
    if fid:
        inst = InstituicaoFinanceira.objects.filter(codigo__iexact=fid.strip()).first()
        if inst:
            return inst
    return None


def _match_membro(acctid: str, inst: InstituicaoFinanceira | None) -> Membro | None:
    """Tenta casar ACCTID com ContaCorrente já cadastrada."""""
    if not acctid:
        return None
    qs = ContaCorrente.objects.filter(numero=acctid.strip())
    if inst:
        qs = qs.filter(instituicao=inst)
    cc = qs.select_related('membro').first()
    return cc.membro if cc and cc.membro else None


def _detectar_ano_mes(filename: str, dtstart: str) -> tuple[str, str]:
    """Retorna (ano, mm) detectados do nome do arquivo ou do período OFX."""
    # 1) tenta mmaaaa no nome  ex.: 012024
    m = re.search(r'(\d{2})(\d{4})', filename)
    if m:
        return m.group(2), m.group(1)  # ano, mm
    # 2) tenta no dtstart YYYYMMDD
    if dtstart and len(dtstart) >= 6:
        return dtstart[:4], dtstart[4:6]
    from django.utils import timezone
    hoje = timezone.now().date()
    return str(hoje.year), f'{hoje.month:02d}'


# ---------------------------------------------------------------------------
# Contas Correntes
# ---------------------------------------------------------------------------

def conta_lista(request):
    """Lista contas agrupadas por membro."""
    contas = (
        ContaCorrente.objects
        .select_related('membro', 'instituicao')
        .order_by('membro__nome', 'instituicao__nome', 'numero')
    )
    # agrupa por membro (None = sem titular)
    grupos = []
    for membro, items in groupby(contas, key=lambda c: c.membro):
        grupos.append({'membro': membro, 'contas': list(items)})
    # sem titular vai ao fim
    grupos.sort(key=lambda g: (g['membro'] is None, g['membro'].nome if g['membro'] else ''))
    return render(request, 'conta_corrente/contas/lista.html', {'grupos': grupos})


def conta_criar(request):
    form = ContaCorrenteForm(request.POST or None)
    if form.is_valid():
        conta = form.save()
        messages.success(request, f'Conta {conta.numero} criada.')
        return redirect('conta_corrente:conta_lista')
    return render(request, 'conta_corrente/contas/form.html', {
        'form': form,
        'titulo': 'Nova Conta Corrente',
    })


def conta_editar(request, pk):
    conta = get_object_or_404(ContaCorrente, pk=pk)
    form = ContaCorrenteForm(request.POST or None, instance=conta)
    if form.is_valid():
        form.save()
        messages.success(request, f'Conta {conta.numero} atualizada.')
        return redirect('conta_corrente:conta_lista')
    return render(request, 'conta_corrente/contas/form.html', {
        'form': form,
        'titulo': f'Editar conta {conta.numero}',
        'conta': conta,
    })


# ---------------------------------------------------------------------------
# Upload de extrato
# ---------------------------------------------------------------------------

def upload_extrato(request, conta_pk=None):
    """Upload genérico ou pré-selecionado para uma conta específica."""
    conta_selecionada = get_object_or_404(ContaCorrente, pk=conta_pk) if conta_pk else None
    membros      = Membro.objects.order_by('nome')
    instituicoes = InstituicaoFinanceira.objects.order_by('nome')

    if request.method != 'POST':
        return render(request, 'conta_corrente/upload/form.html', {
            'membros':           membros,
            'instituicoes':      instituicoes,
            'conta_selecionada': conta_selecionada,
        })

    arquivos     = request.FILES.getlist('arquivos')
    membro_force = request.POST.get('membro')
    inst_force   = request.POST.get('instituicao')
    dados_dir    = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')

    membro_obj_force = Membro.objects.filter(pk=membro_force).first() if membro_force else None
    inst_obj_force   = InstituicaoFinanceira.objects.filter(pk=inst_force).first() if inst_force else None

    resultados = []

    for f in arquivos:
        nome_original = f.name
        ext = nome_original.rsplit('.', 1)[-1].lower() if '.' in nome_original else ''
        raw = f.read()

        info = {'nome_original': nome_original, 'status': 'ok', 'erro': '', 'caminho': '',
                'is_ofx': ext == 'ofx'}

        ofx_data = {}
        if ext == 'ofx':
            ofx_data = _detectar_ofx(raw)

        inst   = inst_obj_force   or _match_instituicao(ofx_data.get('org', ''), ofx_data.get('fid', ''))
        membro = membro_obj_force or _match_membro(ofx_data.get('acctid', ''), inst)

        if not inst:
            info['status'] = 'erro'
            info['erro']   = 'Instituição não detectada. Selecione manualmente.'
            resultados.append(info)
            continue

        if not membro:
            info['status'] = 'aviso'
            info['erro']   = 'Membro não detectado — arquivo salvo sem titular.'

        ano, mm = _detectar_ano_mes(nome_original, ofx_data.get('dtstart', ''))
        membro_slug = _slug(membro.nome) if membro else 'sem_membro'
        inst_slug   = inst.codigo or _slug(inst.nome)
        nome_norm   = _normalizar_nome(nome_original)

        destino = dados_dir / 'conta_corrente' / membro_slug / ano / inst_slug
        destino.mkdir(parents=True, exist_ok=True)
        arquivo_path = destino / nome_norm

        if arquivo_path.exists():
            sha_novo   = hashlib.sha1(raw).hexdigest()
            sha_exist  = hashlib.sha1(arquivo_path.read_bytes()).hexdigest()
            if sha_novo == sha_exist:
                info['status']  = 'ignorado'
                info['erro']    = 'Arquivo idêntico já existe.'
                info['caminho'] = str(arquivo_path.relative_to(dados_dir))
                resultados.append(info)
                continue
            stem, _, ex = nome_norm.rpartition('.')
            i = 2
            while arquivo_path.exists():
                arquivo_path = destino / f"{stem}_{i}.{ex}"
                i += 1

        arquivo_path.write_bytes(raw)

        info['inst']      = inst.nome
        info['membro']    = membro.nome if membro else '—'
        info['ano']       = ano
        info['nome_norm'] = arquivo_path.name
        info['caminho']   = str(arquivo_path.relative_to(dados_dir))
        info['is_ofx']    = ext == 'ofx'
        resultados.append(info)

    return render(request, 'conta_corrente/upload/resultado.html', {
         'resultados':        resultados,
         'conta_selecionada': conta_selecionada,
    })


# ---------------------------------------------------------------------------
# Lista de transações de uma conta
# ---------------------------------------------------------------------------

def transacoes_conta(request, pk):
    """Atalho: redireciona para a lista global pré-filtrada pela conta."""
    from django.urls import reverse
    return redirect(reverse('conta_corrente:transacoes_lista') + f'?conta={pk}')


# ---------------------------------------------------------------------------
# Lista GLOBAL de transações (todas as contas)
# ---------------------------------------------------------------------------

def transacoes_lista(request):
    from django.db.models import Min, Max

    # --- parâmetros do filtro ---
    ano_sel    = request.GET.get('ano',         '').strip()
    mes_sel    = request.GET.get('mes',         '').strip()
    membro_sel = request.GET.get('membro',      '').strip()
    inst_sel   = request.GET.get('instituicao', '').strip()
    conta_sel  = request.GET.get('conta',       '').strip()
    busca      = request.GET.get('q',           '').strip()

    order_sel = request.GET.get('order', 'data').strip()
    dir_sel   = request.GET.get('dir',   'desc').strip()

    _order_map = {
        'data':      'data',
        'tipo':      'tipo',
        'descricao': 'descricao',
        'conta':     'extrato__conta__instituicao__nome',
        'valor':     'valor',
        'categoria': 'categoria__nome',
    }
    order_field = _order_map.get(order_sel, 'data')
    if dir_sel == 'desc':
        order_field = f'-{order_field}'

    qs = (
        Transacao.objects
        .select_related('extrato__conta__instituicao', 'extrato__conta__membro', 'categoria')
        .order_by(order_field, '-pk')
    )

    if ano_sel:
        qs = qs.filter(data__year=ano_sel)
    if mes_sel:
        qs = qs.filter(data__month=mes_sel)
    if membro_sel:
        qs = qs.filter(extrato__conta__membro__pk=membro_sel)
    if inst_sel:
        qs = qs.filter(extrato__conta__instituicao__pk=inst_sel)
    if conta_sel:
        qs = qs.filter(extrato__conta__pk=conta_sel)
    if busca:
        qs = qs.filter(descricao__icontains=busca)

    # totais (calcula sobre o qs filtrado)
    total_credito = sum(t.valor for t in qs if t.valor > 0)
    total_debito  = sum(t.valor for t in qs if t.valor < 0)

    # opções dos filtros
    anos_disponiveis = (
        Transacao.objects.dates('data', 'year', order='DESC')
    )

    return render(request, 'conta_corrente/transacoes/lista.html', {
        'transacoes':        qs,
        'total_credito':     total_credito,
        'total_debito':      total_debito,
        'total_liquido':     total_credito + total_debito,
        # dropdowns
        'membros':           Membro.objects.order_by('nome'),
        'instituicoes':      InstituicaoFinanceira.objects.order_by('nome'),
        'anos_disponiveis':  anos_disponiveis,
        # selecionados
        'ano_sel':           ano_sel,
        'mes_sel':           mes_sel,
        'membro_sel':        membro_sel,
        'inst_sel':          inst_sel,
        'conta_sel':         conta_sel,
        'busca':             busca,
        'order_sel':         order_sel,
        'dir_sel':           dir_sel,
        'meses': [
            (1,'Jan'),(2,'Fev'),(3,'Mar'),(4,'Abr'),(5,'Mai'),(6,'Jun'),
            (7,'Jul'),(8,'Ago'),(9,'Set'),(10,'Out'),(11,'Nov'),(12,'Dez'),
        ],
    })
