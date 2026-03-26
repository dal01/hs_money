from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('planejamento', '0002_lancamentoplanejado_periodicidade'),
    ]

    operations = [
        migrations.AddField(
            model_name='lancamentoplanejado',
            name='mes_do_ano',
            field=models.PositiveSmallIntegerField(
                verbose_name='Mês',
                null=True,
                blank=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(12),
                ],
                help_text='Mês de ocorrência (apenas para periodicidade anual)',
            ),
        ),
    ]
