"""
cartao_credito/services/importar.py

Lógica de importação de faturas PDF do cartão de crédito BB.
Reutilizável por views e management commands.
"""
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pdfplumber
from django.db import transaction as db_transaction
from unidecode import unidecode

from hs_money.core.models import InstituicaoFinanceira, Membro
from hs_money.cartao_credito.models import Cartao, FaturaCartao, Transacao
from hs_money.cartao_credito.parsers.bb.dados_fatura import parse_dados_fatura
from hs_money.cartao_credito.parsers.bb.lancamentos import parse_lancamentos


# ---------------------------------------------------------------------------
# Hash
# ---------------------------------------------------------------------------

def hash_pdf(raw: bytes) -> str:
    """Hash canonico de uma fatura PDF (bytes brutos)."""
    return hashlib.sha1(raw).hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(s: str) -> str:
    s = unidecode((s or "").strip().lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _inferir_membro_por_pasta(pasta: Path) -> Optional[Membro]:
    membros = list(Membro.objects.only("id", "nome"))
    mapa = {_slug(m.nome): m for m in membros}
    ignorar = {"cartao-credito", "cartao_credito", "pdf", "dados", "data"}
    for seg in reversed(pasta.parts):
        tok = _slug(seg)
        if not tok or tok in ignorar or re.fullmatch(r"\d{4}", tok):
            continue
        if tok in mapa:
            return mapa[tok]
    return None


# ---------------------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------------------

@dataclass
class ResultadoArquivo:
    arquivo:       str
    status:        str = "ok"       # ok | ignorado | erro
    cartao_str:    str = ""
    cartao_criado: bool = False
    competencia:   str = ""
    novos:         int = 0
    pulados:       int = 0
    erro:          str = ""
    avisos:        list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def importar_arquivo_pdf_bb(
    caminho_pdf: Path,
    membro:      Optional[Membro]               = None,
    inst:        Optional[InstituicaoFinanceira] = None,
    dry_run:     bool = False,
    reset:       bool = False,
) -> ResultadoArquivo:
    result = ResultadoArquivo(arquivo=caminho_pdf.name)

    try:
        raw = caminho_pdf.read_bytes()
    except OSError as exc:
        result.status = "erro"
        result.erro = f"Não foi possível ler o arquivo: {exc}"
        return result

    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception as exc:
        result.status = "erro"
        result.erro = f"Erro ao extrair texto do PDF: {exc}"
        return result

    if not texto or len(texto.strip()) < 30:
        result.status = "erro"
        result.erro = "Pouco texto extraído. O PDF pode ser uma imagem sem OCR."
        return result

    try:
        dados = parse_dados_fatura(texto, str(caminho_pdf))
    except ValueError as exc:
        result.status = "erro"
        result.erro = str(exc)
        return result

    for obs in dados.observacoes:
        result.avisos.append(obs)

    # --- resolve membro ---
    membro_resolvido = membro or _inferir_membro_por_pasta(caminho_pdf.parent)
    if not membro_resolvido:
        result.avisos.append("Membro não detectado — cartão ficará sem titular.")

    # --- resolve instituição ---
    inst_resolvida = inst
    if not inst_resolvida:
        inst_resolvida, _ = InstituicaoFinanceira.objects.get_or_create(nome="Banco do Brasil")

    # --- resolve cartão ---
    cartao, criado = Cartao.objects.get_or_create(
        instituicao=inst_resolvida,
        bandeira=(dados.bandeira or ""),
        cartao_final=dados.cartao_final,
        defaults={"membro": membro_resolvido, "ativo": True},
    )
    if criado:
        result.cartao_criado = True
    if not cartao.membro and membro_resolvido:
        cartao.membro = membro_resolvido
        cartao.save(update_fields=["membro"])

    result.cartao_str = str(cartao)
    result.competencia = dados.competencia.strftime("%Y-%m")

    # hash baseado em bytes brutos (consistente com hash_pdf usada na listagem)
    arquivo_hash = hash_pdf(raw)

    if dry_run:
        linhas = parse_lancamentos(texto, dados)
        result.novos = len(linhas)
        return result

    if reset:
        FaturaCartao.objects.filter(cartao=cartao, competencia=dados.competencia).delete()

    # --- dedup de FaturaCartao ---
    duplicatas = list(
        FaturaCartao.objects.filter(cartao=cartao, competencia=dados.competencia).order_by("pk")
    )
    if len(duplicatas) > 1:
        ids_exc = [f.pk for f in duplicatas[:-1]]
        FaturaCartao.objects.filter(pk__in=ids_exc).delete()
        result.avisos.append(
            f"Removidos {len(ids_exc)} registro(s) duplicado(s) de FaturaCartao para {result.competencia}."
        )

    fatura, fatura_criada = FaturaCartao.objects.get_or_create(
        cartao=cartao,
        competencia=dados.competencia,
        defaults=dict(
            fechado_em=dados.fechado_em,
            vencimento_em=dados.vencimento_em,
            total=dados.total,
            arquivo_hash=arquivo_hash,
            fonte_arquivo=str(caminho_pdf),
        ),
    )

    if not fatura_criada:
        if fatura.arquivo_hash == arquivo_hash:
            result.status = "ignorado"
            result.avisos.append(f"Fatura {result.competencia} já importada (hash igual) — pulada.")
            return result
        # Arquivo diferente para mesma competência: atualiza hash
        fatura.arquivo_hash  = arquivo_hash
        fatura.fonte_arquivo = str(caminho_pdf)
        fatura.fechado_em    = dados.fechado_em
        fatura.vencimento_em = dados.vencimento_em
        fatura.total         = dados.total
        fatura.save(update_fields=["arquivo_hash", "fonte_arquivo", "fechado_em", "vencimento_em", "total"])
        result.avisos.append(
            f"Fatura {result.competencia} já existia com hash diferente — reimportando lançamentos novos."
        )

    # --- lançamentos ---
    linhas = parse_lancamentos(texto, dados)

    for l in linhas:
        valor_db = -l.valor  # convenção: gastos negativos, créditos positivos

        existe = Transacao.objects.filter(
            fatura=fatura,
            hash_linha=l.hash_linha,
            hash_ordem=l.hash_ordem,
        ).exists()
        if existe:
            result.pulados += 1
            continue

        with db_transaction.atomic():
            Transacao.objects.create(
                fatura=fatura,
                data=l.data,
                descricao=l.descricao[:255],
                cidade=l.cidade or "",
                pais=l.pais or "",
                secao=l.secao,
                valor=valor_db,
                parcela_num=l.parcela_num,
                parcela_total=l.parcela_total,
                etiqueta_parcela=l.etiqueta_parcela,
                hash_linha=l.hash_linha,
                hash_ordem=l.hash_ordem,
                is_duplicado=l.is_duplicado,
            )
        result.novos += 1

    return result
