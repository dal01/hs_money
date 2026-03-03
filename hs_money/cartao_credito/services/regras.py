from __future__ import annotations
from typing import Iterable, Dict, List, Tuple, Set

from django.db import transaction

from cartao_credito.models import Lancamento, RegraMembroCartao


def aplicar_regras_em_lancamento(
    l: Lancamento,
    pular_se_ja_tem_membros: bool = True,
) -> Tuple[List[int], bool]:
    """
    Aplica TODAS as regras ativas ao lançamento.
    - Se pular_se_ja_tem_membros=True e o lançamento já possui membros, NÃO altera nada.
    Retorna (lista_final_ids, alterou_bool).
    """
    # Se já tem qualquer membro atribuído, respeita a seleção manual e não mexe
    if pular_se_ja_tem_membros and l.membros.exists():
        return list(l.membros.values_list("id", flat=True)), False

    regras = (
        RegraMembroCartao.objects
        .filter(ativo=True)
        .prefetch_related("membros")
        .order_by("prioridade", "id")
    )
    membros_ids: Set[int] = set()

    # titular do cartão (para uso em regra.membro_cartao)
    cartao_membro_id = getattr(getattr(getattr(l, "fatura", None), "cartao", None), "membro_id", None)

    for r in regras:
        if r.aplica_para(l.descricao, l.valor, cartao_membro_id=cartao_membro_id):
            membros_ids.update(r.membros.values_list("id", flat=True))

    # Define a associação final (ordenada para previsibilidade)
    ids_ordenados = sorted(membros_ids)
    l.membros.set(ids_ordenados)
    return ids_ordenados, True


@transaction.atomic
def aplicar_regras_em_queryset(
    qs: Iterable[Lancamento],
    pular_se_ja_tem_membros: bool = True,
) -> Dict[int, List[int]]:
    """
    Aplica regras em um conjunto de lançamentos. Respeita 'pular_se_ja_tem_membros'.
    Retorna {lancamento_id: [membro_ids...]} apenas dos lançamentos que foram efetivamente alterados.
    """
    # Evita N+1: traz o titular do cartão junto + M2M atual
    qs = qs.select_related("fatura", "fatura__cartao", "fatura__cartao__membro").prefetch_related("membros")

    resultado: Dict[int, List[int]] = {}
    for l in qs:
        ids, alterou = aplicar_regras_em_lancamento(l, pular_se_ja_tem_membros=pular_se_ja_tem_membros)
        if alterou:
            resultado[l.id] = ids
    return resultado
