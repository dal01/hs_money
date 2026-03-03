# cartao_credito/parsers/bb/lancamentos.py
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from collections import defaultdict
from typing import List, Tuple, Optional

# ------------------ helpers ------------------
def sha1(s: str) -> str:
    import hashlib as _h
    return _h.sha1(s.encode("utf-8")).hexdigest()

def parse_decimal_br(s: str) -> Decimal:
    s = (s or "").strip().replace(".", "").replace(",", ".")
    return Decimal(s)

def norm(s: str) -> str:
    try:
        from unidecode import unidecode
        base = unidecode((s or "").strip())
    except Exception:
        base = (s or "").strip()
    base = re.sub(r"\s+", " ", base)
    return base.upper()

# ------------------ modelo ------------------
@dataclass(frozen=True)
class LancamentoBruto:
    data: date
    descricao: str
    cidade: Optional[str]
    pais: Optional[str]
    secao: Optional[str]
    valor: Decimal
    parcela_num: Optional[int]
    parcela_total: Optional[int]
    etiqueta_parcela: str
    hash_linha: str
    hash_ordem: int
    is_duplicado: bool

# ------------------ padrões ------------------
RE_DATA_CURTA  = re.compile(r"^(?P<data>\d{2}/\d{2})\b")
RE_VALOR_FINAL = re.compile(r"R\$\s*(?P<valor>[+\-]?\s*[\d\.,]+)\s*$")

# âncora para começar a ler os lançamentos (começamos DEPOIS dela)
RE_ANCHOR_LANCAMENTOS = re.compile(r"(?i)LAN[ÇC]AMENTOS\s+NESTA\s+FATURA")

# ignorar apenas linhas conhecidas (PGTO DEBITO + SUBTOTAL + TOTAL DA FATURA)
RE_SKIP_VALUE_LINE = re.compile(r"(?i)(PGTO\s+DEBITO|SUBTOTAL|TOTAL\s+DA\s+FATURA)")

# descarte do lançamento: descrição tem "PGTO ... DEBITO" e valor NEGATIVO
RE_PGTO_DEBITO = re.compile(r"(?i)\bPGTO\b.*\bDEBITO\b")

# moeda/valor no fim da linha (para limpar da descrição)
RE_MOEDA_FIM = re.compile(
    r"\s*(?:R\$|US\$|USD|\$)\s*[+\-]?\s*\d{1,3}(?:\.\d{3})*(?:[.,]\d{2})\s*$"
)

# país imediatamente antes do valor OU no fim da linha
# exemplos válidos: "... SAO FRANCISCO CA R$ 113,93" | "... OPENAI CA"
RE_PAIS_PRE_VALOR = re.compile(r"\s+(?P<pais>[A-Z]{2,3})\s+(?:R\$|US\$|USD|\$)\s*[+\-]?\s*\d")
RE_PAIS_FIM = re.compile(r"\s+(?P<pais>[A-Z]{2,3})\s*$")

# possíveis seções comuns (ajuste/expanda conforme necessário)
RE_SECAO = re.compile(
    r"(?i)^("
    r"COMPRAS\s+NAC(?:IONAIS)?|"
    r"COMPRAS\s+INT(?:ERNACIONAIS)?|"
    r"LAN[ÇC]AMENTOS\s+DIVERSOS|"
    r"ASSINATURAS(?:\s+E\s+SERVI[ÇC]OS)?|"
    r"PARCELADOS?|"
    r"TARIFAS?|"
    r"SEGUROS?|"
    r"ESTORNOS?|"
    r"OUTROS\s+LAN[ÇC]AMENTOS?|"
    r"SERVI[ÇC]OS"
    r")\b"
)

def _limpar_primeira_linha_sem_data(s: str) -> tuple[str, Optional[str]]:
    """
    Remove valor no fim (R$ 123,45 / $ 12.34 / USD 12.34) e captura país
    apenas se ele estiver imediatamente antes do valor ou no final da linha.
    NÃO remove 'cidade' nem come palavras finais de marca/loja.
    Retorna: (descricao_limpa, pais_detectado)
    """
    if not s:
        return "", None

    txt = s.strip()
    pais = None

    # país antes do valor?
    m_pre = RE_PAIS_PRE_VALOR.search(txt)
    if m_pre:
        pais = m_pre.group("pais")
        # remove apenas o país que está imediatamente antes do valor
        start, end = m_pre.span("pais")
        txt = (txt[:start] + txt[end:]).strip()

    # remove valor no fim (se houver)
    txt = RE_MOEDA_FIM.sub("", txt).strip()

    # país no fim?
    if pais is None:
        m_fim = RE_PAIS_FIM.search(txt)
        if m_fim:
            pais = m_fim.group("pais")
            txt = RE_PAIS_FIM.sub("", txt).strip()

    # normaliza múltiplos espaços
    txt = re.sub(r"\s{2,}", " ", txt).strip()

    return txt, pais

# ------------------ núcleo ------------------
def _hash_linha(d: str, v_cent: int, desc: str, cid: str | None, pais: str | None, etiqueta: str) -> str:
    base = f"{d}|{v_cent}|{norm(desc)}|{norm(cid or '')}|{norm(pais or '')}|{norm(etiqueta)}"
    return sha1(base)

def _rollover_ano(dia: int, mes: int, fechado_em: date) -> date:
    ano = fechado_em.year
    dt = date(ano, mes, dia)
    if dt > fechado_em:
        dt = date(ano - 1, mes, dia)
    return dt

def _linhas_apos_ancora(texto: str) -> List[str]:
    linhas = (texto or "").splitlines()
    for i, raw in enumerate(linhas):
        if RE_ANCHOR_LANCAMENTOS.search(raw or ""):
            return linhas[i+1:]  # começa DEPOIS da âncora
    return linhas

def _normalizar_secao(s: str) -> str:
    base = norm(s)
    MAP = [
        (re.compile(r"COMPRAS\s+INT"), "Compras Internacionais"),
        (re.compile(r"COMPRAS\s+NAC"), "Compras Nacionais"),
        (re.compile(r"ASSINATURAS"), "Assinaturas/Serviços"),
        (re.compile(r"PARCELAD"), "Parcelados"),
        (re.compile(r"TARIF"), "Tarifas"),
        (re.compile(r"SEGURO"), "Seguros"),
        (re.compile(r"ESTORNO"), "Estornos"),
        (re.compile(r"LAN[ÇC]AMENTOS\s+DIVERSOS"), "Lançamentos Diversos"),
        (re.compile(r"SERVI[ÇC]OS"), "Serviços"),
        (re.compile(r"OUTROS"), "Outros"),
    ]
    for rx, label in MAP:
        if rx.search(base):
            return label
    return " ".join(w.capitalize() for w in base.split())

def parse_lancamentos(
    texto: str,
    dados_fatura,
    *,
    debug_unmatched: bool = False,
    debug_max: int = 40,
) -> List[LancamentoBruto]:
    if not texto or len(texto.strip()) < 30:
        return []

    fechado_em: date = dados_fatura.fechado_em

    linhas: List[LancamentoBruto] = []
    contagem = defaultdict(int)
    all_lines = _linhas_apos_ancora(texto)
    current_block: List[Tuple[int, str]] = []
    current_secao: Optional[str] = None

    def flush_block():
        nonlocal current_block
        if not current_block:
            return

        block_pairs = [(n, t) for (n, t) in current_block if (t or "").strip()]
        current_block = []
        if not block_pairs:
            return

        block_texts = [t for (_n, t) in block_pairs]
        first_line = block_texts[0].strip()

        # 1) data no início
        m_data = RE_DATA_CURTA.match(first_line)
        if not m_data:
            return
        dia, mes = map(int, m_data.group("data").split("/"))
        data_lcto = _rollover_ano(dia, mes, fechado_em)

        # 2) localizar a PRIMEIRA linha com R$ (ignorando PGTO DEBITO, SUBTOTAL, TOTAL DA FATURA)
        last_idx = -1
        m_val = None
        for j, cand in enumerate(block_texts):
            cand = cand.strip()
            if RE_SKIP_VALUE_LINE.search(cand):
                continue
            mv = RE_VALOR_FINAL.search(cand)
            if mv:
                last_idx = j
                m_val = mv
                break

        if m_val is None or last_idx == -1:
            return

        # 3) valor
        valor = parse_decimal_br(m_val.group("valor").replace(" ", ""))

        # 4) descrição (limpa) = primeira linha sem a data (limpa) + miolo até a linha do valor
        primeira_sem_data = first_line[m_data.end():].strip()
        primeira_limpa, pais_det = _limpar_primeira_linha_sem_data(primeira_sem_data)

        # junta o miolo (sem tentar tirar 'cidade' para não comer marcas)
        desc_partes: List[str] = [primeira_limpa] if primeira_limpa else []
        for part in block_texts[1:last_idx]:
            pt = (part or "").strip()
            if pt:
                desc_partes.append(pt)

        descricao = " ".join(p for p in desc_partes if p).strip()
        descricao = re.sub(r"\s{2,}", " ", descricao).strip()

        # fallback: se ficou vazio, usa 1ª linha sem data apenas removendo valor
        if not descricao:
            fallback = RE_MOEDA_FIM.sub("", primeira_sem_data).strip()
            descricao = fallback or "LANÇAMENTO"

        desc_upper = descricao.upper()

        # 5) descarte específico: "PGTO ... DEBITO" + valor NEGATIVO
        if valor < 0 and RE_PGTO_DEBITO.search(desc_upper):
            return

        # 6) parcelas (busca no bloco montado até a linha do valor)
        etiqueta, parcela_num, parcela_total = "", None, None
        bloco_ate_valor = " ".join(block_texts[: last_idx + 1])
        parc = re.search(r"\bPARC\s+(\d{2})/(\d{2})\b", bloco_ate_valor, re.IGNORECASE)
        if parc:
            etiqueta = parc.group(0)
            parcela_num, parcela_total = int(parc.group(1)), int(parc.group(2))

        # 7) cidade/pais/seção — NÃO inferimos cidade aqui (para não cortar marcas)
        cidade, pais = None, pais_det
        secao = current_secao

        # 8) hash e dedupe
        valor_cent = int((valor * 100).to_integral_value())
        h = _hash_linha(data_lcto.isoformat(), valor_cent, descricao, cidade or "", pais or "", etiqueta)
        contagem[h] += 1
        ordem = contagem[h]
        is_dup = ordem > 1

        lcto = LancamentoBruto(
            data=data_lcto,
            descricao=descricao,  # limpa (sem valor; país extraído quando presente)
            cidade=cidade,        # deixamos None para não comer marcas
            pais=pais,
            secao=secao,
            valor=valor,
            etiqueta_parcela=etiqueta,
            parcela_num=parcela_num,
            parcela_total=parcela_total,
            hash_linha=h,
            hash_ordem=ordem,
            is_duplicado=is_dup,
        )
        linhas.append(lcto)

    # --- varredura por blocos iniciados por data + captura de SEÇÃO entre blocos
    for idx, raw in enumerate(all_lines, start=1):
        t = (raw or "").strip()
        if not t:
            continue

        # detecta cabeçalhos de seção (linhas sem data)
        if not RE_DATA_CURTA.match(t) and RE_SECAO.search(t):
            current_secao = _normalizar_secao(t)
            continue

        if RE_DATA_CURTA.match(t):
            flush_block()
            current_block = [(idx, t)]
        else:
            if current_block:
                current_block.append((idx, t))

    flush_block()

    linhas.sort(key=lambda x: x.data)
    return linhas
