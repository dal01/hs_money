from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import re
import hashlib
from collections import defaultdict

from django.db.models import QuerySet

from cartao_credito.models import Lancamento

# =======================
# Configurações ajustáveis
# =======================
TOLERANCIA_VALOR_ABS = Decimal("0.50")  # tolerância de valor por parcela (ex.: variações pequenas / IOF)
TOLERANCIA_DIAS_MES = 7                 # tolerância em dias para "próximo mês" (ex.: 20~38 dias)
MIN_DIAS_MES = 20
MAX_DIAS_MES = 38

# =======================
# Padrões de parcelado
# =======================
RE_WORD_PARC   = re.compile(r"(?:\b|-)PARC(?:\.|ELA(?:S)?|ELAD[OA]|ELAMENT[OA])?\b", re.IGNORECASE)
RE_FRAC        = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\b")                  # 12/12
RE_DE_FORM     = re.compile(r"\b(\d{1,2})\s*de\s*(\d{1,2})\b", re.IGNORECASE)  # 12 de 12
RE_X_SIMPLE    = re.compile(r"\b(\d{1,2})\s*[xX]\b")                           # 12x
RE_X_PAIR      = re.compile(r"\b(\d{1,2})\s*[xX]\s*(?:de\s*)?(\d{1,2})\b", re.IGNORECASE)  # 12x10, 12x de 10
RE_EM_X        = re.compile(r"\bem\s+(\d{1,2})[xX]\b", re.IGNORECASE)          # em 12x

# =======================
# Normalização de descrição
# =======================
def _try_normalizar(txt: str) -> str:
    try:
        from core.utils.normaliza import normalizar
        base = normalizar(txt or "")
    except Exception:
        base = (txt or "").strip().upper()

    # Remove tokens de parcela para unificar a base textual
    base = RE_FRAC.sub("", base)
    base = RE_DE_FORM.sub("", base)
    base = RE_X_PAIR.sub("", base)
    base = RE_X_SIMPLE.sub("", base)
    base = RE_EM_X.sub("", base)
    base = RE_WORD_PARC.sub("", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base

def _q2(v: Decimal) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def _make_group_id(cartao_id: int | None, data_ref: date, desc_base: str, val_bucket: str, parcela_total: int | None) -> str:
    raw = f"{cartao_id or 0}|{data_ref.isoformat()}|{desc_base}|{val_bucket}|{parcela_total or 0}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

# =======================
# Extração de parcela (num/total) da descrição
# =======================
def _extract_num_total(desc: str) -> Tuple[Optional[int], Optional[int]]:
    if not desc:
        return None, None
    m = RE_FRAC.search(desc)
    if m:
        try:
            return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    m = RE_DE_FORM.search(desc)
    if m:
        try:
            return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    # "12x" sozinho (sem total) -> só num atual não ajuda a total; deixamos None
    m = RE_X_PAIR.search(desc)
    if m:
        try:
            return int(m.group(1)), int(m.group(2))
        except Exception:
            pass
    return None, None

def _tem_padrao_parcelado(texto: str) -> bool:
    if not texto:
        return False
    return any(p.search(texto) for p in (RE_WORD_PARC, RE_FRAC, RE_DE_FORM, RE_X_PAIR, RE_X_SIMPLE, RE_EM_X))

def _eh_candidato(l: Lancamento) -> bool:
    if _tem_padrao_parcelado(l.descricao or ""):
        return True
    if l.etiqueta_parcela:
        return True
    if (l.parcela_total or 0) > 0:
        return True
    return False

# =======================
# Cadeias mensais
# =======================
def _is_next_month(prev: date, curr: date) -> bool:
    """Retorna True se curr está ~1 mês após prev (20..38 dias)."""
    delta = (curr - prev).days
    return MIN_DIAS_MES <= delta <= MAX_DIAS_MES

def _chain_by_month_and_value(items: List[Lancamento]) -> List[List[Lancamento]]:
    """
    Recebe itens já com valores *próximos* (mesmo sub-bucket de valor).
    Cria cadeias ordenadas por data, onde cada item está ~1 mês do anterior.
    """
    if not items:
        return []
    items_sorted = sorted(items, key=lambda x: (x.data, x.id))
    chains: List[List[Lancamento]] = []
    chain: List[Lancamento] = [items_sorted[0]]
    for it in items_sorted[1:]:
        if _is_next_month(chain[-1].data, it.data):
            chain.append(it)
        else:
            if len(chain) >= 2:
                chains.append(chain)
            chain = [it]
    if len(chain) >= 2:
        chains.append(chain)
    return chains

# =======================
# Estrutura final
# =======================
@dataclass
class GrupoParcelado:
    group_id: str
    data_compra: date            # usamos a menor data da cadeia
    desc_base: str
    parcela_total: Optional[int]
    valor_parcela_medio: Decimal
    valor_total_compra: Decimal
    qtd_parcelas: int
    lancamento_ids: List[int] = field(default_factory=list)

# =======================
# API principal
# =======================
def agrupar_parcelados(
    qs: QuerySet[Lancamento],
    *,
    return_debug: bool = False,
) -> List[GrupoParcelado] | Tuple[List[GrupoParcelado], Dict]:
    """
    Pipeline:
      0) Candidatos.
      1) Buckets por (cartao_id, desc_base, parcela_total_inferido).
      2) Dentro de cada bucket: sub-buckets por valor (~=, com tolerância).
      3) Em cada sub-bucket: formar cadeias mensais (20..38 dias entre datas).
      4) Produzir grupos (len(cadeia) >= 2).
    """
    itens = list(
        qs.select_related("fatura", "fatura__cartao", "categoria").prefetch_related("membros")
    )

    # 0) candidatos
    candidatos: List[Lancamento] = [l for l in itens if _eh_candidato(l)]
    if not candidatos:
        return ([], _build_debug(itens, [], {}, [], 0, 0, 0, 0)) if return_debug else []

    # 1) buckets
    bucket_key: Dict[Tuple[Optional[int], str, Optional[int]], List[Lancamento]] = defaultdict(list)
    inferidos: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    for l in candidatos:
        cartao_id = l.fatura.cartao_id if (l.fatura_id and l.fatura.cartao_id) else None
        desc_base = _try_normalizar(l.descricao)
        # preferir total “de verdade”; se não houver, inferir da descrição
        n, t = _extract_num_total(l.descricao or "")
        inferidos[l.id] = (n, t)
        total = l.parcela_total if (l.parcela_total or 0) > 0 else (t if (t or 0) > 0 else None)
        bucket_key[(cartao_id, desc_base, total)].append(l)

    grupos: List[GrupoParcelado] = []
    total_subbuckets = 0
    total_chains = 0

    # 2) sub-buckets por valor (com tolerância)
    for (cartao_id, desc_base, ptotal), items_bucket in bucket_key.items():
        items_sorted = sorted(items_bucket, key=lambda x: _q2(x.valor))
        sub: List[Lancamento] = []
        ref: Optional[Decimal] = None

        def flush_sub():
            nonlocal total_subbuckets, total_chains
            if not sub:
                return
            total_subbuckets += 1
            # monta cadeias mensais
            chains = _chain_by_month_and_value(sub)
            total_chains += len(chains)
            for ch in chains:
                if len(ch) < 2:
                    continue
                valores = [_q2(x.valor) for x in ch]
                qtd = len(ch)
                media = _q2(sum(valores) / qtd)
                total_val = _q2(sum(valores))
                val_bucket = f"{media:.2f}"
                data_ref = min(x.data for x in ch)
                gid = _make_group_id(cartao_id, data_ref, desc_base, val_bucket, ptotal)
                grupos.append(
                    GrupoParcelado(
                        group_id=gid,
                        data_compra=data_ref,
                        desc_base=desc_base,
                        parcela_total=ptotal,
                        valor_parcela_medio=media,
                        valor_total_compra=total_val,
                        qtd_parcelas=qtd,
                        lancamento_ids=[x.id for x in ch],
                    )
                )

        for it in items_sorted:
            v = _q2(it.valor)
            if ref is None:
                ref = v
                sub = [it]
                continue
            if abs(v - ref) <= TOLERANCIA_VALOR_ABS:
                sub.append(it)
            else:
                flush_sub()
                ref = v
                sub = [it]
        flush_sub()

    grupos.sort(key=lambda g: (g.data_compra, g.desc_base), reverse=True)

    if not return_debug:
        return grupos

    debug = _build_debug(
        itens=itens,
        candidatos=candidatos,
        buckets=bucket_key,
        grupos=grupos,
        total_subbuckets=total_subbuckets,
        total_chains=total_chains,
        tol_val=TOLERANCIA_VALOR_ABS,
        tol_dias=TOLERANCIA_DIAS_MES,
    )
    return grupos, debug

# =======================
# Debug builder
# =======================
def _safe_cartao(l: Lancamento) -> str:
    try:
        c = l.fatura.cartao
        inst = getattr(c.instituicao, "nome", "—") if c and c.instituicao_id else "—"
        bd = c.bandeira or "—" if c else "—"
        fim = c.cartao_final if c else "—"
        return f"{inst} • {bd} • ****{fim}"
    except Exception:
        return "—"

def _build_debug(
    itens: List[Lancamento],
    candidatos: List[Lancamento],
    buckets: Dict,
    grupos: List[GrupoParcelado],
    total_subbuckets: int,
    total_chains: int,
    tol_val: Decimal,
    tol_dias: int,
) -> Dict:
    amostras_cand = [{
        "id": l.id, "data": l.data.isoformat(), "valor": str(_q2(l.valor)),
        "desc": (l.descricao or "")[:120], "cartao": _safe_cartao(l),
        "parcela_num": l.parcela_num, "parcela_total": l.parcela_total,
    } for l in candidatos[:50]]

    buckets_summary = []
    for (cartao_id, desc_base, ptotal), items in buckets.items():
        buckets_summary.append({
            "cartao_id": cartao_id,
            "parcela_total": ptotal,
            "desc_base": desc_base[:100],
            "qtd_itens": len(items),
            "datas": sorted({x.data.isoformat() for x in items})[:6],
            "ids": [x.id for x in items[:10]],
        })
    buckets_summary.sort(key=lambda x: x["qtd_itens"], reverse=True)
    buckets_summary = buckets_summary[:20]

    return {
        "total_qs": len(itens),
        "total_candidatos": len(candidatos),
        "total_buckets": len(buckets),
        "total_grupos": len(grupos),
        "total_subbuckets": total_subbuckets,
        "total_chains": total_chains,
        "tolerancia_valor": str(tol_val),
        "tolerancia_dias": tol_dias,
        "amostras_candidatos": amostras_cand,
        "buckets_top": buckets_summary,
    }
