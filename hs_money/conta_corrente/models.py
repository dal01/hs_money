from django.db import models
from django.utils import timezone

from ..core.models import Membro, InstituicaoFinanceira, Categoria


class ContaCorrente(models.Model):
    """Conta corrente vinculada a uma instituição e a um membro."""

    instituicao = models.ForeignKey(
        InstituicaoFinanceira,
        on_delete=models.CASCADE,
        related_name='contas_correntes',
    )
    membro = models.ForeignKey(
        Membro,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contas_correntes',
    )
    agencia = models.CharField('Agência', max_length=20, blank=True, null=True)
    numero = models.CharField('Número', max_length=30)
    ativa = models.BooleanField('Ativa', default=True)

    class Meta:
        verbose_name = 'Conta Corrente'
        verbose_name_plural = 'Contas Correntes'
        constraints = [
            models.UniqueConstraint(
                fields=['instituicao', 'agencia', 'numero'],
                name='uniq_conta_inst_agencia_numero',
            ),
        ]

    def __str__(self) -> str:
        ag = f" ag. {self.agencia}" if self.agencia else ''
        return f"{self.instituicao} — cc {self.numero}{ag}"


class Extrato(models.Model):
    """Cabeçalho/período de um extrato importado."""

    conta = models.ForeignKey(
        ContaCorrente,
        on_delete=models.CASCADE,
        related_name='extratos',
    )
    data_inicio = models.DateField('Início')
    data_fim = models.DateField('Fim')
    arquivo_hash = models.CharField(max_length=40, blank=True, null=True)
    fonte_arquivo = models.CharField(max_length=255, blank=True, null=True)
    criado_em = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Extrato'
        verbose_name_plural = 'Extratos'
        ordering = ['-data_fim']

    def __str__(self) -> str:
        return f"Extrato {self.conta} ({self.data_inicio} a {self.data_fim})"


class Transacao(models.Model):
    """Transação de um extrato de conta corrente."""

    extrato = models.ForeignKey(
        Extrato,
        on_delete=models.CASCADE,
        related_name='transacoes',
    )
    data = models.DateField('Data')
    tipo = models.CharField('Tipo', max_length=100, blank=True, default='')
    descricao = models.CharField('Descrição', max_length=255)
    valor = models.DecimalField('Valor', max_digits=12, decimal_places=2)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transacoes_cc',
    )
    membros = models.ManyToManyField(
        Membro,
        blank=True,
        related_name='transacoes_cc',
    )

    oculta = models.BooleanField('Oculta', default=False)

    # Dedupe
    hash_linha = models.CharField(max_length=40)
    hash_ordem = models.PositiveSmallIntegerField(default=1)
    is_duplicado = models.BooleanField(default=False)

    fitid = models.CharField(max_length=100, blank=True, null=True)
    anotacao = models.CharField('Anotação', max_length=255, blank=True, null=True, help_text='Comentário ou identificação manual da transação.')

    class Meta:
        verbose_name = 'Transação'
        verbose_name_plural = 'Transações'
        constraints = [
            models.UniqueConstraint(
                fields=['extrato', 'hash_linha', 'hash_ordem'],
                name='uniq_lcto_cc_hash_ordem',
            ),
        ]
        indexes = [
            models.Index(fields=['extrato', 'data']),
        ]

    def __str__(self) -> str:
        return f"{self.data} — {self.descricao} (R$ {self.valor})"
