"""
Inverte o sinal de todas as transações de cartão de crédito existentes.

Convenção anterior: gastos positivos, pagamentos negativos.
Convenção nova:     gastos negativos,  pagamentos positivos (igual à conta corrente).
"""
from django.db import migrations


def inverter_sinal(apps, schema_editor):
    Transacao = apps.get_model("cartao_credito", "Transacao")
    # Faz em batches para não travar o DB em bases grandes
    ids = list(Transacao.objects.values_list("pk", flat=True))
    BATCH = 500
    for i in range(0, len(ids), BATCH):
        batch_ids = ids[i : i + BATCH]
        for t in Transacao.objects.filter(pk__in=batch_ids):
            t.valor = -t.valor
            t.save(update_fields=["valor"])


def reverter_sinal(apps, schema_editor):
    # Invertendo de volta é a mesma operação
    inverter_sinal(apps, schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("cartao_credito", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(inverter_sinal, reverter_sinal),
    ]
