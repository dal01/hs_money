from django.http import HttpResponse

from django.shortcuts import render
from django.conf import settings
from pathlib import Path
from django.core.management import call_command
from io import StringIO


def import_pdf_web(request):
    # determina pasta base de PDFs
    base = Path(getattr(settings, 'DADOS_DIR', Path.cwd())) / 'cartao_credito'
    if not base.exists():
        # fallback para projeto/data/cartao_credito
        base = Path(settings.BASE_DIR) / 'data' / 'cartao_credito'

    pdfs = []
    if base.exists():
        for p in sorted(base.rglob('*.pdf')):
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            pdfs.append({'path': str(p), 'name': p.name, 'size': size})

    results = []
    if request.method == 'POST':
        selected = request.POST.getlist('files')
        dry = request.POST.get('dry') == 'on'
        for fp in selected:
            buf = StringIO()
            try:
                call_command('importar_pdf_cartao_bb', fp, dry_run=dry, stdout=buf)
                out = buf.getvalue()
                results.append({'file': fp, 'ok': True, 'output': out})
            except Exception as e:
                results.append({'file': fp, 'ok': False, 'output': str(e)})

    return render(request, 'cartao_credito/import_web.html', {
        'pdfs': pdfs,
        'results': results,
    })


def index(request):
    return HttpResponse('App cartao_credito funcionando')
