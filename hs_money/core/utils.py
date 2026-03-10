"""
core/utils.py — Utilitários compartilhados entre os apps.
"""
import re


_RE_PREFIX = re.compile(r'^((?:[\d/:.]+\s+)+)(.+)', re.DOTALL)


def limpar_prefixo_descricao(desc: str) -> str:
    """Move tokens numéricos/de data/hora no início da descrição para o final.

    Tokens considerados "prefixo" são sequências de dígitos, /, :, .
    Exemplos:
        '01/08 09:04 nilton massahito'  → 'nilton massahito (01/08 09:04)'
        '033 4551 81001274172 sergio'   → 'sergio (033 4551 81001274172)'
        'bb rf ref di plus agil'        → 'bb rf ref di plus agil'  (sem mudança)
    """
    if not desc:
        return desc
    desc = desc.strip()
    m = _RE_PREFIX.match(desc)
    if not m:
        return desc
    prefix = m.group(1).strip()
    rest   = m.group(2).strip()
    if not rest:
        return desc
    return f'{rest} ({prefix})'
