# conta_corrente/services/importar_pdf_caixa.py
"""
Serviço de importação de extratos PDF da Caixa Econômica Federal.

Segue a mesma interface de importar.py (ResultadoArquivo), podendo ser
chamado de views, management commands ou tarefas agendadas.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from django.db import transaction as db_transaction

from hs_money.core.models import InstituicaoFinanceira, Membro
from hs_money.conta_corrente.models import ContaCorrente, Extrato, Transacao
from hs_money.conta_corrente.parsers.caixa.extrato_pdf import (
    parse_extrato_pdf,
    ResultadoParsePDF,
)
from hs_money.conta_corrente.services.importar import (
    ResultadoArquivo,
    _inferir_membro_por_pasta,
    _inferir_inst_por_pasta,
    _sha1,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_pdf(caminho: Path) -> str:
    """Hash SHA-1 do conteúdo binário do PDF."""
    return hashlib.sha1(caminho.read_bytes()).hexdigest()


def _fitid_para_lancamento(l) -> str:
    """FITID derivado do hash_linha + hash_ordem, igual ao padrão OFX do projeto."""
    return f"{l.hash_linha}__{l.hash_ordem}"


# ---------------------------------------------------------------------------
# Função pública principal
# ---------------------------------------------------------------------------

def importar_arquivo_pdf_caixa(
    caminho_pdf: Path,
    inst:    Optional[InstituicaoFinanceira] = None,
    membro:  Optional[Membro]               = None,
    dry_run: bool = False,
    reset:   bool = False,
) -> ResultadoArquivo:
    """
    Importa um único PDF de extrato da Caixa para o banco de dados.

    Se `inst` / `membro` forem None, tenta inferir pelo caminho de pastas.
    Retorna :class:`ResultadoArquivo` (mesma estrutura do importar OFX).
    """
    result = ResultadoArquivo(arquivo=caminho_pdf.name)

    # --- parse PDF ---
    parsed: ResultadoParsePDF = parse_extrato_pdf(caminho_pdf)

    if parsed.erro:
        result.status = "erro"
        result.erro   = parsed.erro
        return result

    for av in parsed.avisos:
        result.avisos.append(av)

    pasta = caminho_pdf.parent

    # --- instituição ---
    inst_resolvida = inst or _inferir_inst_por_pasta(pasta)
    if not inst_resolvida:
        # Última tentativa: busca pela palavra "caixa" no caminho
        inst_resolvida = (
            InstituicaoFinanceira.objects
            .filter(nome__icontains="caixa")
            .first()
        )
    if not inst_resolvida:
        result.status = "erro"
        result.erro   = (
            "Instituição não detectada. Cadastre um código 'cx' para a Caixa "
            "ou coloque o PDF numa pasta cujo nome bata com esse código."
        )
        return result

    # --- membro ---
    membro_resolvido = membro or _inferir_membro_por_pasta(pasta)
    if not membro_resolvido and parsed.conta:
        # tenta pelo nome do cliente no próprio PDF
        nome_cliente = parsed.conta.cliente
        if nome_cliente:
            from unidecode import unidecode
            import re as _re
            slug_cliente = _re.sub(r"[^a-z0-9]+", "-", unidecode(nome_cliente.lower())).strip("-")
            for m_obj in Membro.objects.all():
                slug_m = _re.sub(r"[^a-z0-9]+", "-", unidecode(m_obj.nome.lower())).strip("-")
                if slug_m and slug_m in slug_cliente:
                    membro_resolvido = m_obj
                    break
    if not membro_resolvido:
        result.avisos.append("Membro não detectado — conta ficará sem titular.")

    # --- conta corrente ---
    numero = parsed.conta.numero if parsed.conta else "desconhecido"
    agencia = parsed.conta.agencia if parsed.conta else None

    conta, criada = ContaCorrente.objects.get_or_create(
        instituicao=inst_resolvida,
        numero=numero,
        defaults={"agencia": agencia, "membro": membro_resolvido, "ativa": True},
    )
    if criada:
        result.conta_criada = True
    if not conta.membro and membro_resolvido:
        conta.membro = membro_resolvido
        conta.save(update_fields=["membro"])

    result.conta_str = f"{inst_resolvida.nome} — cc {numero}"

    lancamentos = parsed.lancamentos
    if not lancamentos:
        result.avisos.append("Nenhum lançamento no PDF.")
        return result

    # --- período ---
    datas = [l.data for l in lancamentos]
    dt_inicio = min(datas)
    dt_fim    = max(datas)
    result.periodo = f"{dt_inicio} → {dt_fim}"

    arquivo_hash = _hash_pdf(caminho_pdf)

    if reset and not dry_run:
        Extrato.objects.filter(conta=conta, data_inicio=dt_inicio, data_fim=dt_fim).delete()

    # --- extrato ---
    if dry_run:
        extrato = None
    else:
        extrato, extrato_criado = Extrato.objects.get_or_create(
            conta=conta,
            data_inicio=dt_inicio,
            data_fim=dt_fim,
            defaults={"arquivo_hash": arquivo_hash, "fonte_arquivo": str(caminho_pdf)},
        )
        if not extrato_criado:
            if extrato.arquivo_hash == arquivo_hash:
                result.status = "ignorado"
                result.avisos.append(
                    f"Extrato {result.periodo} já importado com hash igual — pulado."
                )
                return result
            result.avisos.append(
                f"Extrato {result.periodo} já existe mas hash diferente — reimportando lançamentos novos."
            )

    # --- lançamentos ---
    for l in lancamentos:
        fitid = _fitid_para_lancamento(l)

        if dry_run:
            result.novos += 1
            continue

        if Transacao.objects.filter(extrato__conta=conta, fitid=fitid).exists():
            result.pulados += 1
            continue

        with db_transaction.atomic():
            Transacao.objects.create(
                extrato    = extrato,
                data       = l.data,
                tipo       = "",            # PDF não tem tipo estruturado
                descricao  = l.descricao,
                valor      = l.valor,
                fitid      = fitid,
                hash_linha = l.hash_linha,
                hash_ordem = l.hash_ordem,
                is_duplicado = l.is_duplicado,
            )
        result.novos += 1

    return result


def importar_lista_pdf_caixa(
    caminhos: List[Path],
    inst:    Optional[InstituicaoFinanceira] = None,
    membro:  Optional[Membro]               = None,
    dry_run: bool = False,
    reset:   bool = False,
) -> List[ResultadoArquivo]:
    return [
        importar_arquivo_pdf_caixa(p, inst=inst, membro=membro, dry_run=dry_run, reset=reset)
        for p in caminhos
    ]
