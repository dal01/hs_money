from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

import pdfplumber

from django import forms
from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from hs_money.cartao_credito.models import Cartao, FaturaCartao
from hs_money.cartao_credito.parsers.bb.dados_fatura import parse_dados_fatura
from hs_money.cartao_credito.services.importar import importar_arquivo_pdf_bb, hash_pdf
from hs_money.core.models import Membro, InstituicaoFinanceira


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
    dados_dir = getattr(settings, 'DADOS_DIR', Path(settings.BASE_DIR) / 'data')
    raiz_cc   = dados_dir / 'cartao_credito'

    hashes_importados = set(FaturaCartao.objects.values_list('arquivo_hash', flat=True))

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

        itens.append({
            'caminho':    caminho_rel,
            'nome':       arq.name,
            'membro':     membro_slug.replace('-', ' ').replace('_', ' ').title(),
            'ano':        ano,
            'importado':  sha in hashes_importados,
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

