from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('planejamento', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='lancamentoplanejado',
            name='periodicidade',
            field=models.CharField(
                verbose_name='Periodicidade',
                max_length=10,
                choices=[('mensal', 'Mensal'), ('anual', 'Anual')],
                default='mensal',
            ),
        ),
    ]
