from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('investimentos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='investimento',
            name='tipo_financeiro',
            field=models.CharField(
                max_length=8,
                choices=[('CREDITO', 'Crédito (ativo)'), ('DEBITO', 'Débito (dívida)')],
                default='CREDITO',
                verbose_name='Tipo financeiro',
            ),
        ),
    ]
