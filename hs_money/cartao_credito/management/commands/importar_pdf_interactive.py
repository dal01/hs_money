from __future__ import annotations

from pathlib import Path
from typing import Iterable, Set

from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings


def iter_pdfs(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
    else:
        yield from sorted(path.rglob("*.pdf"))


def parse_selection(s: str, max_i: int) -> Set[int]:
    s = (s or "").strip().lower()
    if not s:
        return set()
    if s == "all":
        return set(range(1, max_i + 1))

    result: Set[int] = set()
    for part in s.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                a, b = part.split('-', 1)
                ia, ib = int(a), int(b)
                if ia > ib:
                    ia, ib = ib, ia
                for i in range(ia, ib + 1):
                    if 1 <= i <= max_i:
                        result.add(i)
            except Exception:
                continue
        else:
            try:
                i = int(part)
                if 1 <= i <= max_i:
                    result.add(i)
            except Exception:
                continue
    return result


class Command(BaseCommand):
    help = "Interactive PDF importer: lista PDFs, permite seleção e invoca importar_pdf_cartao_bb."

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default=None, help='Pasta ou PDF para listar')
        parser.add_argument('--dry-run', action='store_true', help='Simula sem gravar (passa para o importador)')

    def handle(self, *args, **opts):
        raw_path = opts.get('path')
        dry = opts.get('dry_run', False)

        if raw_path:
            base_path = Path(raw_path)
        else:
            # fallback para settings.DADOS_DIR/cartao_credito ou ./data/cartao_credito
            base_path = Path(getattr(settings, 'DADOS_DIR', Path.cwd())) / 'cartao_credito'

        if not base_path.exists():
            # tenta relativo a settings.DADOS_DIR
            alt = Path(getattr(settings, 'DADOS_DIR', Path.cwd())) / str(base_path)
            if alt.exists():
                base_path = alt

        if not base_path.exists():
            self.stderr.write(f'Caminho inválido: {base_path}')
            return

        pdfs = list(iter_pdfs(base_path))
        if not pdfs:
            self.stdout.write(self.style.WARNING(f'Nenhum PDF encontrado em {base_path}'))
            return

        self.stdout.write(self.style.SUCCESS(f'Encontrados {len(pdfs)} PDFs em {base_path}'))
        for idx, p in enumerate(pdfs, start=1):
            self.stdout.write(f'{idx:3d}: {p.name}  ({p.stat().st_size} bytes)')

        sel = input('Selecione arquivos (ex: 1-3,5 ou all). Enter para cancelar: ').strip()
        indices = parse_selection(sel, len(pdfs))
        if not indices:
            self.stdout.write('Nenhuma seleção feita — abortando.')
            return

        selected = [pdfs[i - 1] for i in sorted(indices)]
        self.stdout.write(f'Selecionados {len(selected)} arquivos:')
        for p in selected:
            self.stdout.write(f' - {p}')

        confirmar = input(f'Confirmar import (y/N)? (dry-run={dry}): ').strip().lower()
        if confirmar != 'y':
            self.stdout.write('Aborted by user.')
            return

        imported = 0
        errors = 0
        for p in selected:
            try:
                self.stdout.write(self.style.NOTICE(f'Importando {p} (dry-run={dry})'))
                # chama o comando existente para cada arquivo
                call_command('importar_pdf_cartao_bb', str(p), dry_run=dry)
                imported += 1
            except Exception as e:
                errors += 1
                self.stderr.write(self.style.ERROR(f'Erro importando {p}: {e}'))

        self.stdout.write(self.style.SUCCESS(f'Concluído: importados={imported} erros={errors}'))
