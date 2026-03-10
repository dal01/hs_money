# conta_corrente/parsers/caixa/extrato_pdf.py
"""
Parser para extratos de conta corrente da Caixa Econômica Federal em PDF.

Formato esperado (internet banking / app):

    Cliente: FULANO DE TAL  Conta: 00002 | 3701 | 000584985168-9
    Período: Novembro/2024  1 - 30  14/08/2025 - 21:41

    Data Mov.  Nr. Doc.  Histórico         Valor      Saldo
    01/11/2024 011037    AP LOTERIA        15,00 D    7.778,69 C
    01/11/2024 000000    SALDO DIA          0,00 C    7.763,69 C
    ...
"""
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

from hs_money.core.utils import limpar_prefixo_descricao


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _parse_br(s: str) -> Decimal:
    """'1.234,56' → Decimal('1234.56')"""
    return Decimal(s.strip().replace(".", "").replace(",", "."))


# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

# Linha de transação:  DD/MM/YYYY  NNNNNNN  DESCRIÇÃO  1.234,56 D  1.234,56 C
RE_TRANSACAO = re.compile(
    r"^(?P<data>\d{2}/\d{2}/\d{4})"
    r"\s+(?P<doc>\d+)"
    r"\s+(?P<hist>.+?)"
    r"\s+(?P<valor>[\d.]+,\d{2})"
    r"\s+(?P<sinal>[DC])"
    r"\s+(?P<saldo>[\d.]+,\d{2})"
    r"\s+(?P<saldo_sinal>[DC])"
    r"\s*$"
)

# Cabeçalho: Conta: 00002 | 3701 | 000584985168-9
RE_CONTA = re.compile(
    r"Conta:\s*(?P<op>[\d]+)\s*\|\s*(?P<agencia>[\d]+)\s*\|\s*(?P<numero>[^\s|]+)",
    re.IGNORECASE,
)

# Cliente: NOME
RE_CLIENTE = re.compile(r"Cliente:\s*(?P<nome>.+?)(?:\s{2,}|$)", re.IGNORECASE)

# Período: Mês/Ano  dia_ini - dia_fim
RE_PERIODO = re.compile(
    r"Per[ií]odo:\s*(?P<mes_nome>\w+)/(?P<ano>\d{4})",
    re.IGNORECASE,
)

# Descricoes a ignorar
DESCRICOES_IGNORAR = {"SALDO DIA", "SALDO ANTERIOR"}


# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class DadosConta:
    agencia: str
    numero: str
    cliente: str


@dataclass
class LancamentoCaixa:
    data: date
    doc: str
    descricao: str
    valor: Decimal        # positivo = crédito, negativo = débito
    saldo: Decimal
    hash_linha: str
    hash_ordem: int
    is_duplicado: bool


@dataclass
class ResultadoParsePDF:
    conta: Optional[DadosConta] = None
    lancamentos: List[LancamentoCaixa] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    erro: Optional[str] = None


# ---------------------------------------------------------------------------
# Parser principal
# ---------------------------------------------------------------------------

def parse_extrato_pdf(caminho_pdf) -> ResultadoParsePDF:
    """
    Faz o parse de um arquivo PDF de extrato da Caixa.

    Parâmetro: Path ou str com o caminho do PDF.
    Retorna ResultadoParsePDF.
    """
    try:
        import pdfplumber
    except ImportError:
        return ResultadoParsePDF(erro="pdfplumber não instalado. Execute: pip install pdfplumber")

    result = ResultadoParsePDF()

    try:
        pdf = pdfplumber.open(str(caminho_pdf))
    except Exception as exc:
        result.erro = f"Não foi possível abrir o PDF: {exc}"
        return result

    linhas_todas: list[str] = []
    with pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text(x_tolerance=3, y_tolerance=3) or ""
            linhas_todas.extend(texto.splitlines())

    if not linhas_todas:
        result.erro = "Nenhum texto extraído do PDF."
        return result

    # --- cabeçalho ---
    texto_completo = "\n".join(linhas_todas)

    m_conta = RE_CONTA.search(texto_completo)
    m_cliente = RE_CLIENTE.search(texto_completo)

    if m_conta:
        result.conta = DadosConta(
            agencia=m_conta.group("agencia").strip(),
            numero=m_conta.group("numero").strip(),
            cliente=m_cliente.group("nome").strip() if m_cliente else "",
        )
    else:
        result.avisos.append("Número de conta não encontrado no PDF.")

    # --- transações ---
    contador_hash: dict[str, int] = {}
    fitids_vistos: set[str] = set()

    for linha in linhas_todas:
        linha = linha.strip()
        m = RE_TRANSACAO.match(linha)
        if not m:
            continue

        hist = m.group("hist").strip()

        # ignora linhas de saldo
        if any(ign in hist.upper() for ign in DESCRICOES_IGNORAR):
            continue

        # data
        dia, mes, ano_str = m.group("data").split("/")
        data = date(int(ano_str), int(mes), int(dia))

        # valor com sinal
        valor_bruto = _parse_br(m.group("valor"))
        sinal = m.group("sinal")
        valor = valor_bruto if sinal == "C" else -valor_bruto

        saldo = _parse_br(m.group("saldo"))
        if m.group("saldo_sinal") == "D":
            saldo = -saldo

        doc = m.group("doc").strip()
        descricao = limpar_prefixo_descricao(hist)

        # hash de deduplicação
        chave = f"{data:%Y%m%d}|{doc}|{descricao}|{valor}"
        n = contador_hash.get(chave, 0)
        contador_hash[chave] = n + 1
        hash_linha = _sha1(chave)
        is_duplicado = hash_linha in fitids_vistos
        fitids_vistos.add(hash_linha)

        result.lancamentos.append(
            LancamentoCaixa(
                data=data,
                doc=doc,
                descricao=descricao,
                valor=valor,
                saldo=saldo,
                hash_linha=hash_linha,
                hash_ordem=n + 1,
                is_duplicado=is_duplicado,
            )
        )

    if not result.lancamentos:
        result.avisos.append("Nenhum lançamento encontrado no PDF.")

    return result
