from django.db import models

from ..core.models import Membro, InstituicaoFinanceira


class Investimento(models.Model):
    """Produto de investimento (fundo, tesouro, ações, etc.)."""

    TIPO_CHOICES = [
        ('FUNDO_RF',  'Fundo Renda Fixa'),
        ('FUNDO_RV',  'Fundo Renda Variável'),
        ('TESOURO',   'Tesouro Direto'),
        ('ACAO',      'Ação'),
        ('OUTRO',     'Outro'),
    ]

    TIPO_FINANCEIRO_CHOICES = [
        ('CREDITO', 'Crédito (ativo)'),
        ('DEBITO',  'Débito (dívida)'),
    ]

    nome = models.CharField('Nome', max_length=200)
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES, default='FUNDO_RF')
    tipo_financeiro = models.CharField('Tipo financeiro', max_length=8, choices=TIPO_FINANCEIRO_CHOICES, default='CREDITO')
    instituicao = models.ForeignKey(
        InstituicaoFinanceira,
        on_delete=models.CASCADE,
        related_name='investimentos',
    )
    membro = models.ForeignKey(
        Membro,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='investimentos',
    )
    ativo = models.BooleanField('Ativo', default=True)

    class Meta:
        verbose_name = 'Investimento'
        verbose_name_plural = 'Investimentos'
        ordering = ['membro', 'nome']
        constraints = [
            models.UniqueConstraint(
                fields=['instituicao', 'membro', 'nome'],
                name='uniq_invest_inst_membro_nome',
            ),
        ]

    def __str__(self) -> str:
        membro = f" ({self.membro})" if self.membro_id else ''
        return f"{self.nome}{membro}"


class Movimentacao(models.Model):
    """Aplicação ou resgate em um investimento."""

    TIPO_APLICACAO = 'APL'
    TIPO_RESGATE   = 'RES'
    TIPO_CHOICES = [
        (TIPO_APLICACAO, 'Aplicação'),
        (TIPO_RESGATE,   'Resgate'),
    ]

    investimento = models.ForeignKey(
        Investimento,
        on_delete=models.CASCADE,
        related_name='movimentacoes',
    )
    data = models.DateField('Data')
    tipo = models.CharField('Tipo', max_length=3, choices=TIPO_CHOICES)
    valor = models.DecimalField('Valor', max_digits=14, decimal_places=2)
    descricao = models.CharField('Descrição', max_length=255, blank=True, default='')
    anotacao = models.CharField(
        'Anotação', max_length=255, blank=True, null=True,
        help_text='Comentário ou identificação manual.',
    )

    class Meta:
        verbose_name = 'Movimentação'
        verbose_name_plural = 'Movimentações'
        ordering = ['-data']
        indexes = [
            models.Index(fields=['investimento', 'data']),
        ]

    def __str__(self) -> str:
        tipo = self.get_tipo_display()
        return f"{self.data} — {self.investimento} {tipo} R$ {self.valor}"


class SaldoInvestimento(models.Model):
    """Snapshot de saldo de um investimento em uma data."""

    investimento = models.ForeignKey(
        Investimento,
        on_delete=models.CASCADE,
        related_name='saldos',
    )
    data = models.DateField('Data de referência')
    saldo = models.DecimalField('Saldo', max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = 'Saldo de Investimento'
        verbose_name_plural = 'Saldos de Investimentos'
        ordering = ['-data']
        constraints = [
            models.UniqueConstraint(
                fields=['investimento', 'data'],
                name='uniq_saldo_invest_data',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.investimento} — {self.data}: R$ {self.saldo}"
