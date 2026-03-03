# cartao_credito/parsers/bb/dados_fatura.py
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

__all__ = [
    "DadosFatura",
    "parse_dados_fatura",
    "sha1",
    "parse_decimal_br",
    "competencia_from_fechamento",
]

# ------------------ helpers ------------------
def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def parse_decimal_br(s: str) -> Decimal:
    """Converte string no formato brasileiro para Decimal.
    Ex.: "1.234,56" → Decimal('1234.56')
    """
    s = (s or "").strip().replace(".", "").replace(",", ".")
    return Decimal(s)

def competencia_from_fechamento(dt: date) -> date:
    return dt.replace(day=1)

# ------------------ dataclass ------------------
@dataclass(frozen=True)
class DadosFatura:
    emissor: str
    cartao_final: str
    bandeira: Optional[str]          # <--- novo campo
    fechado_em: date
    vencimento_em: date
    competencia: date
    total: Optional[Decimal]
    arquivo_hash: str
    observacoes: list[str]

# ------------------ padrões ------------------
RE_DATA = r"(\d{2}/\d{2}/\d{4})"

# âncora da seção de lançamentos
PAT_ANCHOR_LANCAMENTOS = re.compile(r"(?i)LAN[ÇC]AMENTOS\s+NESTA\s+FATURA")

# datas típicas
PAT_FECHAMENTO = re.compile(r"(?is)\b(fatura\s+fechada\s+em|fechada\s+em)\s+" + RE_DATA)
PAT_VENCIMENTO = re.compile(r"(?is)\bvencimento\b.{0,80}?" + RE_DATA)

# final do cartão (duas alternativas)
PAT_FINAL_CARTAO = re.compile(r"(?is)\bfinal\s*(\d{4})\b|cart[ãa]o.*?\bfinal\s*(\d{4})\b")

# total da fatura (apenas a linha TOTAL DA FATURA; evitamos confundir com SUBTOTAL etc.)
PAT_TOTAL_DA_FATURA = re.compile(
    r"(?is)\bTOTAL\s+DA\s+FATURA\b.*?R\$\s*([+\-]?\s*[\d\.,]+)"
)

# bandeira do cartão — prioriza o cabeçalho "OUROCARD <BANDEIRA> ..."
PAT_BANDEIRA_OUROCARD = re.compile(
    r"(?is)\bOUROCARD\b[^A-Za-z0-9]+(?P<band>VISA|MASTERCARD|ELO|AMEX|AMERICAN\s+EXPRESS|PLATINUM)\b"
)
# fallback: qualquer ocorrência das bandeiras
PAT_BANDEIRA_GENERIC = re.compile(
    r"(?is)\b(VISA|MASTERCARD|ELO|AMEX|AMERICAN\s+EXPRESS|HIPERCARD)\b"
)

def _texto_apos_ancora(texto: str) -> str:
    """Retorna o texto a partir da âncora 'Lançamentos nesta fatura' (excluindo a linha da âncora)."""
    if not texto:
        return ""
    linhas = texto.splitlines()
    for i, raw in enumerate(linhas):
        if PAT_ANCHOR_LANCAMENTOS.search(raw or ""):
            return "\n".join(linhas[i+1:])
    return texto  # fallback: se não achou âncora, devolve inteiro (vamos registrar observação)

def _extrair_bandeira(texto: str) -> tuple[Optional[str], list[str]]:
    """Tenta extrair a bandeira do cartão a partir do texto completo do PDF."""
    obs: list[str] = []

    # 1) Prioriza padrão no cabeçalho: "OUROCARD VISA INFINITE" etc.
    m = PAT_BANDEIRA_OUROCARD.search(texto or "")
    if m:
        band = m.group("band").upper()
        if band == "AMERICAN EXPRESS":
            band = "AMEX"
        return band, obs

    # 2) Fallback: qualquer ocorrência
    m2 = PAT_BANDEIRA_GENERIC.search(texto or "")
    if m2:
        band = m2.group(1).upper()
        if band == "AMERICAN EXPRESS":
            band = "AMEX"
        # Observação leve: detectado fora do cabeçalho
        obs.append("Bandeira detectada fora do cabeçalho OUROCARD; verifique se está correta.")
        return band, obs

    obs.append("Bandeira do cartão não detectada no PDF.")
    return None, obs

def parse_dados_fatura(
    texto: str,
    pdf_path: str | None = None,
    emissor: str = "Banco do Brasil",
) -> DadosFatura:
    """Extrai dados gerais da fatura BB (cabeçalho) a partir do texto do PDF.

    Regras:
    - Se não encontrar dados críticos (fechamento, vencimento, final do cartão), levanta ValueError com dicas.
    - O total é buscado APENAS após a âncora 'Lançamentos nesta fatura'.
    - `arquivo_hash` é sha1 do texto completo para idempotência.
    - Detecta a bandeira (ex.: 'OUROCARD VISA INFINITE' → bandeira='VISA').
    """
    if not texto or len(texto.strip()) < 30:
        raise ValueError("Pouco texto extraído; o PDF pode ser escaneado sem OCR.")

    arquivo_hash = sha1(texto)
    obs: list[str] = []

    # Fechamento / Vencimento / Final do cartão
    m_fech = PAT_FECHAMENTO.search(texto)
    m_venc = PAT_VENCIMENTO.search(texto)
    m_final = PAT_FINAL_CARTAO.search(texto)

    faltando: list[str] = []
    if not m_fech:
        faltando.append('fechamento ("Fatura fechada em")')
    if not m_venc:
        faltando.append('vencimento ("Vencimento")')
    if not m_final:
        faltando.append('final do cartão ("Final 1234")')

    if faltando:
        chaves = ["Fatura fechada", "fechada em", "Vencimento", "Final", "Cartão", "Total", "OUROCARD", "VISA", "MASTERCARD", "ELO", "AMEX"]
        linhas = texto.splitlines()
        hits = [ln for ln in linhas if any(ch.lower() in ln.lower() for ch in chaves)]
        preview = "\n".join(hits[:12] if hits else linhas[:18])
        raise ValueError(
            "Dados da fatura não encontrados: "
            + ", ".join(faltando)
            + "\nPrévia de linhas relevantes:\n"
            + preview
        )

    fechado_str = m_fech.group(m_fech.lastindex)  # aponta para a data
    fechado_em = datetime.strptime(fechado_str, "%d/%m/%Y").date()

    vencimento_em = datetime.strptime(m_venc.group(1), "%d/%m/%Y").date()

    if vencimento_em < fechado_em:
        obs.append(
            f"Vencimento ({vencimento_em:%d/%m/%Y}) anterior ao fechamento ({fechado_em:%d/%m/%Y}). Verificar PDF."
        )

    # Final do cartão: primeiro grupo não-nulo
    cartao_final = next(g for g in m_final.groups() if g)

    # Bandeira (prioriza cabeçalho 'OUROCARD <BANDEIRA> ...')
    bandeira, obs_band = _extrair_bandeira(texto)
    obs.extend(obs_band)

    # Total da fatura — APÓS a âncora
    texto_pos_anchor = _texto_apos_ancora(texto)
    if texto_pos_anchor is texto:
        obs.append("Âncora 'Lançamentos nesta fatura' não encontrada; total buscado no texto inteiro.")

    m_total = PAT_TOTAL_DA_FATURA.search(texto_pos_anchor)
    if m_total:
        total = parse_decimal_br(m_total.group(1))
    else:
        total = None
        obs.append("Total da Fatura (após a âncora) não encontrado no PDF.")

    comp = competencia_from_fechamento(fechado_em)

    return DadosFatura(
        emissor=emissor,
        cartao_final=cartao_final,
        bandeira=bandeira,
        fechado_em=fechado_em,
        vencimento_em=vencimento_em,
        competencia=comp,
        total=total,
        arquivo_hash=arquivo_hash,
        observacoes=obs,
    )
