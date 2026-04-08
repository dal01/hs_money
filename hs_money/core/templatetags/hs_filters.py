from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_url(context, field, default_dir='asc'):
    """
    Retorna a URL com ?order=<field>&dir=<asc|desc> mantendo todos os outros
    parâmetros GET.  Se a coluna já estiver ativa, inverte a direção.
    """
    request = context.get('request')
    if not request:
        return ''
    params = request.GET.copy()
    params.pop('tab', None)   # ordenar sempre abre a aba visível
    current_order = params.get('order', '')
    current_dir   = params.get('dir',   '')
    if current_order == field:
        new_dir = 'asc' if current_dir == 'desc' else 'desc'
    else:
        new_dir = default_dir
    params['order'] = field
    params['dir']   = new_dir
    return '?' + params.urlencode()


@register.filter
def brl(value):
    """
    Formata um número no padrão brasileiro: 1.234.567,89
    Sem prefixo R$.  Valores negativos ficam -1.234,56
    """
    try:
        v = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value

    neg = v < 0
    formatted = f"{abs(v):,.2f}"                             # 1,234.56
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")  # 1.234,56

    return f"-{formatted}" if neg else formatted


@register.filter
def dict_get(d, key):
    """Acessa d[key] em templates. Retorna None se não encontrar."""
    if d is None:
        return None
    return d.get(key)


@register.filter
def abs(value):
    """Retorna o valor absoluto de um número."""
    try:
        v = Decimal(str(value))
        return v if v >= 0 else -v
    except (InvalidOperation, TypeError, ValueError):
        return value
