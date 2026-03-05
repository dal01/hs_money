"""
conta_corrente/services/importar.py

Lógica de importação OFX reutilizável por views e management commands.
"""
from __future__ import annotations

import re
import hashlib
from io import BytesIO
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from django.db import transaction as db_transaction
from django.conf import settings

from ofxparse import OfxParser
from unidecode import unidecode

from hs_money.core.models import InstituicaoFinanceira, Membro
from hs_money.conta_corrente.models import ContaCorrente, Extrato, Transacao


# ---------------------------------------------------------------------------
# Pré-processamento OFX: injeta FITID quando ausente
# ---------------------------------------------------------------------------
STMTTRN_RE = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE)


def _tag_re(tag: str) -> re.Pattern:
    return re.compile(rf"<{tag}>\s*([^<\r\n]+)", re.IGNORECASE)


def _tag_value(block: str, tag: str) -> Optional[str]:
    m = _tag_re(tag).search(block)
    return m.group(1).strip() if m else None


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def hash_arquivo_ofx(raw: bytes) -> str:
    """Hash canônico de um arquivo OFX — mesmo algoritmo usado ao gravar no banco."""
    return _sha1(raw.decode("latin-1", errors="replace"))


def _inject_fitid_if_missing(block: str, idx: int) -> str:
    if _tag_re("FITID").search(block):
        return block
    dt       = _tag_value(block, "DTPOSTED") or ""
    amt      = _tag_value(block, "TRNAMT")   or ""
    name     = _tag_value(block, "NAME")     or ""
    memo     = _tag_value(block, "MEMO")     or ""
    checknum = _tag_value(block, "CHECKNUM") or ""
    fitid    = _sha1(f"{dt}|{amt}|{name}|{memo}|{checknum}|#{idx}")[:28]
    return re.sub(r"(?i)<STMTTRN>", f"<STMTTRN>\n<FITID>{fitid}\n", block, count=1)


def preprocess_ofx(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    parts: list[str] = []
    last = 0
    for i, m in enumerate(STMTTRN_RE.finditer(text)):
        parts.append(text[last:m.start()])
        parts.append(_inject_fitid_if_missing(m.group(0), i))
        last = m.end()
    parts.append(text[last:])
    return "".join(parts).encode("utf-8")


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------
def _slug(s: str) -> str:
    s = unidecode((s or "").strip().lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _normalizar(s: str) -> str:
    return unidecode(" ".join(s.split()).strip().lower())


def _extract_tipo_descricao(tx) -> tuple[str, str]:
    """Retorna (tipo, descricao) a partir dos campos NAME e MEMO do OFX.

    No ofxparse, <NAME> do OFX é exposto como tx.payee e <MEMO> como tx.memo.
    """
    tipo = (getattr(tx, "payee", None) or "").strip()   # <NAME> → tx.payee
    memo = (getattr(tx, "memo",  None) or "").strip()   # <MEMO> → tx.memo
    descricao = memo or tipo
    return tipo, descricao


def _compose_descricao(tx) -> str:
    """Mantido para compatibilidade. Usa a nova lógica."""
    _, descricao = _extract_tipo_descricao(tx)
    return descricao


def _fitid_with_suffix(fitid_original: str, data: date, valor: Decimal) -> str:
    cents = int(valor.copy_abs().quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    base  = fitid_original or "NOFITID"
    return f"{base}__{data:%Y%m%d}_{cents}"


def _fitid_ja_existe(conta: ContaCorrente, fitid: str) -> bool:
    return Transacao.objects.filter(extrato__conta=conta, fitid=fitid).exists()


def _inferir_membro_por_pasta(pasta: Path) -> Optional[Membro]:
    membros = list(Membro.objects.only("id", "nome"))
    mapa    = {_slug(m.nome): m for m in membros}
    ignorar = {"conta-corrente", "conta_corrente", "ofx", "pdf", "dados", "data"}
    for seg in reversed(pasta.parts):
        tok = _slug(seg)
        if not tok or tok in ignorar or re.fullmatch(r"\d{4}", tok):
            continue
        if tok in mapa:
            return mapa[tok]
    return None


def _inferir_inst_por_pasta(pasta: Path) -> Optional[InstituicaoFinanceira]:
    for seg in reversed(pasta.parts):
        seg_clean = seg.strip().lower()
        try:
            return InstituicaoFinanceira.objects.get(codigo__iexact=seg_clean)
        except InstituicaoFinanceira.DoesNotExist:
            continue
    return None


# ---------------------------------------------------------------------------
# Resultado de uma importação
# ---------------------------------------------------------------------------
@dataclass
class ResultadoArquivo:
    arquivo:       str
    status:        str = "ok"       # ok | ignorado | erro
    conta_str:     str = ""
    conta_criada:  bool = False
    periodo:       str = ""
    novos:         int = 0
    pulados:       int = 0
    sem_data:      int = 0
    saldo_ant:     int = 0
    erro:          str = ""
    avisos:        list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Função pública principal
# ---------------------------------------------------------------------------
def importar_arquivo_ofx(
    caminho_ofx: Path,
    inst:    Optional[InstituicaoFinanceira] = None,
    membro:  Optional[Membro]               = None,
    dry_run: bool = False,
    reset:   bool = False,
) -> ResultadoArquivo:
    """
    Importa um único arquivo OFX para o banco.

    Se `inst` / `membro` forem None, tenta inferir pelo caminho de pastas.
    Retorna :class:`ResultadoArquivo` com os detalhes do processamento.
    """
    result = ResultadoArquivo(arquivo=caminho_ofx.name)

    try:
        raw   = caminho_ofx.read_bytes()
        fixed = preprocess_ofx(raw)
        ofx   = OfxParser.parse(BytesIO(fixed))
    except Exception as exc:
        result.status = "erro"
        result.erro   = f"Falha ao ler/parsear OFX: {exc}"
        return result

    pasta = caminho_ofx.parent

    # --- resolve instituição ---
    inst_resolvida = inst or _inferir_inst_por_pasta(pasta)
    if not inst_resolvida:
        result.status = "erro"
        result.erro   = (
            "Instituição não detectada pelo caminho. "
            "Cadastre um código para a instituição que bata com o nome da pasta."
        )
        return result

    # --- resolve membro ---
    membro_resolvido = membro or _inferir_membro_por_pasta(pasta)
    if not membro_resolvido:
        result.avisos.append("Membro não detectado — conta ficará sem titular.")

    contas_ofx = getattr(ofx, "accounts", None) or [getattr(ofx, "account", None)]
    contas_ofx = [c for c in contas_ofx if c is not None]

    for conta_ofx in contas_ofx:
        numero = str(
            getattr(conta_ofx, "number",     None) or
            getattr(conta_ofx, "account_id", "desconhecido")
        ).strip()

        conta, criada = ContaCorrente.objects.get_or_create(
            instituicao=inst_resolvida,
            numero=numero,
            defaults={"agencia": None, "membro": membro_resolvido, "ativa": True},
        )
        if criada:
            result.conta_criada = True
        if not conta.membro and membro_resolvido:
            conta.membro = membro_resolvido
            conta.save(update_fields=["membro"])

        result.conta_str = f"{inst_resolvida.nome} — cc {numero}"

        statement = getattr(conta_ofx, "statement", None)
        txs = statement.transactions if statement else []
        if not txs:
            result.avisos.append("Nenhuma transação no arquivo.")
            continue

        # período
        datas_validas = []
        for tx in txs:
            d = tx.date
            if isinstance(d, datetime):
                d = d.date()
            if d and d.year >= 2000:
                datas_validas.append(d)

        dt_inicio = getattr(statement, "start_date", None)
        dt_fim    = getattr(statement, "end_date",   None)
        if isinstance(dt_inicio, datetime): dt_inicio = dt_inicio.date()
        if isinstance(dt_fim,    datetime): dt_fim    = dt_fim.date()
        if not dt_inicio and datas_validas: dt_inicio = min(datas_validas)
        if not dt_fim    and datas_validas: dt_fim    = max(datas_validas)

        if not dt_inicio or not dt_fim:
            result.status = "erro"
            result.erro   = "Não foi possível determinar o período do extrato."
            return result

        result.periodo = f"{dt_inicio} → {dt_fim}"

        arquivo_hash = _sha1(raw.decode("latin-1", errors="replace"))

        if reset and not dry_run:
            Extrato.objects.filter(conta=conta, data_inicio=dt_inicio, data_fim=dt_fim).delete()

        # extrato
        if dry_run:
            extrato = None
        else:
            # Se houver duplicatas para o mesmo período (eg. dois arquivos importados
            # antes), remove as extras mantendo apenas o mais recente.
            duplicatas = list(
                Extrato.objects.filter(conta=conta, data_inicio=dt_inicio, data_fim=dt_fim)
                .order_by('pk')
            )
            if len(duplicatas) > 1:
                ids_excluir = [e.pk for e in duplicatas[:-1]]
                Extrato.objects.filter(pk__in=ids_excluir).delete()
                result.avisos.append(
                    f"Removidos {len(ids_excluir)} registro(s) duplicado(s) de Extrato para o período {result.periodo}."
                )

            extrato, extrato_criado = Extrato.objects.get_or_create(
                conta=conta,
                data_inicio=dt_inicio,
                data_fim=dt_fim,
                defaults={"arquivo_hash": arquivo_hash, "fonte_arquivo": str(caminho_ofx)},
            )
            if not extrato_criado:
                if extrato.arquivo_hash == arquivo_hash:
                    result.status = "ignorado"
                    result.avisos.append(
                        f"Extrato {result.periodo} já importado com hash igual — pulado."
                    )
                    continue
                # Arquivo diferente para o mesmo período: atualiza o hash para que
                # listar_extratos_disco marque o arquivo como "importado".
                extrato.arquivo_hash  = arquivo_hash
                extrato.fonte_arquivo = str(caminho_ofx)
                extrato.save(update_fields=["arquivo_hash", "fonte_arquivo"])
                result.avisos.append(
                    f"Extrato {result.periodo} já existe mas hash diferente — reimportando transações novas."
                )

        # transações
        for tx in txs:
            data = tx.date
            if isinstance(data, datetime): data = data.date()
            if data is None:
                result.sem_data += 1
                continue
            if data.year < 2000:
                continue

            desc_base = (
                getattr(tx, "memo",  "") or
                getattr(tx, "payee", "") or
                getattr(tx, "name",  "") or ""
            ).strip().lower()
            if "saldo anterior" in desc_base:
                result.saldo_ant += 1
                continue

            tipo_raw, descricao_raw = _extract_tipo_descricao(tx)
            tipo      = _normalizar(tipo_raw)
            descricao = _normalizar(descricao_raw)
            valor     = Decimal(str(tx.amount))

            fitid_original = (
                getattr(tx, "id",    None) or
                getattr(tx, "fitid", None) or ""
            )
            fitid = fitid_original
            if fitid_original:
                existing = (
                    Transacao.objects
                    .filter(extrato__conta=conta, fitid=fitid_original)
                    .only("id", "data", "valor")
                    .first()
                )
                if existing and (existing.data != data or existing.valor != valor):
                    fitid = _fitid_with_suffix(fitid_original, data, valor)
            else:
                fitid = _fitid_with_suffix("NOFITID", data, valor)

            if dry_run:
                result.novos += 1
                continue

            if _fitid_ja_existe(conta, fitid):
                result.pulados += 1
                continue

            with db_transaction.atomic():
                Transacao.objects.create(
                    extrato      = extrato,
                    data         = data,
                    tipo         = tipo,
                    descricao    = descricao,
                    valor        = valor,
                    fitid        = fitid,
                    hash_linha   = _sha1(fitid),
                    hash_ordem   = 1,
                    is_duplicado = False,
                )
            result.novos += 1

    return result


def importar_lista_ofx(
    caminhos: List[Path],
    inst:    Optional[InstituicaoFinanceira] = None,
    membro:  Optional[Membro]               = None,
    dry_run: bool = False,
    reset:   bool = False,
) -> List[ResultadoArquivo]:
    """Importa uma lista de arquivos OFX, retornando um resultado por arquivo."""
    return [
        importar_arquivo_ofx(p, inst=inst, membro=membro, dry_run=dry_run, reset=reset)
        for p in caminhos
    ]
