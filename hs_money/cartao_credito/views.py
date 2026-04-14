from __future__ import annotations
from django.views.decorators.http import require_POST
from django.http import HttpResponseRedirect
# Inline annotation editing for credit card transaction
@require_POST
def transacao_anotacao(request, pk):
    """Edita a anotação de uma transação de cartão (inline)."""
    anotacao = request.POST.get('anotacao', '').strip()
    if anotacao:
        anotacao = anotacao[0].upper() + anotacao[1:] if len(anotacao) > 1 else anotacao.upper()
    transacao = get_object_or_404(TransacaoCartao, pk=pk)
    transacao.anotacao = anotacao
    transacao.save(update_fields=['anotacao'])
    next_url = request.POST.get('next') or reverse('cartao_credito:transacoes_lista')
    return HttpResponseRedirect(next_url)


import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pdfplumber

from django import forms
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from django.urls import reverse

from hs_money.cartao_credito.models import Cartao, FaturaCartao, Transacao as TransacaoCartao
from hs_money.cartao_credito.parsers.bb.dados_fatura import parse_dados_fatura
from hs_money.cartao_credito.services.importar import importar_arquivo_pdf_bb, hash_pdf
from hs_money.cartao_credito.services.parcelados import (
    agrupar_parcelados,
    _extract_num_total,
    _tem_padrao_parcelado,
    _try_normalizar,
)
from django.db.models import Q
from decimal import Decimal
from collections import defaultdict
import calendar
from hs_money.core.models import Membro, InstituicaoFinanceira, Categoria


# ---------------------------------------------------------------------------
# Form
# ---------------------------------------------------------------------------

class CartaoForm(forms.ModelForm):
    class Meta:
        model  = Cartao
        fields = ['instituicao', 'bandeira', 'cartao_final', 'membro', 'ativo']
        widgets = {
            'instituicao':  forms.Select(attrs={'class': 'form-select'}),
            'bandeira':     forms.TextInput(attrs={
                                'class': 'form-control',
                                'placeholder': 'VISA, MASTERCARD, ELO…',
                            }),
            'cartao_final': forms.TextInput(attrs={
                                'class': 'form-control',
                                'placeholder': '6462',
                                'maxlength': '8',
                            }),
            'membro':       forms.Select(attrs={'class': 'form-select'}),
            'ativo':        forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ---------------------------------------------------------------------------
# Index – redireciona para lista de cartões
# ---------------------------------------------------------------------------

def index(request):
    return redirect('cartao_credito:cartao_lista')


# ---------------------------------------------------------------------------
# CRUD de Cartões
# ---------------------------------------------------------------------------

def cartao_lista(request):
    cartoes = (
        Cartao.objects
        .select_related('instituicao', 'membro')
        .order_by('membro__nome', 'instituicao__nome', 'cartao_final')
    )

    grupos_raw: dict = {}
    for c in cartoes:
        membro_nome = c.membro.nome if c.membro else '— Sem titular —'
        grupos_raw.setdefault(membro_nome, []).append(c)

    grupos = [{'membro': m, 'cartoes': lst} for m, lst in sorted(grupos_raw.items())]

    return render(request, 'cartao_credito/cartoes/lista.html', {
        'grupos': grupos,
    })


def cartao_criar(request):
    if request.method == 'POST':
        form = CartaoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cartão cadastrado com sucesso.')
            return redirect('cartao_credito:cartao_lista')
    else:
        form = CartaoForm()
    return render(request, 'cartao_credito/cartoes/form.html', {
        'form':   form,
        'titulo': 'Novo Cartão de Crédito',
    })


def cartao_editar(request, pk):
    cartao = get_object_or_404(Cartao, pk=pk)
    if request.method == 'POST':
        form = CartaoForm(request.POST, instance=cartao)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cartão atualizado.')
            return redirect('cartao_credito:cartao_lista')
    else:
        form = CartaoForm(instance=cartao)
    return render(request, 'cartao_credito/cartoes/form.html', {
        'form':   form,
        'titulo': f'Editar Cartão ****{cartao.cartao_final}',
        'cartao': cartao,
    })


# ---------------------------------------------------------------------------
# Upload de fatura PDF
# ---------------------------------------------------------------------------

def _slug_cc(s: str) -> str:
    """Slug simples para nomes de pasta."""
    try:
        from unidecode import unidecode
        s = unidecode(s)
    except ImportError:
        pass
    return re.sub(r'[^a-z0-9]+', '_', s.lower().strip()).strip('_')


def upload_fatura(request, cartao_pk=None):
    cartao_selecionado = get_object_or_404(Cartao, pk=cartao_pk) if cartao_pk else None
    cartoes  = Cartao.objects.select_related('membro', 'instituicao').order_by('membro__nome', 'cartao_final')
    membros  = Membro.objects.order_by('nome')

    if request.method != 'POST':
        return render(request, 'cartao_credito/upload/form.html', {
            'cartoes':            cartoes,
            'membros':            membros,
            'cartao_selecionado': cartao_selecionado,
        })

    arquivos      = request.FILES.getlist('arquivos')
    cartao_pk_val = request.POST.get('cartao') or (cartao_pk and str(cartao_pk))
    membro_force  = request.POST.get('membro')
    dados_dir     = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')

    cartao_obj_force = Cartao.objects.filter(pk=cartao_pk_val).first() if cartao_pk_val else None
    membro_obj_force = Membro.objects.filter(pk=membro_force).first() if membro_force else None

    resultados = []

    for f in arquivos:
        nome_original = f.name
        ext = nome_original.rsplit('.', 1)[-1].lower() if '.' in nome_original else ''
        raw = f.read()

        info: dict = {
            'nome_original': nome_original,
            'status':        'ok',
            'erro':          '',
            'caminho':       '',
            'nome_norm':     '',
            'cartao_str':    '',
            'membro':        '',
            'competencia':   '',
        }

        if ext != 'pdf':
            info['status'] = 'erro'
            info['erro']   = 'Somente arquivos .pdf são aceitos.'
            resultados.append(info)
            continue

        # --- Parsear o PDF para extrair cartao_final + competência ---
        cartao_final = None
        competencia  = None
        try:
            import io
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                texto = "\n".join(p.extract_text() or '' for p in pdf.pages)
            dados = parse_dados_fatura(texto, raw)
            cartao_final = dados.cartao_final
            competencia  = dados.competencia
        except Exception as exc:
            info['erro'] = f'Aviso: não foi possível parsear PDF — {exc}'
            info['status'] = 'aviso'

        # Se cartão foi selecionado no form, usa ele como referência para membro/pasta
        cartao_ref = cartao_obj_force
        if not cartao_ref and cartao_final:
            cartao_ref = Cartao.objects.filter(cartao_final=cartao_final).first()

        membro_ref = membro_obj_force
        if not membro_ref and cartao_ref and cartao_ref.membro:
            membro_ref = cartao_ref.membro

        # Se não encontrou nada, falha
        if not membro_ref and not cartao_final:
            info['status'] = 'erro'
            info['erro']   = 'Não foi possível detectar o cartão/membro. Selecione manualmente.'
            resultados.append(info)
            continue

        membro_slug = _slug_cc(membro_ref.nome) if membro_ref else 'sem_membro'
        final       = (cartao_obj_force.cartao_final if cartao_obj_force else cartao_final) or 'xxxx'

        if competencia:
            ano  = str(competencia.year)
            mm   = f'{competencia.month:02d}'
        else:
            hoje = date.today()
            ano, mm = str(hoje.year), f'{hoje.month:02d}'

        nome_norm   = f"{final}-{ano}-{mm}.pdf"
        destino     = dados_dir / 'cartao_credito' / membro_slug / ano
        destino.mkdir(parents=True, exist_ok=True)
        arquivo_path = destino / nome_norm

        if arquivo_path.exists():
            sha_novo  = hash_pdf(raw)
            sha_exist = hash_pdf(arquivo_path.read_bytes())
            if sha_novo == sha_exist:
                info['status']     = 'ignorado'
                info['erro']       = 'Arquivo idêntico já existe.'
                info['caminho']    = str(arquivo_path.relative_to(dados_dir))
                info['nome_norm']  = nome_norm
                info['competencia'] = str(competencia) if competencia else ''
                resultados.append(info)
                continue
            # nome conflita mas conteúdo diferente → adiciona sufixo
            stem = nome_norm.rstrip('.pdf')
            i = 2
            while arquivo_path.exists():
                arquivo_path = destino / f"{final}-{ano}-{mm}_{i}.pdf"
                i += 1

        arquivo_path.write_bytes(raw)

        info['nome_norm']    = arquivo_path.name
        info['caminho']      = str(arquivo_path.relative_to(dados_dir))
        info['cartao_str']   = str(cartao_ref) if cartao_ref else (f'****{final}' if final else '—')
        info['membro']       = membro_ref.nome if membro_ref else '—'
        info['competencia']  = f'{ano}/{mm}'
        resultados.append(info)

    return render(request, 'cartao_credito/upload/resultado.html', {
        'resultados':         resultados,
        'cartao_selecionado': cartao_selecionado,
    })


# ---------------------------------------------------------------------------
# Listagem de faturas no disco
# ---------------------------------------------------------------------------

def listar_faturas_disco(request):
    """
    Varre DADOS_DIR/cartao_credito/**/*.pdf e mostra quais já foram
    importados (via FaturaCartao.arquivo_hash) e quais estão pendentes.
    """
    import re as _re
    dados_dir = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    raiz_cc   = dados_dir / 'cartao_credito'

    hashes_importados = set(FaturaCartao.objects.values_list('arquivo_hash', flat=True))

    # índice (cartao_final, competencia_date) → fatura, para detectar arquivos
    # renomeados cujo hash ainda não foi sincronizado no banco
    _faturas_por_cartao_comp: dict = {}
    for f in FaturaCartao.objects.select_related('cartao'):
        _faturas_por_cartao_comp[(f.cartao.cartao_final, f.competencia)] = f

    _NOME_PADRAO = _re.compile(r'^(\d+)-(\d{4})-(\d{2})(?:_\d+)?\.pdf$', _re.I)

    def _inferir_fatura_por_nome(nome: str):
        """Retorna FaturaCartao se o nome bate com padrão cartao_final-YYYY-MM.pdf."""
        m = _NOME_PADRAO.match(nome)
        if not m:
            return None
        cartao_final, ano, mes = m.group(1), int(m.group(2)), int(m.group(3))
        from datetime import date as _date
        comp = _date(ano, mes, 1)
        return _faturas_por_cartao_comp.get((cartao_final, comp))

    arquivos = sorted(raiz_cc.rglob('*.pdf')) if raiz_cc.exists() else []

    itens = []
    for arq in arquivos:
        try:
            raw = arq.read_bytes()
            sha = hash_pdf(raw)
        except OSError:
            raw, sha = b'', ''

        partes = arq.relative_to(raiz_cc).parts
        membro_slug = partes[0] if len(partes) > 1 else '—'
        ano         = partes[1] if len(partes) > 2 else '—'
        caminho_rel = str(arq.relative_to(dados_dir))

        importado = sha in hashes_importados

        if not importado and sha:
            # Arquivo renomeado: hash não bate mas existe fatura com mesmo cartão/mês
            fatura_match = _inferir_fatura_por_nome(arq.name)
            if fatura_match:
                # Sincroniza o hash no banco silenciosamente
                fatura_match.arquivo_hash = sha
                fatura_match.fonte_arquivo = str(arq)
                fatura_match.save(update_fields=['arquivo_hash', 'fonte_arquivo'])
                hashes_importados.add(sha)
                importado = True
            else:
                # Arquivo original não normalizado: verifica se há duplicata com
                # mesmo conteúdo (mesmo hash) no mesmo diretório já importada
                for irmao in arq.parent.iterdir():
                    if irmao == arq or irmao.suffix.lower() != '.pdf':
                        continue
                    try:
                        if hash_pdf(irmao.read_bytes()) == sha:
                            importado = True
                            break
                    except OSError:
                        pass

        itens.append({
            'caminho':    caminho_rel,
            'nome':       arq.name,
            'membro':     membro_slug.replace('-', ' ').replace('_', ' ').title(),
            'ano':        ano,
            'importado':  importado,
            'tamanho_kb': round(len(raw) / 1024, 1) if raw else 0,
        })

    # Estrutura: lista de {membro, anos: [{ano, itens, tem_pendente}]}
    grupos_raw: dict = {}
    for item in itens:
        g1 = grupos_raw.setdefault(item['membro'], {})
        g1.setdefault(item['ano'], []).append(item)

    ano_atual = str(date.today().year)

    grupos = []
    for membro, anos_dict in sorted(grupos_raw.items()):
        anos = []
        for ano, lista in sorted(anos_dict.items(), reverse=True):
            tem_pendente = any(not i['importado'] for i in lista)
            anos.append({'ano': ano, 'itens': lista, 'tem_pendente': tem_pendente})
        grupos.append({'membro': membro, 'anos': anos})

    pendentes = sum(1 for i in itens if not i['importado'])

    return render(request, 'cartao_credito/faturas/lista_disco.html', {
        'grupos':      grupos,
        'total':       len(itens),
        'pendentes':   pendentes,
        'ano_atual':   ano_atual,
        'raiz_existe': raiz_cc.exists(),
    })


# ---------------------------------------------------------------------------
# Processar faturas selecionadas
# ---------------------------------------------------------------------------

def processar_faturas(request):
    if request.method != 'POST':
        return redirect('cartao_credito:listar_faturas')

    dados_dir    = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    caminhos_rel = request.POST.getlist('caminhos')
    dry_run      = bool(request.POST.get('dry_run'))

    resultados = []
    for rel in caminhos_rel:
        caminho = (dados_dir / rel).resolve()
        if not caminho.exists() or caminho.suffix.lower() != '.pdf':
            resultados.append({
                'arquivo': rel, 'status': 'erro',
                'erro': 'Arquivo não encontrado ou não é PDF.',
                'novos': 0, 'pulados': 0, 'competencia': '', 'cartao_str': '', 'avisos': [],
            })
            continue

        r = importar_arquivo_pdf_bb(caminho, dry_run=dry_run)
        resultados.append({
            'arquivo':      r.arquivo,
            'status':       r.status,
            'erro':         r.erro,
            'novos':        r.novos,
            'pulados':      r.pulados,
            'competencia':  r.competencia,
            'cartao_str':   r.cartao_str,
            'cartao_criado': r.cartao_criado,
            'avisos':       r.avisos,
            'dry_run':      dry_run,
        })

    totais = {
        'novos':   sum(r['novos']   for r in resultados),
        'pulados': sum(r['pulados'] for r in resultados),
        'erros':   sum(1 for r in resultados if r['status'] == 'erro'),
    }

    return render(request, 'cartao_credito/faturas/resultado.html', {
        'resultados':  resultados,
        'totais':      totais,
        'dry_run':     dry_run,
        'caminhos':    caminhos_rel,
    })


# ---------------------------------------------------------------------------
# Excluir faturas do disco (e limpa arquivo_hash no banco)
# ---------------------------------------------------------------------------

def excluir_faturas_disco(request):
    """POST: exclui arquivos PDF selecionados e seus registros de FaturaCartao no banco."""
    if request.method != 'POST':
        return redirect('cartao_credito:listar_faturas')

    dados_dir    = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    caminhos_rel = request.POST.getlist('caminhos')

    excluidos       = []
    nao_encontrados = []
    erros           = []

    for rel in caminhos_rel:
        caminho = (dados_dir / rel).resolve()
        try:
            caminho.relative_to(dados_dir.resolve())
        except ValueError:
            erros.append(rel)
            continue

        if not caminho.exists():
            nao_encontrados.append(rel)
            continue

        try:
            raw = caminho.read_bytes()
            arq_hash = hash_pdf(raw)
            FaturaCartao.objects.filter(arquivo_hash=arq_hash).delete()
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

    return redirect('cartao_credito:listar_faturas')


# ---------------------------------------------------------------------------
# Normalizar nomes de arquivos → {cartao_final}-{YYYY}-{MM}.pdf
# ---------------------------------------------------------------------------

def normalizar_faturas_disco(request):
    """POST: tenta parsear cada PDF selecionado e renomeia para o
    formato padrão {cartao_final}-{YYYY}-{MM}.pdf."""
    if request.method != 'POST':
        return redirect('cartao_credito:listar_faturas')

    dados_dir    = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    caminhos_rel = request.POST.getlist('caminhos')

    renomeados = []
    ja_ok      = []
    erros      = []

    for rel in caminhos_rel:
        caminho = (dados_dir / rel).resolve()
        if not caminho.exists() or caminho.suffix.lower() != '.pdf':
            erros.append(f"{caminho.name}: não encontrado ou não é PDF")
            continue

        try:
            raw = caminho.read_bytes()
            with pdfplumber.open(caminho) as pdf:
                texto = "\n".join(p.extract_text() or '' for p in pdf.pages)

            dados = parse_dados_fatura(texto, raw)

            if not dados.cartao_final or not dados.competencia:
                erros.append(f"{caminho.name}: não foi possível extrair cartão/competência")
                continue

            comp      = dados.competencia
            novo_nome = f"{dados.cartao_final}-{comp.year}-{comp.month:02d}.pdf"
            novo_caminho = caminho.parent / novo_nome

            if novo_caminho.resolve() == caminho.resolve():
                ja_ok.append(caminho.name)
                continue

            if novo_caminho.exists():
                erros.append(f"{caminho.name}: destino '{novo_nome}' já existe")
                continue

            caminho.rename(novo_caminho)
            renomeados.append(f"{caminho.name} → {novo_nome}")

        except Exception as exc:
            erros.append(f"{caminho.name}: {exc}")

    if renomeados:
        messages.success(request, f"{len(renomeados)} arquivo(s) renomeado(s): " + "; ".join(renomeados))
    if ja_ok:
        messages.info(request, f"{len(ja_ok)} arquivo(s) já estavam no formato correto.")
    if erros:
        messages.error(request, f"{len(erros)} erro(s): " + " | ".join(erros))

    return redirect('cartao_credito:listar_faturas')


# ---------------------------------------------------------------------------
# Transações – lista, toggle oculta, bulk action
# ---------------------------------------------------------------------------

MESES = [
    (1, 'Jan'), (2, 'Fev'), (3, 'Mar'), (4, 'Abr'),
    (5, 'Mai'), (6, 'Jun'), (7, 'Jul'), (8, 'Ago'),
    (9, 'Set'), (10, 'Out'), (11, 'Nov'), (12, 'Dez'),
]


def transacoes_lista(request):
    ano_sel    = request.GET.get('ano', str(date.today().year))
    mes_sel    = request.GET.get('mes', '')
    membro_sel = request.GET.get('membro', '')
    cartao_sel = request.GET.get('cartao', '')
    busca      = request.GET.get('q', '')
    cat_sel    = request.GET.get('categoria', '')
    atrib_sel  = request.GET.get('atribuicao', '')
    tab_sel    = request.GET.get('tab', '')
    order_sel  = request.GET.get('order', 'data')
    dir_sel    = request.GET.get('dir', 'desc')

    qs = (TransacaoCartao.objects
          .select_related(
              'fatura__cartao__membro',
              'fatura__cartao__instituicao',
              'categoria',
          )
          .prefetch_related('membros'))

    if ano_sel:
        qs = qs.filter(fatura__competencia__year=ano_sel)
    if mes_sel:
        qs = qs.filter(fatura__competencia__month=mes_sel)
    if membro_sel:
        qs = qs.filter(fatura__cartao__membro_id=membro_sel)
    if cartao_sel:
        qs = qs.filter(fatura__cartao_id=cartao_sel)
    if busca:
        qs = qs.filter(descricao__icontains=busca)
    if cat_sel == '0':
        qs = qs.filter(categoria__isnull=True)
    elif cat_sel:
        try:
            cat_obj = Categoria.objects.get(pk=cat_sel)
            ids = [cat_obj.pk] + list(
                cat_obj.subcategorias.values_list('pk', flat=True)
            )
            qs = qs.filter(categoria_id__in=ids)
        except Categoria.DoesNotExist:
            pass
    if atrib_sel == '0':
        qs = qs.filter(membros__isnull=True)

    order_map = {
        'data':      'data',
        'descricao': 'descricao',
        'cartao':    'fatura__cartao__cartao_final',
        'valor':     'valor',
        'categoria': 'categoria__nome',
    }
    order_db = order_map.get(order_sel, 'data')
    qs = qs.order_by(order_db if dir_sel == 'asc' else f'-{order_db}')

    qs_visiveis = qs.filter(oculta=False)
    qs_ocultas  = qs.filter(oculta=True)

    # Totals – evaluate querysets once
    lista_vis    = list(qs_visiveis)
    lista_ocult  = list(qs_ocultas)

    total_credito  = sum(t.valor for t in lista_vis   if t.valor > 0)
    total_debito   = sum(t.valor for t in lista_vis   if t.valor < 0)
    total_liquido  = total_credito + total_debito
    total_credito_ocultas = sum(t.valor for t in lista_ocult if t.valor > 0)
    total_debito_ocultas  = sum(t.valor for t in lista_ocult if t.valor < 0)
    total_liquido_ocultas = total_credito_ocultas + total_debito_ocultas

    anos_disponiveis = FaturaCartao.objects.dates('competencia', 'year', order='DESC')
    membros   = Membro.objects.order_by('ordem', 'nome')
    cartoes   = Cartao.objects.select_related('membro', 'instituicao').filter(ativo=True)

    # ── Gráfico: totais mensais (últimos 12 meses, respeita filtros membro/cartao) ──
    today = date.today()
    grafico_qs = (TransacaoCartao.objects
                  .filter(oculta=False)
                  .select_related('fatura__cartao__membro'))
    if membro_sel:
        grafico_qs = grafico_qs.filter(fatura__cartao__membro_id=membro_sel)
    if cartao_sel:
        grafico_qs = grafico_qs.filter(fatura__cartao_id=cartao_sel)
    grafico_list = list(grafico_qs)  # evaluate once

    # build list of (year, month) for last 12 months
    months_seq = []
    grafico_labels = []
    for i in range(11, -1, -1):
        total_months = today.year * 12 + today.month - 1 - i
        y, m_idx = divmod(total_months, 12)
        m = m_idx + 1
        months_seq.append((y, m))
        grafico_labels.append(f'{m:02d}/{y}')

    # per-member series (only members that appear in grafico_list)
    member_map = {}  # pk -> nome
    for t in grafico_list:
        mb = t.fatura.cartao.membro
        if mb and mb.pk not in member_map:
            member_map[mb.pk] = mb.nome
    # also include "sem membro" bucket if needed
    has_no_member = any(t.fatura.cartao.membro is None for t in grafico_list if t.valor < 0)

    COLORS = [
        'rgba(13,110,253,0.78)',
        'rgba(25,135,84,0.78)',
        'rgba(255,193,7,0.85)',
        'rgba(111,66,193,0.78)',
        'rgba(253,126,20,0.78)',
    ]
    datasets = []
    for idx, (pk, nome) in enumerate(member_map.items()):
        values = []
        for y, m in months_seq:
            total = sum(
                abs(t.valor) for t in grafico_list
                if t.fatura.cartao.membro_id == pk
                and t.fatura.competencia.year == y
                and t.fatura.competencia.month == m
                and t.valor < 0
            )
            values.append(float(total))
        datasets.append({
            'label': nome,
            'data': values,
            'backgroundColor': COLORS[idx % len(COLORS)],
            'borderRadius': 3,
        })
    if has_no_member:
        values = []
        for y, m in months_seq:
            total = sum(
                abs(t.valor) for t in grafico_list
                if t.fatura.cartao.membro is None
                and t.fatura.competencia.year == y
                and t.fatura.competencia.month == m
                and t.valor < 0
            )
            values.append(float(total))
        datasets.append({
            'label': 'Sem membro',
            'data': values,
            'backgroundColor': 'rgba(108,117,125,0.72)',
            'borderRadius': 3,
        })

    grafico_json = json.dumps({'labels': grafico_labels, 'datasets': datasets})
    categorias = (Categoria.objects
                  .filter(nivel=1)
                  .prefetch_related('subcategorias')
                  .order_by('nome'))

    context = {
        'transacoes':             lista_vis,
        'transacoes_ocultas':     lista_ocult,
        'total_credito':          total_credito,
        'total_debito':           total_debito,
        'total_liquido':          total_liquido,
        'total_credito_ocultas':  total_credito_ocultas,
        'total_debito_ocultas':   total_debito_ocultas,
        'total_liquido_ocultas':  total_liquido_ocultas,
        'membros':                membros,
        'cartoes':                cartoes,
        'categorias':             categorias,
        'anos_disponiveis':       anos_disponiveis,
        'meses':                  MESES,
        'ano_sel':                ano_sel,
        'mes_sel':                mes_sel,
        'membro_sel':             membro_sel,
        'cartao_sel':             cartao_sel,
        'busca':                  busca,
        'cat_sel':                cat_sel,
        'atrib_sel':              atrib_sel,
        'tab_sel':                tab_sel,
        'order_sel':              order_sel,
        'dir_sel':                dir_sel,
        'grafico_json':           grafico_json,
    }
    return render(request, 'cartao_credito/transacoes/lista.html', context)


def transacao_toggle_oculta(request, pk):
    if request.method != 'POST':
        return redirect('cartao_credito:transacoes_lista')
    t = get_object_or_404(TransacaoCartao, pk=pk)
    t.oculta = not t.oculta
    t.save(update_fields=['oculta'])
    voltar = request.POST.get('next', '')
    return redirect(voltar) if voltar else redirect('cartao_credito:transacoes_lista')


def transacoes_bulk_action(request):
    if request.method != 'POST':
        return redirect('cartao_credito:transacoes_lista')

    ids    = request.POST.getlist('ids')
    action = request.POST.get('action', '')
    voltar = request.POST.get('next', '')

    if ids:
        qs = TransacaoCartao.objects.filter(pk__in=ids)

        if action == 'ocultar':
            qs.update(oculta=True)
        elif action == 'mostrar':
            qs.update(oculta=False)
        elif action == 'editar_tudo':
            cat_id = request.POST.get('categoria_id', '')
            membro_ids = request.POST.getlist('membro_ids')
            anotacao = request.POST.get('anotacao_bulk', '').strip()
            if anotacao:
                anotacao = anotacao[0].upper() + anotacao[1:] if len(anotacao) > 1 else anotacao.upper()
            for t in qs:
                # Categoria
                if cat_id:
                    try:
                        cat = Categoria.objects.get(pk=cat_id)
                        t.categoria = cat
                    except Categoria.DoesNotExist:
                        t.categoria = None
                elif cat_id == '':
                    t.categoria = None
                # Membros
                if membro_ids:
                    t.membros.set(membro_ids)
                # Anotacao
                t.anotacao = anotacao
                t.save()
        elif action == 'categorizar':
            cat_id = request.POST.get('categoria_id', '')
            if cat_id:
                try:
                    cat = Categoria.objects.get(pk=cat_id)
                    qs.update(categoria=cat)
                except Categoria.DoesNotExist:
                    pass
            else:
                qs.update(categoria=None)
        elif action == 'atribuir_membros':
            membro_ids = request.POST.getlist('membro_ids')
            for t in qs:
                t.membros.set(membro_ids)
        elif action == 'anotacao_bulk':
            anotacao = request.POST.get('anotacao_bulk', '').strip()
            if anotacao:
                anotacao = anotacao[0].upper() + anotacao[1:] if len(anotacao) > 1 else anotacao.upper()
            for t in qs:
                t.anotacao = anotacao
                t.save(update_fields=['anotacao'])

    return redirect(voltar) if voltar else redirect('cartao_credito:transacoes_lista')


def parcelados(request):
    """Lista de compras parceladas agrupadas por compra e por mês.

    Filtros (GET):
      - start: YYYY-MM (primeiro dia do mês)
      - end: YYYY-MM (último dia do mês)
      - period: '12m' (padrão), '24m', 'year', 'prev_year'
    """
    # Parâmetros
    period = request.GET.get('period', '')
    start_param = request.GET.get('start', '').strip()
    end_param = request.GET.get('end', '').strip()

    hoje = date.today()

    def parse_ym(s: str):
        if not s:
            return None
        try:
            if re.match(r'^\d{4}-\d{2}$', s):
                y, m = map(int, s.split('-'))
                return date(y, m, 1)
            return date.fromisoformat(s)
        except Exception:
            return None

    def last_day_of_month(d: date) -> date:
        last = calendar.monthrange(d.year, d.month)[1]
        return date(d.year, d.month, last)

    _re_parc_token = re.compile(r'\s*[-–]?\s*PARC\s+\d{1,2}/\d{1,2}\b', re.IGNORECASE)

    def _clean_desc(texto: str) -> str:
        """Remove 'PARC XX/XX' da descrição para exibição."""
        if not texto:
            return ''
        return re.sub(r'\s+', ' ', _re_parc_token.sub('', texto)).strip()

    def _add_months(d: date, n: int) -> date:
        y = d.year + (d.month - 1 + n) // 12
        m = (d.month - 1 + n) % 12 + 1
        return date(y, m, 1)

    # Carrega todos os grupos antes de determinar o período (necessário para calcular max_proj)
    try:
        grupos = agrupar_parcelados(TransacaoCartao.objects.filter(oculta=False))
    except Exception:
        grupos = []

    all_ids = [pid for g in grupos for pid in g.lancamento_ids]

    # Calcula o último mês com parcela projetada (para período padrão)
    max_proj = date(hoje.year, hoje.month, 1)
    for g in grupos:
        if g.parcela_total:
            candidate = _add_months(g.data_compra, g.parcela_total - 1)
            if candidate > max_proj:
                max_proj = candidate
    try:
        for t in TransacaoCartao.objects.filter(
            oculta=False, parcela_total__gt=0
        ).exclude(pk__in=all_ids).select_related('fatura'):
            num = int(t.parcela_num) if (t.parcela_num or 0) > 0 else None
            total = int(t.parcela_total)
            if num and total and num < total:
                base = (t.fatura.competencia if getattr(t, 'fatura', None) and getattr(t.fatura, 'competencia', None) else date(t.data.year, t.data.month, 1))
                candidate = _add_months(base, total - num)
                if candidate > max_proj:
                    max_proj = candidate
    except Exception:
        pass

    # Determina intervalo
    if start_param and end_param:
        sd = parse_ym(start_param) or date(hoje.year, hoje.month, 1)
        ed_tmp = parse_ym(end_param) or date(hoje.year, hoje.month, 1)
        ed = last_day_of_month(ed_tmp)
    elif period == '24m':
        sd = _add_months(date(hoje.year, hoje.month, 1), -23)
        ed = last_day_of_month(hoje)
    elif period == '12m':
        sd = _add_months(date(hoje.year, hoje.month, 1), -11)
        ed = last_day_of_month(hoje)
    elif period == 'year':
        sd = date(hoje.year, 1, 1)
        ed = date(hoje.year, 12, 31)
    elif period == 'prev_year':
        sd = date(hoje.year - 1, 1, 1)
        ed = date(hoje.year - 1, 12, 31)
    else:
        # Padrão: 6 meses anteriores até o fim das parcelas futuras
        sd = _add_months(date(hoje.year, hoje.month, 1), -6)
        ed = last_day_of_month(max_proj)

    # lista de meses para exibição
    months = []
    cur = date(sd.year, sd.month, 1)
    end_month = date(ed.year, ed.month, 1)
    while cur <= end_month:
        months.append({'year': cur.year, 'month': cur.month, 'label': f"{cur.month:02d}/{cur.year}"})
        cur = _add_months(cur, 1)
    trans_qs = TransacaoCartao.objects.filter(pk__in=all_ids).select_related('fatura', 'fatura__cartao', 'categoria').prefetch_related('membros')
    trans_map = {t.pk: t for t in trans_qs}

    monthly_sums: dict = defaultdict(Decimal)
    monthly_entries: Dict[Tuple[int,int], List[Dict]] = defaultdict(list)
    # seen keys to avoid duplicate additions: (tx_id, parcela_num_or_0)
    monthly_seen: set = set()
    grupos_vis = []
    # índices para evitar duplicação entre transações diferentes com mesma assinatura
    # assinatura = (desc_base_normalizada, parcela_total)
    real_months_by_sig: Dict[Tuple[str, Optional[int]], set] = defaultdict(set)
    projected_months_by_sig: Dict[Tuple[str, Optional[int]], set] = defaultdict(set)

    for g in grupos:
        trans_list = [trans_map.get(i) for i in g.lancamento_ids if trans_map.get(i)]
        if not trans_list:
            continue
        # incluir grupo se alguma parcela estiver dentro do período filtrado
        inclui = any((sd <= (t.fatura.competencia if getattr(t, 'fatura', None) and getattr(t.fatura, 'competencia', None) else date(t.data.year, t.data.month, 1)) <= ed) or (sd <= t.data <= ed) for t in trans_list)
        if not inclui:
            continue

        # meses já presentes (evita duplicar quando existir lançamentos reais)
        existentes = set(
            (
                (t.fatura.competencia.year, t.fatura.competencia.month)
                if getattr(t, 'fatura', None) and getattr(t.fatura, 'competencia', None)
                else (t.data.year, t.data.month)
            )
            for t in trans_list
        )

        # adiciona entradas reais e acumula valores
        for t in trans_list:
            inst_date_real = (t.fatura.competencia if getattr(t, 'fatura', None) and getattr(t.fatura, 'competencia', None) else date(t.data.year, t.data.month, 1))
            if sd <= inst_date_real <= ed:
                key = (inst_date_real.year, inst_date_real.month)

                # parcela num/total (prefere campos do modelo, senão infere da descrição)
                num = int(t.parcela_num) if (t.parcela_num or 0) > 0 else None
                total = int(t.parcela_total) if (t.parcela_total or 0) > 0 else None
                if (num is None or total is None) and (t.descricao or ''):
                    try:
                        inf_n, inf_t = _extract_num_total(t.descricao or '')
                        if num is None:
                            num = inf_n
                        if total is None:
                            total = inf_t
                    except Exception:
                        num, total = num, total

                pnum = num or 0
                seen_key = (t.pk, pnum)
                if seen_key in monthly_seen:
                    continue
                monthly_seen.add(seen_key)

                monthly_sums[key] += Decimal(t.valor or 0)

                parcela_token = t.etiqueta_parcela or (f"PARC {num:02d}/{total:02d}" if (num and total) else '')
                categoria_nome = (t.categoria.nome if getattr(t, 'categoria', None) else '')
                membros_nomes = [m.nome for m in t.membros.all()]

                monthly_entries[key].append({
                    'tx_id': t.pk,
                    'orig_date': t.data,
                    'desc': _clean_desc(t.descricao),
                    'cidade': t.cidade,
                    'inst_label': f"{inst_date_real.month:02d}/{inst_date_real.year}",
                    'parcela_token': parcela_token,
                    'parcela_num': num,
                    'parcela_total': total,
                    'amount': Decimal(t.valor or 0),
                    'categoria': categoria_nome,
                    'membros': membros_nomes,
                    'is_real': True,
                    'grupo_id': g.group_id,
                })
                # marca mês real para esta assinatura (desc_base do grupo)
                try:
                    sig = (g.desc_base, g.parcela_total)
                    real_months_by_sig.setdefault(sig, set()).add(key)
                except Exception:
                    pass

        # Projeta parcelas futuras a partir da num/total (campo ou inferido pela descrição)
        for t in trans_list:
            num = int(t.parcela_num) if (t.parcela_num or 0) > 0 else None
            total = int(t.parcela_total) if (t.parcela_total or 0) > 0 else None
            if (num is None or total is None) and (t.descricao or ''):
                try:
                    inf_n, inf_t = _extract_num_total(t.descricao or '')
                    if num is None:
                        num = inf_n
                    if total is None:
                        total = inf_t
                except Exception:
                    num, total = num, total

            if not (num and total) or num >= total:
                continue

            base = (t.fatura.competencia if getattr(t, 'fatura', None) and getattr(t.fatura, 'competencia', None) else date(t.data.year, t.data.month, 1))

            for idx in range(num + 1, total + 1):
                offset = idx - num
                inst_date = _add_months(base, offset)
                # considera apenas dentro do intervalo filtrado
                if not (date(sd.year, sd.month, 1) <= date(inst_date.year, inst_date.month, 1) <= date(ed.year, ed.month, 1)):
                    continue
                key = (inst_date.year, inst_date.month)
                # evita somar se já houver lançamento real nesse mês (no próprio grupo)
                if key in existentes:
                    continue
                # evita duplicação entre transações com mesma assinatura (desc_base + parcela_total)
                sig = (g.desc_base, g.parcela_total)
                if key in real_months_by_sig.get(sig, set()):
                    continue
                if key in projected_months_by_sig.get(sig, set()):
                    continue
                # avoid duplicate projected entries (same tx, same parcela index)
                seen_key = (t.pk, idx)
                if seen_key in monthly_seen:
                    continue
                monthly_seen.add(seen_key)

                monthly_sums[key] += Decimal(t.valor or 0)

                total_proj = total
                parcela_token = f"PARC {idx:02d}/{total_proj:02d}" if total_proj else ''
                categoria_nome = (t.categoria.nome if getattr(t, 'categoria', None) else '')
                membros_nomes = [m.nome for m in t.membros.all()]

                monthly_entries[key].append({
                    'tx_id': t.pk,
                    'orig_date': t.data,
                    'desc': _clean_desc(t.descricao),
                    'cidade': t.cidade,
                    'inst_label': f"{inst_date.month:02d}/{inst_date.year}",
                    'parcela_token': parcela_token,
                    'parcela_num': idx,
                    'parcela_total': total_proj,
                    'amount': Decimal(t.valor or 0),
                    'categoria': categoria_nome,
                    'membros': membros_nomes,
                    'is_real': False,
                    'grupo_id': g.group_id,
                })
                # marca mês projetado para esta assinatura
                projected_months_by_sig.setdefault(sig, set()).add(key)

        grupos_vis.append({'grupo': g, 'transacoes': sorted(trans_list, key=lambda x: (x.descricao or '').lower())})

    # --- Incluir transações "single" que têm informação de parcela (etiqueta/parcela_total/descrição)
    # Estas transações não formaram cadeias (por terem apenas uma linha presente no banco),
    # mas é importante projetar as parcelas futuras a partir de num/total.
    try:
        singles_qs = TransacaoCartao.objects.filter(
            oculta=False
        ).exclude(pk__in=all_ids).select_related('fatura', 'fatura__cartao', 'categoria').prefetch_related('membros')
    except Exception:
        singles_qs = []

    # Filtra em Python mais estritamente: aceitar apenas descrições/etiquetas com PARC xx/yy
    candidates = []
    for t in list(singles_qs):
        desc = (t.descricao or '')
        etiqueta = (t.etiqueta_parcela or '')
        if _tem_padrao_parcelado(desc):
            candidates.append(t)
            continue
        if etiqueta and 'PARC' in etiqueta.upper():
            candidates.append(t)
            continue
        if (t.parcela_total or 0) > 0 and 'PARC' in desc.upper():
            candidates.append(t)

    for t in candidates:
        trans_list = [t]
        # incluir se parcela real ou projeção cair dentro do período
        inst_real = (t.fatura.competencia if getattr(t, 'fatura', None) and getattr(t.fatura, 'competencia', None) else date(t.data.year, t.data.month, 1))
        # determina se há qualquer parcela (real ou projetada) no intervalo
        num = int(t.parcela_num) if (t.parcela_num or 0) > 0 else None
        total = int(t.parcela_total) if (t.parcela_total or 0) > 0 else None
        if (num is None or total is None) and (t.descricao or ''):
            try:
                inf_n, inf_t = _extract_num_total(t.descricao or '')
                if num is None:
                    num = inf_n
                if total is None:
                    total = inf_t
            except Exception:
                num, total = num, total

        includes_period = False
        # check real date
        if sd <= inst_real <= ed:
            includes_period = True
        # check projected months
        if not includes_period and num and total and num < total:
            base = inst_real
            for idx in range(num + 1, total + 1):
                offset = idx - num
                inst_date = _add_months(base, offset)
                if date(sd.year, sd.month, 1) <= date(inst_date.year, inst_date.month, 1) <= date(ed.year, ed.month, 1):
                    includes_period = True
                    break

        if not includes_period:
            continue

        existentes = set(((inst_real.year, inst_real.month),))

        # adiciona entrada real (com deduplicação)
        if sd <= inst_real <= ed:
            key = (inst_real.year, inst_real.month)
            pnum = num or 0
            seen_key = (t.pk, pnum)
            if seen_key not in monthly_seen:
                monthly_seen.add(seen_key)
                monthly_sums[key] += Decimal(t.valor or 0)
                parcela_token = t.etiqueta_parcela or (f"PARC {num:02d}/{total:02d}" if (num and total) else '')
                categoria_nome = (t.categoria.nome if getattr(t, 'categoria', None) else '')
                membros_nomes = [m.nome for m in t.membros.all()]
                monthly_entries[key].append({
                    'tx_id': t.pk,
                    'orig_date': t.data,
                    'desc': _clean_desc(t.descricao),
                    'cidade': t.cidade,
                    'inst_label': f"{inst_real.month:02d}/{inst_real.year}",
                    'parcela_token': parcela_token,
                    'parcela_num': num,
                    'parcela_total': total,
                    'amount': Decimal(t.valor or 0),
                    'categoria': categoria_nome,
                    'membros': membros_nomes,
                    'is_real': True,
                    'grupo_id': None,
                })
                # marca mês real para esta assinatura (normaliza descrição)
                try:
                    sig = (_try_normalizar(t.descricao or ''), total)
                    real_months_by_sig.setdefault(sig, set()).add(key)
                except Exception:
                    pass

        # projeta parcelas futuras (com deduplicação)
        if num and total and num < total:
            base = inst_real
            for idx in range(num + 1, total + 1):
                offset = idx - num
                inst_date = _add_months(base, offset)
                if not (date(sd.year, sd.month, 1) <= date(inst_date.year, inst_date.month, 1) <= date(ed.year, ed.month, 1)):
                    continue
                key = (inst_date.year, inst_date.month)
                if key in existentes:
                    continue
                # evita duplicação por assinatura entre diferentes transações
                sig = (_try_normalizar(t.descricao or ''), total)
                if key in real_months_by_sig.get(sig, set()):
                    continue
                if key in projected_months_by_sig.get(sig, set()):
                    continue
                seen_key = (t.pk, idx)
                if seen_key in monthly_seen:
                    continue
                monthly_seen.add(seen_key)
                monthly_sums[key] += Decimal(t.valor or 0)
                parcela_token = f"PARC {idx:02d}/{total:02d}" if total else ''
                categoria_nome = (t.categoria.nome if getattr(t, 'categoria', None) else '')
                membros_nomes = [m.nome for m in t.membros.all()]
                monthly_entries[key].append({
                    'tx_id': t.pk,
                    'orig_date': t.data,
                    'desc': _clean_desc(t.descricao),
                    'cidade': t.cidade,
                    'inst_label': f"{inst_date.month:02d}/{inst_date.year}",
                    'parcela_token': parcela_token,
                    'parcela_num': idx,
                    'parcela_total': total,
                    'amount': Decimal(t.valor or 0),
                    'categoria': categoria_nome,
                    'membros': membros_nomes,
                    'is_real': False,
                    'grupo_id': None,
                })
                # marca mês projetado para esta assinatura
                projected_months_by_sig.setdefault(sig, set()).add(key)

        grupos_vis.append({'grupo': None, 'transacoes': sorted(trans_list, key=lambda x: (x.descricao or '').lower())})

    # Deduplica entradas por mês: para cada compra (grupo ou assinatura desc+total),
    # mantém apenas uma entrada — prefere real sobre projetada e, entre reais, a de
    # maior parcela_num (parcela mais recente da cadeia que caiu naquele mês).
    for key in list(monthly_entries.keys()):
        entries = monthly_entries[key]
        if len(entries) <= 1:
            continue
        best: dict = {}  # purchase_key -> entry
        for e in entries:
            gid = e.get('grupo_id')
            if gid is not None:
                pkey = ('g', gid)
            else:
                try:
                    nd = _try_normalizar(e.get('desc') or '')
                except Exception:
                    nd = (e.get('desc') or '').upper().strip()
                pkey = ('s', nd, e.get('parcela_total'))

            existing = best.get(pkey)
            if existing is None:
                best[pkey] = e
            else:
                e_real = e.get('is_real', False)
                ex_real = existing.get('is_real', False)
                e_num = e.get('parcela_num') or 0
                ex_num = existing.get('parcela_num') or 0
                # entrada real sempre vence projetada; entre iguais, maior parcela_num
                if (e_real and not ex_real) or (e_real == ex_real and e_num > ex_num):
                    best[pkey] = e

        monthly_entries[key] = list(best.values())
        monthly_sums[key] = sum(e['amount'] for e in monthly_entries[key])

    # anexa entradas e totais a cada mês (para uso direto no template)
    for m in months:
        key = (m['year'], m['month'])
        m_total = monthly_sums.get(key, Decimal('0.00'))
        m['total'] = m_total
        # ordena entradas alfabeticamente pela descrição
        entries = monthly_entries.get(key, [])
        entries_sorted = sorted(entries, key=lambda e: ((e.get('desc') or '').lower()))
        m['entries'] = entries_sorted

    monthly_totals = [{'label': m['label'], 'total': m['total']} for m in months]

    # Totais do período
    credits_total = sum((v for v in monthly_sums.values() if v > 0), Decimal('0.00'))
    debits_total = sum((v for v in monthly_sums.values() if v < 0), Decimal('0.00'))
    total_period = credits_total + debits_total
    # total_compras = soma absoluta de todas as parcelas do período (após dedup)
    total_compras = abs(sum(monthly_sums.values(), Decimal('0.00')))
    transactions_count = sum(len(m['entries']) for m in months)

    # Parcelas não pagas: mês atual + futuros
    mes_atual_inicio = date(hoje.year, hoje.month, 1)
    total_nao_pago = abs(sum(
        v for (yr, mn), v in monthly_sums.items()
        if date(yr, mn, 1) >= mes_atual_inicio
    ))

    return render(request, 'cartao_credito/parcelados/lista.html', {
        'grupos': grupos_vis,
        'monthly_totals': monthly_totals,
        'months': months,
        'start': sd,
        'end': ed,
        'total_compras': total_compras,
        'total_nao_pago': total_nao_pago,
        'period': period,
        'credits_total': credits_total,
        'debits_total': debits_total,
        'total_period': total_period,
        'transactions_count': transactions_count,
    })

