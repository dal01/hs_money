import calendar
from datetime import date
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class LancamentoPlanejado(models.Model):
    TIPO_PONTUAL = 'pontual'
    TIPO_RECORRENTE = 'recorrente'
    TIPO_CHOICES = [
        (TIPO_PONTUAL, 'Pontual'),
        (TIPO_RECORRENTE, 'Recorrente'),
    ]

    PERIOD_MENSAL = 'mensal'
    PERIOD_ANUAL  = 'anual'
    PERIOD_CHOICES = [
        (PERIOD_MENSAL, 'Mensal'),
        (PERIOD_ANUAL,  'Anual'),
    ]

    descricao = models.CharField('Descrição', max_length=200)
    valor = models.DecimalField(
        'Valor', max_digits=12, decimal_places=2,
        help_text='Positivo = crédito (recebimento), negativo = débito (pagamento)',
    )
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES, default=TIPO_PONTUAL)

    # Pontual-specific
    data = models.DateField(
        'Data', null=True, blank=True,
        help_text='Data do lançamento (para tipo pontual)',
    )

    # Recorrente-specific
    periodicidade = models.CharField(
        'Periodicidade', max_length=10, choices=[
            ('mensal', 'Mensal'), ('anual', 'Anual'),
        ], default='mensal',
    )
    dia_do_mes = models.PositiveSmallIntegerField(
        'Dia do mês', null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text='Dia do mês para pagamento/recebimento (1–28)',
    )
    mes_do_ano = models.PositiveSmallIntegerField(
        'Mês', null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text='Mês de ocorrência (apenas para periodicidade anual)',
    )
    data_inicio = models.DateField(
        'Data início', null=True, blank=True,
        help_text='Mês de início da recorrência',
    )
    data_fim = models.DateField(
        'Data fim', null=True, blank=True,
        help_text='Mês de encerramento (deixe em branco para indeterminado)',
    )

    categoria = models.ForeignKey(
        'core.Categoria', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='lancamentos_planejados',
        verbose_name='Categoria',
    )
    membro = models.ForeignKey(
        'core.Membro', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='lancamentos_planejados',
        verbose_name='Membro',
    )

    ativo = models.BooleanField('Ativo', default=True)
    anotacao = models.TextField('Anotação', blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Lançamento Planejado'
        verbose_name_plural = 'Lançamentos Planejados'
        ordering = ['tipo', 'dia_do_mes', 'data', 'descricao']

    def __str__(self):
        return f'{self.descricao} ({self.get_tipo_display()})'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.tipo == self.TIPO_PONTUAL and not self.data:
            raise ValidationError({'data': 'Data é obrigatória para lançamentos pontuais.'})
        if self.tipo == self.TIPO_RECORRENTE and not self.dia_do_mes:
            raise ValidationError({'dia_do_mes': 'Dia do mês é obrigatório para lançamentos recorrentes.'})
        if self.tipo == self.TIPO_RECORRENTE and self.periodicidade == self.PERIOD_ANUAL and not self.mes_do_ano:
            raise ValidationError({'mes_do_ano': 'Mês é obrigatório para recorrência anual.'})
        if (self.data_inicio and self.data_fim
                and self.data_inicio > self.data_fim):
            raise ValidationError({'data_fim': 'Data fim deve ser posterior à data início.'})

    def ocorrencias_no_periodo(self, inicio: date, fim: date) -> list[tuple[date, Decimal]]:
        """Returns list of (date, valor) tuples for this entry within [inicio, fim]."""
        if not self.ativo:
            return []

        if self.tipo == self.TIPO_PONTUAL:
            if self.data and inicio <= self.data <= fim:
                return [(self.data, self.valor)]
            return []

        if self.periodicidade == self.PERIOD_ANUAL:
            # Fires once a year on dia_do_mes / mes_do_ano
            mes_anual = self.mes_do_ano or 1
            result = []
            for ano in range(inicio.year, fim.year + 1):
                day = min(self.dia_do_mes, calendar.monthrange(ano, mes_anual)[1])
                d = date(ano, mes_anual, day)
                if self.data_inicio and d < self.data_inicio:
                    continue
                if self.data_fim and d > self.data_fim:
                    break
                if inicio <= d <= fim:
                    result.append((d, self.valor))
            return result

        # Recorrente mensal
        result = []
        ano, mes = inicio.year, inicio.month
        while True:
            if date(ano, mes, 1) > date(fim.year, fim.month, 1):
                break
            day = min(self.dia_do_mes, calendar.monthrange(ano, mes)[1])
            d = date(ano, mes, day)

            # Respect the lancamento's own date bounds
            if self.data_fim and d > self.data_fim:
                break
            if not (self.data_inicio and d < self.data_inicio):
                if inicio <= d <= fim:
                    result.append((d, self.valor))

            # Advance month
            if mes == 12:
                ano, mes = ano + 1, 1
            else:
                mes += 1
        return result


class PatrimonioInvestimento(models.Model):
    """
    Marks which investments are included in the net-worth (patrimônio líquido)
    baseline shown on the planning calendar.
    """
    investimento = models.OneToOneField(
        'investimentos.Investimento',
        on_delete=models.CASCADE,
        related_name='patrimonio_config',
        verbose_name='Investimento',
    )

    class Meta:
        verbose_name = 'Investimento no Patrimônio'
        verbose_name_plural = 'Investimentos no Patrimônio'

    def __str__(self):
        return str(self.investimento)


class AjusteCartaoMes(models.Model):
    """
    Adjustment to exclude an atypical value from the credit-card monthly average.
    Example: car purchase should not inflate the projected CC average.
    """
    mes = models.DateField(
        'Mês', help_text='Informe qualquer dia do mês; será normalizado para o dia 1.',
    )
    valor = models.DecimalField(
        'Valor a excluir', max_digits=12, decimal_places=2,
        help_text='Valor POSITIVO que será subtraído da base de cálculo da média.',
    )
    descricao = models.CharField('Descrição', max_length=200)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Ajuste de Cartão (mês)'
        verbose_name_plural = 'Ajustes de Cartão'
        ordering = ['-mes']

    def save(self, *args, **kwargs):
        # Normalize to 1st of month
        self.mes = self.mes.replace(day=1)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.mes:%m/%Y} – {self.descricao}'
