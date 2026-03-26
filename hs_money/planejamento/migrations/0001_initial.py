from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0005_add_ordem_to_membro'),
    ]

    operations = [
        migrations.CreateModel(
            name='LancamentoPlanejado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('descricao', models.CharField(max_length=200, verbose_name='Descrição')),
                ('valor', models.DecimalField(decimal_places=2, help_text='Positivo = crédito (recebimento), negativo = débito (pagamento)', max_digits=12, verbose_name='Valor')),
                ('tipo', models.CharField(choices=[('pontual', 'Pontual'), ('recorrente', 'Recorrente')], default='pontual', max_length=20, verbose_name='Tipo')),
                ('data', models.DateField(blank=True, help_text='Data do lançamento (para tipo pontual)', null=True, verbose_name='Data')),
                ('dia_do_mes', models.PositiveSmallIntegerField(blank=True, help_text='Dia do mês para pagamento/recebimento (1–28)', null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(28)], verbose_name='Dia do mês')),
                ('data_inicio', models.DateField(blank=True, help_text='Mês de início da recorrência', null=True, verbose_name='Data início')),
                ('data_fim', models.DateField(blank=True, help_text='Mês de encerramento (deixe em branco para indeterminado)', null=True, verbose_name='Data fim')),
                ('ativo', models.BooleanField(default=True, verbose_name='Ativo')),
                ('anotacao', models.TextField(blank=True, default='', verbose_name='Anotação')),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('atualizado_em', models.DateTimeField(auto_now=True)),
                ('categoria', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='lancamentos_planejados', to='core.categoria', verbose_name='Categoria')),
                ('membro', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='lancamentos_planejados', to='core.membro', verbose_name='Membro')),
            ],
            options={
                'verbose_name': 'Lançamento Planejado',
                'verbose_name_plural': 'Lançamentos Planejados',
                'ordering': ['tipo', 'dia_do_mes', 'data', 'descricao'],
            },
        ),
        migrations.CreateModel(
            name='AjusteCartaoMes',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mes', models.DateField(help_text='Informe qualquer dia do mês; será normalizado para o dia 1.', verbose_name='Mês')),
                ('valor', models.DecimalField(decimal_places=2, help_text='Valor POSITIVO que será subtraído da base de cálculo da média.', max_digits=12, verbose_name='Valor a excluir')),
                ('descricao', models.CharField(max_length=200, verbose_name='Descrição')),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Ajuste de Cartão (mês)',
                'verbose_name_plural': 'Ajustes de Cartão',
                'ordering': ['-mes'],
            },
        ),
    ]
