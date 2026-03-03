# conta_corrente/management/commands/importar_ofx.py
from __future__ import annotations

import re
import hashlib
from io import BytesIO
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
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


def _tag_value(block: str, tag: str) -> str | None:
    m = _tag_re(tag).search(block)
    return m.group(1).strip() if m else None


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _inject_fitid_if_missing(block: str, idx: int) -> str:
    if _tag_re("FITID").search(block):
        return block
    dt  = _tag_value(block, "DTPOSTED") or ""
    amt = _tag_value(block, "TRNAMT") or ""
    name = _tag_value(block, "NAME") or ""
    memo = _tag_value(block, "MEMO") or ""
    checknum = _tag_value(block, "CHECKNUM") or ""
    fitid = _sha1(f"{dt}|{amt}|{name}|{memo}|{checknum}|#{idx}")[:28]
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
# Helpers
# ---------------------------------------------------------------------------
def _slug(s: str) -> str:
    s = unidecode((s or "").strip().lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _normalizar(s: str) -> str:
    return unidecode(" ".join(s.split()).strip().lower())


def _compose_descricao(tx) -> str:
    """Monta descrição legível a partir dos campos OFX."""
    name = (getattr(tx, "name", None) or "").strip()
    memo = (getattr(tx, "memo", None) or "").strip()

    if name and memo and memo.lower() != name.lower():
        desc = f"{name} - {memo}"
    else:
        desc = name or memo

    checknum = getattr(tx, "checknum", None)
    ttype    = getattr(tx, "type", None)
    if checknum:
        desc = f"{desc} - cheque {checknum}" if desc else f"cheque {checknum}"
    if ttype and str(ttype).strip().lower() not in {"other", "debit", "credit"}:
        desc = f"{desc} - {ttype}".strip(" -")

    return desc[:255] or ""


def _fitid_with_suffix(fitid_original: str, data: date, valor: Decimal) -> str:
    """Sufixa o FITID quando há colisão de id com data/valor diferentes."""
    cents = int(valor.copy_abs().quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    base  = fitid_original or "NOFITID"
    return f"{base}__{data:%Y%m%d}_{cents}"


def _inferir_membro_por_pasta(pasta: Path) -> Membro | None:
    """Casa segmentos do caminho contra o slug do nome dos membros."""
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


# ---------------------------------------------------------------------------
# Dedupe: fitid existe em qualquer extrato desta conta?
# ---------------------------------------------------------------------------
def _fitid_ja_existe(conta: ContaCorrente, fitid: str) -> bool:
    return Transacao.objects.filter(
        extrato__conta=conta,
        fitid=fitid,
    ).exists()


# ---------------------------------------------------------------------------
# Comando
# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = (
        "Importa arquivos .ofx de conta corrente. "
        "Aceita arquivo único ou pasta (recursiva). "
        "Dedup por FITID — transações já importadas são ignoradas."
    )

    def add_arguments(self, parser):
        parser.add_argument("pasta_ou_arquivo", help="Pasta base OU arquivo OFX.")
        parser.add_argument("--dry-run",  action="store_true", help="Simula sem gravar.")
        parser.add_argument("--reset",    action="store_true", help="Apaga o extrato do período antes de reimportar.")
        parser.add_argument("--titular",  type=str, default="", help="Força o membro titular da conta.")
        parser.add_argument("--instituicao", type=str, default="", help="Força o nome da instituição (caso não seja inferível pelo caminho).")

    def handle(self, *args, **opts):
        caminho = Path(opts["pasta_ou_arquivo"])
        if not caminho.is_absolute():
            # tenta relativo ao BASE_DIR primeiro, depois ao DADOS_DIR
            alt = Path(settings.BASE_DIR) / caminho
            if alt.exists():
                caminho = alt
            else:
                dados_dir = getattr(settings, "DADOS_DIR", settings.BASE_DIR / "data")
                caminho = dados_dir / caminho
        caminho = caminho.resolve()

        dry_run      = opts["dry_run"]
        do_reset     = opts["reset"]
        titular_nome = opts["titular"].strip()
        inst_force   = opts["instituicao"].strip()

        # --- coleta arquivos ---
        if caminho.is_file() and caminho.suffix.lower() == ".ofx":
            arquivos  = [caminho]
            pasta_base = caminho.parent
        elif caminho.is_dir():
            arquivos   = sorted(caminho.rglob("*.ofx"))
            pasta_base = caminho
        else:
            raise CommandError(f"Caminho inválido: {caminho}")

        if not arquivos:
            self.stdout.write(self.style.WARNING(f"Nenhum OFX encontrado em {caminho}"))
            return

        self.stdout.write(self.style.NOTICE(f"{len(arquivos)} arquivo(s) encontrado(s)."))

        # --- resolve instituição ---
        if inst_force:
            inst = InstituicaoFinanceira.objects.filter(nome__iexact=inst_force).first()
            if not inst:
                raise CommandError(f"Instituição não encontrada: {inst_force!r}")
        else:
            inst = None
            for seg in reversed(pasta_base.parts):
                seg_clean = seg.strip().lower()
                try:
                    inst = InstituicaoFinanceira.objects.get(codigo__iexact=seg_clean)
                    break
                except InstituicaoFinanceira.DoesNotExist:
                    continue
            if not inst:
                raise CommandError(
                    "InstituiçãoFinanceira não encontrada pelo caminho. "
                    "Use --instituicao para forçar ou cadastre o código da pasta."
                )

        self.stdout.write(self.style.HTTP_INFO(f"Instituição: {inst.nome}"))

        # --- membro ---
        if titular_nome:
            membro_inferido = Membro.objects.filter(nome__iexact=titular_nome).first()
        else:
            membro_inferido = _inferir_membro_por_pasta(pasta_base)

        if membro_inferido:
            self.stdout.write(self.style.HTTP_INFO(f"Membro: {membro_inferido.nome}"))
        else:
            self.stdout.write(self.style.WARNING("Nenhum membro inferido — conta ficará sem titular."))

        # --- contadores partilhados por referência ---
        contadores = {"proc": 0, "novos": 0, "pulados": 0, "sem_data": 0, "saldo_ant": 0}

        for caminho_ofx in arquivos:
            self.stdout.write(self.style.NOTICE(f"\n→ {caminho_ofx.name}"))
            try:
                self._importar_arquivo(
                    caminho_ofx, inst, membro_inferido, pasta_base,
                    dry_run, do_reset, contadores,
                )
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  ERRO: {exc}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Concluído{'  [dry-run]' if dry_run else ''}. "
            f"Novos: {contadores['novos']} | Pulados: {contadores['pulados']} | "
            f"Sem data: {contadores['sem_data']} | Saldo Anterior ignorado: {contadores['saldo_ant']}"
        ))

    # -----------------------------------------------------------------------
    def _importar_arquivo(
        self,
        caminho_ofx: Path,
        inst: InstituicaoFinanceira,
        membro_inferido: Membro | None,
        pasta_base: Path,
        dry_run: bool,
        do_reset: bool,
        contadores: dict,
    ):
        raw   = caminho_ofx.read_bytes()
        fixed = preprocess_ofx(raw)
        ofx   = OfxParser.parse(BytesIO(fixed))

        contas_ofx = getattr(ofx, "accounts", None) or [getattr(ofx, "account", None)]
        contas_ofx = [c for c in contas_ofx if c is not None]

        for conta_ofx in contas_ofx:
            numero = str(
                getattr(conta_ofx, "number", None) or
                getattr(conta_ofx, "account_id", "desconhecido")
            ).strip()

            # --- get_or_create ContaCorrente ---
            conta, criada = ContaCorrente.objects.get_or_create(
                instituicao=inst,
                numero=numero,
                defaults={
                    "agencia":  None,
                    "membro":   membro_inferido,
                    "ativa":    True,
                },
            )
            if criada:
                self.stdout.write(self.style.SUCCESS(f"  Nova conta criada: {numero}"))
            if not conta.membro and membro_inferido:
                conta.membro = membro_inferido
                conta.save(update_fields=["membro"])

            statement = getattr(conta_ofx, "statement", None)
            txs = statement.transactions if statement else []
            if not txs:
                self.stdout.write(self.style.WARNING("  Nenhuma transação no arquivo."))
                continue

            # --- calcula período do extrato ---
            datas_validas = []
            for tx in txs:
                d = tx.date
                if isinstance(d, datetime):
                    d = d.date()
                if d and d.year >= 2000:
                    datas_validas.append(d)

            dt_inicio = getattr(statement, "start_date", None)
            dt_fim    = getattr(statement, "end_date",   None)
            if isinstance(dt_inicio, datetime):
                dt_inicio = dt_inicio.date()
            if isinstance(dt_fim, datetime):
                dt_fim = dt_fim.date()

            if not dt_inicio and datas_validas:
                dt_inicio = min(datas_validas)
            if not dt_fim and datas_validas:
                dt_fim = max(datas_validas)

            if not dt_inicio or not dt_fim:
                self.stderr.write(self.style.ERROR("  Não foi possível determinar o período do extrato. Pulando."))
                continue

            arquivo_hash = _sha1(caminho_ofx.read_bytes().decode("latin-1", errors="replace"))

            if do_reset and not dry_run:
                deletados, _ = Extrato.objects.filter(
                    conta=conta,
                    data_inicio=dt_inicio,
                    data_fim=dt_fim,
                ).delete()
                if deletados:
                    self.stdout.write(self.style.WARNING(
                        f"  Extrato {dt_inicio}→{dt_fim} removido (cascade: {deletados} objetos)."
                    ))

            # --- get/create Extrato ---
            if dry_run:
                extrato = None
            else:
                extrato, extrato_criado = Extrato.objects.get_or_create(
                    conta=conta,
                    data_inicio=dt_inicio,
                    data_fim=dt_fim,
                    defaults={
                        "arquivo_hash": arquivo_hash,
                        "fonte_arquivo": str(caminho_ofx),
                    },
                )
                if not extrato_criado:
                    if extrato.arquivo_hash == arquivo_hash:
                        self.stdout.write(self.style.SUCCESS(
                            f"  Extrato {dt_inicio}→{dt_fim} já importado (hash igual). Pulando."
                        ))
                        return
                    self.stdout.write(self.style.WARNING(
                        f"  Extrato {dt_inicio}→{dt_fim} já existe mas hash diferente — continuando (use --reset para reimportar)."
                    ))

            # --- processa transações ---
            novos_neste_arquivo = 0
            for tx in txs:
                data = tx.date
                if isinstance(data, datetime):
                    data = data.date()
                if data is None:
                    contadores["sem_data"] += 1
                    continue
                if data.year < 2000:
                    continue

                # filtra "saldo anterior"
                desc_base = (
                    getattr(tx, "memo", "") or
                    getattr(tx, "payee", "") or
                    getattr(tx, "name", "") or ""
                ).strip().lower()
                if "saldo anterior" in desc_base:
                    contadores["saldo_ant"] += 1
                    continue

                descricao = _normalizar(_compose_descricao(tx))
                valor     = Decimal(str(tx.amount))

                fitid_original = (
                    getattr(tx, "id", None) or
                    getattr(tx, "fitid", None) or ""
                )

                # resolve fitid único
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

                contadores["proc"] += 1

                if dry_run:
                    self.stdout.write(f"  [dry] {data}  {valor:+10.2f}  {descricao[:60]}")
                    novos_neste_arquivo += 1
                    contadores["novos"] += 1
                    continue

                # dedup: fitid já existe nesta conta?
                if _fitid_ja_existe(conta, fitid):
                    contadores["pulados"] += 1
                    continue

                hash_linha = _sha1(fitid)

                with transaction.atomic():
                    Transacao.objects.create(
                        extrato       = extrato,
                        data          = data,
                        descricao     = descricao,
                        valor         = valor,
                        fitid         = fitid,
                        hash_linha    = hash_linha,
                        hash_ordem    = 1,
                        is_duplicado  = False,
                    )

                novos_neste_arquivo += 1
                contadores["novos"] += 1

            self.stdout.write(self.style.SUCCESS(
                f"  {dt_inicio} → {dt_fim} | {novos_neste_arquivo} nova(s) | "
                f"{contadores['pulados']} pulada(s)"
            ))
