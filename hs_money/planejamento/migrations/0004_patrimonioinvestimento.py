from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('investimentos', '0001_initial'),
        ('planejamento', '0003_lancamentoplanejado_mes_do_ano'),
    ]

    operations = [
        migrations.CreateModel(
            name='PatrimonioInvestimento',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('investimento', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='patrimonio_config',
                    to='investimentos.investimento',
                    verbose_name='Investimento',
                )),
            ],
            options={
                'verbose_name': 'Investimento no Patrimônio',
                'verbose_name_plural': 'Investimentos no Patrimônio',
            },
        ),
    ]
