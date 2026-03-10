"""
Management command: limpar_descricoes

Corrige descrições existentes que começam com tokens numéricos/data/hora,
movendo-os para o final.

Uso:
    python manage.py limpar_descricoes
    python manage.py limpar_descricoes --dry-run   (só mostra o que seria feito)
"""
from django.core.management.base import BaseCommand

from hs_money.core.utils import limpar_prefixo_descricao
from hs_money.conta_corrente.models import Transacao as TransacaoCC
from hs_money.cartao_credito.models import Transacao as TransacaoCA


class Command(BaseCommand):
    help = "Move prefixos numéricos/data do início das descrições para o final."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Exibe as mudanças sem salvar no banco.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        total_cc, total_ca = 0, 0

        self.stdout.write("=== Conta Corrente ===")
        cc_updates = []
        for t in TransacaoCC.objects.only("id", "descricao").iterator():
            nova = limpar_prefixo_descricao(t.descricao or "")
            if nova != (t.descricao or ""):
                self.stdout.write(f"  [{t.pk}] {t.descricao!r}  =>  {nova!r}")
                t.descricao = nova
                cc_updates.append(t)
                total_cc += 1

        if cc_updates and not dry:
            TransacaoCC.objects.bulk_update(cc_updates, ["descricao"], batch_size=500)

        self.stdout.write("\n=== Cartao de Credito ===")
        ca_updates = []
        for t in TransacaoCA.objects.only("id", "descricao").iterator():
            nova = limpar_prefixo_descricao(t.descricao or "")
            if nova != (t.descricao or ""):
                self.stdout.write(f"  [{t.pk}] {t.descricao!r}  =>  {nova!r}")
                t.descricao = nova
                ca_updates.append(t)
                total_ca += 1

        if ca_updates and not dry:
            TransacaoCA.objects.bulk_update(ca_updates, ["descricao"], batch_size=500)

        modo = "[DRY-RUN] " if dry else ""
        self.stdout.write(
            self.style.SUCCESS(
                f"\n{modo}CC: {total_cc} atualizadas  |  Cartão: {total_ca} atualizadas"
            )
        )
