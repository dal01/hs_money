# conta_corrente/management/commands/importar_pdf_caixa.py
"""
Management command para importar extratos PDF da Caixa Econômica Federal.

Uso:
    python manage.py importar_pdf_caixa
    python manage.py importar_pdf_caixa --dry-run
    python manage.py importar_pdf_caixa --arquivo data/conta_corrente/dalton/2024/cx/202411.pdf
    python manage.py importar_pdf_caixa --membro dalton --instituicao cx
    python manage.py importar_pdf_caixa --reset
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from hs_money.core.models import InstituicaoFinanceira, Membro
from hs_money.conta_corrente.services.importar_pdf_caixa import importar_arquivo_pdf_caixa


class Command(BaseCommand):
    help = "Importa extratos PDF da Caixa Econômica Federal para o banco de dados."

    def add_arguments(self, parser):
        parser.add_argument(
            "--arquivo",
            nargs="*",
            metavar="PDF",
            help="Caminho(s) explícito(s) do PDF. Se omitido, varre DADOS_DIR/conta_corrente/**/cx/*.pdf",
        )
        parser.add_argument(
            "--membro",
            default=None,
            help="Nome (ou slug) do membro titular. Se omitido, infere pelo caminho.",
        )
        parser.add_argument(
            "--instituicao",
            default=None,
            help="Código da instituição (ex.: cx). Se omitido, infere pelo caminho.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Apenas conta os registros, não grava nada.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            default=False,
            help="Remove extratos existentes do mesmo período antes de reimportar.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reset   = options["reset"]

        # --- resolve instituição ---
        inst = None
        if options["instituicao"]:
            cod = options["instituicao"].strip()
            inst = InstituicaoFinanceira.objects.filter(codigo__iexact=cod).first()
            if not inst:
                raise CommandError(f"Instituição com código '{cod}' não encontrada.")

        # --- resolve membro ---
        membro = None
        if options["membro"]:
            nome = options["membro"].strip()
            membro = (
                Membro.objects.filter(nome__iexact=nome).first()
                or Membro.objects.filter(nome__icontains=nome).first()
            )
            if not membro:
                raise CommandError(f"Membro '{nome}' não encontrado.")

        # --- lista de arquivos ---
        if options["arquivo"]:
            arquivos = [Path(p) for p in options["arquivo"]]
        else:
            dados_dir = getattr(settings, "DADOS_DIR", Path(settings.BASE_DIR) / "data")
            raiz = dados_dir / "conta_corrente"
            arquivos = sorted(raiz.rglob("*.pdf")) if raiz.exists() else []
            if not arquivos:
                self.stdout.write(self.style.WARNING(
                    f"Nenhum PDF encontrado em {raiz}"
                ))
                return

        if dry_run:
            self.stdout.write(self.style.WARNING("=== DRY-RUN — nada será gravado ==="))

        totais = {"novos": 0, "pulados": 0, "erros": 0, "ignorados": 0}

        for caminho in arquivos:
            if not caminho.exists():
                self.stdout.write(self.style.ERROR(f"  [ERRO] Arquivo não encontrado: {caminho}"))
                totais["erros"] += 1
                continue

            r = importar_arquivo_pdf_caixa(
                caminho,
                inst=inst,
                membro=membro,
                dry_run=dry_run,
                reset=reset,
            )

            cor = {
                "ok":       self.style.SUCCESS,
                "ignorado": self.style.WARNING,
                "erro":     self.style.ERROR,
            }.get(r.status, self.style.SUCCESS)

            self.stdout.write(cor(
                f"  [{r.status.upper():8}] {r.arquivo}"
                + (f" — {r.conta_str}" if r.conta_str else "")
                + (f" — {r.periodo}" if r.periodo else "")
                + (f" — {r.novos} novos, {r.pulados} pulados" if r.status == "ok" else "")
                + (f" — {r.erro}" if r.erro else "")
            ))
            for av in r.avisos:
                self.stdout.write(f"       ⚠ {av}")

            totais["novos"]    += r.novos
            totais["pulados"]  += r.pulados
            totais["erros"]    += 1 if r.status == "erro" else 0
            totais["ignorados"] += 1 if r.status == "ignorado" else 0

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Concluído — {totais['novos']} novos | {totais['pulados']} pulados "
            f"| {totais['ignorados']} ignorados | {totais['erros']} erros"
        ))
