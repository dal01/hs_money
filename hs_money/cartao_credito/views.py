from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.shortcuts import render, redirect

from hs_money.cartao_credito.models import FaturaCartao
from hs_money.cartao_credito.services.importar import importar_arquivo_pdf_bb, hash_pdf


def index(request):
    return redirect('cartao_credito:listar_faturas')


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
