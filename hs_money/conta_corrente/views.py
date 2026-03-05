from __future__ import annotations

import re
import hashlib
from datetime import date
from io import BytesIO
from pathlib import Path
from itertools import groupby

from django import forms
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.conf import settings

from unidecode import unidecode

from hs_money.core.models import Membro, InstituicaoFinanceira, Categoria
from hs_money.conta_corrente.models import ContaCorrente, Extrato, Transacao
from hs_money.conta_corrente.services.importar import importar_arquivo_ofx, hash_arquivo_ofx
from hs_money.conta_corrente.services.importar_pdf_caixa import importar_arquivo_pdf_caixa


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


class TransacaoManualForm(forms.Form):
    conta = forms.ModelChoiceField(
        queryset=ContaCorrente.objects.select_related('instituicao', 'membro').order_by('membro__nome', 'numero'),
        label='Conta',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    data = forms.DateField(
        label='Data',
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
    )
    tipo = forms.CharField(
        label='Tipo', max_length=100, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PIX, TED, DÉBITO…'}),
    )
    descricao = forms.CharField(
        label='Descrição', max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    valor = forms.DecimalField(
        label='Valor', max_digits=12, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        help_text='Negativo para débito, positivo para crédito.',
    )
    categoria = forms.ModelChoiceField(
        queryset=Categoria.objects.order_by('nivel', 'nome'),
        required=False, label='Categoria',
        widget=forms.Select(attrs={'class': 'form-select'}),
        empty_label='— sem categoria —',
    )
    membros = forms.ModelMultipleChoiceField(
        queryset=Membro.objects.order_by('nome'),
        required=False, label='Membros',
        widget=forms.CheckboxSelectMultiple(),
    )


def index(request):
    return redirect('conta_corrente:conta_lista')


# ---------------------------------------------------------------------------
# Extratos no disco → listagem para processamento
# ---------------------------------------------------------------------------

def _sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def listar_extratos_disco(request):
    """
    Varre DADOS_DIR/conta_corrente/**/*.ofx e *.pdf e mostra quais já foram
    importados (via Extrato.arquivo_hash) e quais ainda estão pendentes.
    """
    dados_dir = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    raiz_cc   = dados_dir / 'conta_corrente'

    # hashes já importados — set para lookup O(1)
    hashes_importados = set(Extrato.objects.values_list('arquivo_hash', flat=True))

    arquivos = []
    if raiz_cc.exists():
        arquivos = sorted(
            list(raiz_cc.rglob('*.ofx')) + list(raiz_cc.rglob('*.pdf'))
        )

    itens = []
    for arq in arquivos:
        ext = arq.suffix.lower()
        try:
            raw = arq.read_bytes()
            if ext == '.ofx':
                sha = hash_arquivo_ofx(raw)
            else:  # pdf — hash binário direto
                sha = hashlib.sha1(raw).hexdigest()
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
            'tipo':       arq.suffix.upper().lstrip('.'),
            'membro':     membro_slug.replace('-', ' ').title(),
            'ano':        ano,
            'banco':      banco_slug.replace('-', ' ').title(),
            'importado':  sha in hashes_importados,
            'tamanho_kb': round(len(raw) / 1024, 1) if raw else 0,
        })

<<<<<<< HEAD
    grupos_raw = {}
=======
    # ---  montar estrutura grupos_raw: {membro: {ano: {banco: [items]}}}  ---
    grupos_raw: dict = {}
>>>>>>> bug-de-extrato-pendente
    for item in itens:
        g1 = grupos_raw.setdefault(item['membro'], {})
        g2 = g1.setdefault(item['ano'], {})
        g2.setdefault(item['banco'], []).append(item)

<<<<<<< HEAD
    # Sort anos descending (mais recente primeiro)
    grupos = {
        membro: dict(sorted(anos.items(), reverse=True))
        for membro, anos in grupos_raw.items()
    }
=======
    ano_atual = str(date.today().year)

    # converte para lista ordenada; ano mais recente primeiro
    grupos = []
    for membro, anos_dict in sorted(grupos_raw.items()):
        anos = []
        for ano, bancos_dict in sorted(anos_dict.items(), reverse=True):
            todos_itens = [i for lst in bancos_dict.values() for i in lst]
            tem_pendente = any(not i['importado'] for i in todos_itens)
            bancos = [
                {'banco': banco, 'itens': lst}
                for banco, lst in bancos_dict.items()
            ]
            anos.append({'ano': ano, 'bancos': bancos, 'tem_pendente': tem_pendente})
        grupos.append({'membro': membro, 'anos': anos})
>>>>>>> bug-de-extrato-pendente

    pendentes = sum(1 for i in itens if not i['importado'])

    return render(request, 'conta_corrente/extratos/lista_disco.html', {
        'grupos':      grupos,
        'total':       len(itens),
        'pendentes':   pendentes,
<<<<<<< HEAD
        'ano_atual':   str(date.today().year),
=======
        'ano_atual':   ano_atual,
>>>>>>> bug-de-extrato-pendente
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
        ext = caminho.suffix.lower()
        if not caminho.exists() or ext not in ('.ofx', '.pdf'):
            resultados.append({
                'arquivo':  rel,
                'status':   'erro',
                'erro':     'Arquivo não encontrado ou formato não suportado (use .ofx ou .pdf).',
                'novos':    0,
                'pulados':  0,
                'periodo':  '',
                'conta_str': '',
                'avisos':   [],
            })
            continue
        if ext == '.pdf':
            r = importar_arquivo_pdf_caixa(caminho, dry_run=dry_run)
        else:
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
# Excluir arquivos de extrato do disco
# ---------------------------------------------------------------------------

def excluir_extratos_disco(request):
    """POST: exclui arquivos de extrato selecionados e seus registros de Extrato no banco."""
    if request.method != 'POST':
        return redirect('conta_corrente:listar_extratos')

    dados_dir    = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    caminhos_rel = request.POST.getlist('caminhos')

    excluidos  = []
    nao_encontrados = []
    erros      = []

    for rel in caminhos_rel:
        caminho = (dados_dir / rel).resolve()
        # Garante que o arquivo está dentro de dados_dir (segurança)
        try:
            caminho.relative_to(dados_dir.resolve())
        except ValueError:
            erros.append(rel)
            continue

        if not caminho.exists():
            nao_encontrados.append(rel)
            continue

        try:
            # Remove registro de Extrato do banco (pelo hash do arquivo)
            raw = caminho.read_bytes()
            arq_hash = hashlib.sha1(raw).hexdigest()
            from hs_money.conta_corrente.models import Extrato
            Extrato.objects.filter(arquivo_hash=arq_hash).delete()

            caminho.unlink()
            excluidos.append(rel)
        except Exception as exc:
            erros.append(f"{rel}: {exc}")

    if excluidos:
        messages.success(request, f"{len(excluidos)} arquivo(s) excluído(s) com sucesso.")
    if nao_encontrados:
        messages.warning(request, f"{len(nao_encontrados)} arquivo(s) não encontrado(s) no disco.")
    if erros:
        messages.error(request, f"Erro ao excluir {len(erros)} arquivo(s): " + ' | '.join(erros))

    return redirect('conta_corrente:listar_extratos')
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', unidecode((s or '').lower().strip())).strip('_')


def _normalizar_nome(filename: str) -> str:
    """Fallback: limpa o nome original caso seja necessário."""
    stem, _, ext = filename.rpartition('.')
    stem = unidecode(stem)
    stem = re.sub(r'[^a-zA-Z0-9]+', '_', stem).strip('_').lower()
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


_MESES_PT = {
    'janeiro': '01', 'fevereiro': '02', 'março': '03', 'marco': '03',
    'abril': '04', 'maio': '05', 'junho': '06', 'julho': '07',
    'agosto': '08', 'setembro': '09', 'outubro': '10',
    'novembro': '11', 'dezembro': '12',
}


def _detectar_pdf_caixa(raw: bytes) -> dict:
    """Lê o cabeçalho do PDF da Caixa e retorna {'ano', 'mm', 'cliente'}.

    Faz uma única passagem pelo PDF para evitar abrir duas vezes.
    """
    result = {'ano': '', 'mm': '', 'cliente': ''}
    try:
        import pdfplumber
        from io import BytesIO
        with pdfplumber.open(BytesIO(raw)) as pdf:
            texto = ''
            for pg in pdf.pages:
                texto += (pg.extract_text(x_tolerance=3, y_tolerance=3) or '') + '\n'
                if texto.count('\n') > 60:
                    break
    except Exception:
        return result

    # Período: "Mês: Julho/2025" ou "Período: Novembro/2024"
    m = re.search(
        r'(?:M[eê]s|Per[ií]odo)[:\s]+([A-Za-z\u00e7\u00e3\u00e1\u00e0\u00e2\u00e9\u00ea\u00f3\u00f4\u00fa]+)/?\s*(\d{4})',
        texto, re.IGNORECASE,
    )
    if m:
        from unidecode import unidecode
        mes_nome_ascii = unidecode(m.group(1).lower().strip())
        mm = _MESES_PT.get(mes_nome_ascii, '')
        if mm:
            result['ano'] = m.group(2)
            result['mm']  = mm

    # Cliente: "Cliente: DALTON EIDI HISAYASU  Conta:..."
    mc = re.search(r'Cliente:\s*(.+?)(?:\s{2,}|Conta:|$)', texto, re.IGNORECASE)
    if mc:
        result['cliente'] = mc.group(1).strip()

    return result


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
    membros      = Membro.objects.all()
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
                'is_ofx': ext == 'ofx',
                'is_pdf': ext == 'pdf'}

        ofx_data = {}
        pdf_data = {}
        if ext == 'ofx':
            ofx_data = _detectar_ofx(raw)
        elif ext == 'pdf':
            pdf_data = _detectar_pdf_caixa(raw)

        inst   = inst_obj_force   or _match_instituicao(ofx_data.get('org', ''), ofx_data.get('fid', ''))
        membro = membro_obj_force or _match_membro(ofx_data.get('acctid', ''), inst)

        if not inst and ext == 'pdf':
            # Para PDFs da Caixa, tenta casar pelo código da instituição
            inst = InstituicaoFinanceira.objects.filter(nome__icontains='caixa').first()

        if not membro and pdf_data.get('cliente'):
            # Tenta casar o nome do cliente no PDF com os membros cadastrados
            from unidecode import unidecode as _ud
            slug_cliente = _slug(_ud(pdf_data['cliente']))
            for m_obj in Membro.objects.all():
                slug_m = _slug(_ud(m_obj.nome))
                if slug_m and slug_m in slug_cliente:
                    membro = m_obj
                    break

        if not inst:
            info['status'] = 'erro'
            info['erro']   = 'Instituição não detectada. Selecione manualmente.'
            resultados.append(info)
            continue

        if not membro:
            info['status'] = 'aviso'
            info['erro']   = 'Membro não detectado — arquivo salvo sem titular.'

        if ext == 'pdf' and pdf_data.get('ano') and pdf_data.get('mm'):
            ano, mm = pdf_data['ano'], pdf_data['mm']
        else:
            ano, mm = _detectar_ano_mes(nome_original, ofx_data.get('dtstart', ''))
        membro_slug = _slug(membro.nome) if membro else 'sem_membro'
        inst_slug   = inst.codigo or _slug(inst.nome)
        nome_norm   = f"{ano}{mm}.{ext}" if ext else f"{ano}{mm}"

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
    return redirect(reverse('conta_corrente:transacoes_lista') + f'?conta={pk}')


def transacoes_bulk_action(request):
    """Ação em massa: ocultar, mostrar ou categorizar transações."""
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    ids    = request.POST.getlist('ids')
    action = request.POST.get('action', '')
    voltar = request.POST.get('next', reverse('conta_corrente:transacoes_lista'))
    if ids and action in ('ocultar', 'mostrar'):
        Transacao.objects.filter(pk__in=ids).update(oculta=(action == 'ocultar'))
    elif ids and action == 'categorizar':
        categoria_id = request.POST.get('categoria_id', '').strip()
        if categoria_id:
            cat = Categoria.objects.filter(pk=categoria_id).first()
            if cat:
                Transacao.objects.filter(pk__in=ids).update(categoria=cat)
        else:
            Transacao.objects.filter(pk__in=ids).update(categoria=None)
    elif ids and action == 'atribuir_membros':
        membro_ids = request.POST.getlist('membro_ids')
        for t in Transacao.objects.filter(pk__in=ids):
            if membro_ids:
                t.membros.set(membro_ids)
            else:
                t.membros.clear()
    return redirect(voltar)


# ---------------------------------------------------------------------------
# Lista GLOBAL de transações (todas as contas)
def transacao_toggle_oculta(request, pk):
    """Toggle do campo oculta de uma transação (POST)."""
    if request.method != 'POST':
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['POST'])
    t = get_object_or_404(Transacao, pk=pk)
    t.oculta = not t.oculta
    t.save(update_fields=['oculta'])
    # volta para onde veio, mantendo todos os query params
    voltar = request.POST.get('next', reverse('conta_corrente:transacoes_lista'))
    return redirect(voltar)


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
    cat_sel    = request.GET.get('categoria',   '').strip()
    atrib_sel  = request.GET.get('atribuicao',  '').strip()
    tab_sel    = request.GET.get('tab',         'visiveis').strip()

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

    qs_base = (
        Transacao.objects
        .select_related('extrato__conta__instituicao', 'extrato__conta__membro', 'categoria')
        .prefetch_related('membros')
        .order_by(order_field, '-pk')
    )

    if ano_sel:
        qs_base = qs_base.filter(data__year=ano_sel)
    if mes_sel:
        qs_base = qs_base.filter(data__month=mes_sel)
    if membro_sel:
        qs_base = qs_base.filter(extrato__conta__membro__pk=membro_sel)
    if inst_sel:
        qs_base = qs_base.filter(extrato__conta__instituicao__pk=inst_sel)
    if conta_sel:
        qs_base = qs_base.filter(extrato__conta__pk=conta_sel)
    if busca:
        qs_base = qs_base.filter(descricao__icontains=busca)
    if cat_sel == '0':
        qs_base = qs_base.filter(categoria__isnull=True)
    elif cat_sel:
        # filtra pela categoria escolhida OU qualquer subcategoria dela
        cat_obj = Categoria.objects.filter(pk=cat_sel).first()
        if cat_obj:
            if cat_obj.nivel == 1:
                sub_ids = list(cat_obj.subcategorias.values_list('pk', flat=True))
                qs_base = qs_base.filter(categoria__pk__in=[cat_obj.pk] + sub_ids)
            else:
                qs_base = qs_base.filter(categoria__pk=cat_obj.pk)
    if atrib_sel == '0':
        qs_base = qs_base.filter(membros__isnull=True)

    qs_visiveis = qs_base.filter(oculta=False)
    qs_ocultas  = qs_base.filter(oculta=True)

    # totais sobre as visíveis
    total_credito = sum(t.valor for t in qs_visiveis if t.valor > 0)
    total_debito  = sum(t.valor for t in qs_visiveis if t.valor < 0)

    # totais sobre as ocultas
    total_credito_ocultas = sum(t.valor for t in qs_ocultas if t.valor > 0)
    total_debito_ocultas  = sum(t.valor for t in qs_ocultas if t.valor < 0)

    anos_disponiveis = Transacao.objects.dates('data', 'year', order='DESC')

    return render(request, 'conta_corrente/transacoes/lista.html', {
        'transacoes':          qs_visiveis,
        'transacoes_ocultas':  qs_ocultas,
        'total_credito':       total_credito,
        'total_debito':        total_debito,
        'total_liquido':       total_credito + total_debito,
        'total_credito_ocultas': total_credito_ocultas,
        'total_debito_ocultas':  total_debito_ocultas,
        'total_liquido_ocultas': total_credito_ocultas + total_debito_ocultas,
        'membros':             Membro.objects.all(),
        'instituicoes':        InstituicaoFinanceira.objects.order_by('nome'),
        'anos_disponiveis':    anos_disponiveis,
        'categorias':          Categoria.objects.filter(nivel=1).prefetch_related('subcategorias').order_by('nome'),
        'cat_sel':             cat_sel,
        'atrib_sel':           atrib_sel,
        'ano_sel':             ano_sel,
        'mes_sel':             mes_sel,
        'membro_sel':          membro_sel,
        'inst_sel':            inst_sel,
        'conta_sel':           conta_sel,
        'busca':               busca,
        'tab_sel':             tab_sel,
        'order_sel':           order_sel,
        'dir_sel':             dir_sel,
        'meses': [
            (1,'Jan'),(2,'Fev'),(3,'Mar'),(4,'Abr'),(5,'Mai'),(6,'Jun'),
            (7,'Jul'),(8,'Ago'),(9,'Set'),(10,'Out'),(11,'Nov'),(12,'Dez'),
        ],
    })


# ---------------------------------------------------------------------------
# Criar transação manual
# ---------------------------------------------------------------------------

def _get_or_create_extrato_manual(conta: 'ContaCorrente', data: 'date') -> 'Extrato':
    """Encontra ou cria um Extrato 'manual' para a conta no mês/ano da data."""
    import calendar
    first = data.replace(day=1)
    last  = data.replace(day=calendar.monthrange(data.year, data.month)[1])
    extrato, _ = Extrato.objects.get_or_create(
        conta=conta,
        fonte_arquivo='manual',
        data_inicio=first,
        data_fim=last,
        defaults={'arquivo_hash': ''},
    )
    return extrato


def transacao_criar(request):
    """Cria uma transação manualmente (sem arquivo de extrato)."""
    initial = {}
    if request.GET.get('conta'):
        initial['conta'] = request.GET.get('conta')

    form = TransacaoManualForm(request.POST or None, initial=initial)

    if form.is_valid():
        cd      = form.cleaned_data
        extrato = _get_or_create_extrato_manual(cd['conta'], cd['data'])

        # gera hash_linha a partir do conteúdo
        raw_hash   = f"{cd['conta'].pk}|{cd['data']}|{cd['descricao']}|{cd['valor']}"
        hash_linha = hashlib.sha1(raw_hash.encode()).hexdigest()

        # resolve hash_ordem para evitar colisão de unique constraint
        hash_ordem = 1
        while Transacao.objects.filter(
            extrato=extrato, hash_linha=hash_linha, hash_ordem=hash_ordem
        ).exists():
            hash_ordem += 1

        t = Transacao.objects.create(
            extrato=extrato,
            data=cd['data'],
            tipo=cd['tipo'],
            descricao=cd['descricao'],
            valor=cd['valor'],
            categoria=cd['categoria'],
            hash_linha=hash_linha,
            hash_ordem=hash_ordem,
        )
        if cd['membros']:
            t.membros.set(cd['membros'])

        messages.success(request, f'Transação "{t.descricao}" criada com sucesso.')
        voltar = request.POST.get('next') or reverse('conta_corrente:transacoes_lista')
        return redirect(voltar)

    return render(request, 'conta_corrente/transacoes/form.html', {
        'form':  form,
        'titulo': 'Nova Transação Manual',
        'next':  request.GET.get('next', ''),
    })
