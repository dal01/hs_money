from __future__ import annotations

import re
from uuid import uuid4
from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError

from ..core.models import Membro, InstituicaoFinanceira, Categoria


class Cartao(models.Model):
    """Cartão físico/lógico. Um membro titular, vários ciclos de fatura."""

    instituicao = models.ForeignKey(
        InstituicaoFinanceira,
        on_delete=models.CASCADE,
        related_name="cartoes",
    )
    bandeira = models.CharField(max_length=60, blank=True, null=True)
    cartao_final = models.CharField(max_length=8)  # ex.: "6462"

    # titular real do cartão no sistema
    membro = models.ForeignKey(
        Membro,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cartoes",
    )

    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # evita duplicar o mesmo cartão na mesma instituição/bandeira
            models.UniqueConstraint(
                fields=["instituicao", "bandeira", "cartao_final"],
                name="uniq_cartao_instituicao_bandeira_final",
            ),
        ]
        indexes = [
            models.Index(fields=["cartao_final"]),
            models.Index(fields=["membro"]),
        ]

    def __str__(self) -> str:
        inst = self.instituicao.nome if self.instituicao_id else "—"
        bd = self.bandeira or "—"
        mb = f"{self.membro}" if self.membro_id else "—"
        return f"{inst} • {bd} • ****{self.cartao_final} • {mb}"


class FaturaCartao(models.Model):
    """Metadados/cabeçalho de uma fatura mensal por cartão."""
    cartao = models.ForeignKey(
        Cartao,
        on_delete=models.CASCADE,
        related_name="faturas",
        null=False,
        blank=False,
    )

    fechado_em = models.DateField()
    vencimento_em = models.DateField()
    competencia = models.DateField()  # sempre 1º dia do mês

    total = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)

    arquivo_hash = models.CharField(max_length=40, blank=True, null=True)   # sha1 do PDF
    fonte_arquivo = models.CharField(max_length=255, blank=True, null=True) # caminho nome do PDF (opcional)
    import_batch = models.UUIDField(default=uuid4, editable=False)

    criado_em = models.DateTimeField(default=timezone.now, editable=False)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # uma fatura por mês por cartão
            models.UniqueConstraint(
                fields=["cartao", "competencia"],
                name="uniq_fatura_por_cartao_competencia",
            ),
        ]
        indexes = [
            models.Index(fields=["competencia", "cartao"]),
            models.Index(fields=["fechado_em"]),
        ]

    def __str__(self) -> str:
        return f"Fatura {self.competencia:%Y-%m} • {self.cartao}"


class Transacao(models.Model):
    """Linha de transação pertencente a uma fatura."""
    fatura = models.ForeignKey(
        FaturaCartao,
        on_delete=models.CASCADE,
        related_name="transacoes",
    )

    # Dados da linha
    data = models.DateField()
    descricao = models.CharField(max_length=255)
    cidade = models.CharField(max_length=80, blank=True, null=True)
    pais = models.CharField(max_length=8, blank=True, null=True)           # "BR", "US", etc.
    secao = models.CharField(max_length=40, blank=True, null=True)         # "ENCARGOS", etc.
    oculta = models.BooleanField(default=False, db_index=True)
    oculta_manual = models.BooleanField(default=False, db_index=True)
    categoria = models.ForeignKey(Categoria, null=True, blank=True, on_delete=models.SET_NULL, related_name="transacoes")

    # Valor final em BRL
    valor = models.DecimalField(max_digits=12, decimal_places=2)

    # Moeda estrangeira (se houver)
    moeda = models.CharField(max_length=10, blank=True, null=True)         # "USD", ...
    valor_moeda = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    taxa_cambio = models.DecimalField(max_digits=12, decimal_places=6, blank=True, null=True)

    # Parcelas detectadas
    etiqueta_parcela = models.CharField(max_length=20, blank=True, null=True)   # "PARC 05/12"
    parcela_num = models.PositiveIntegerField(blank=True, null=True)
    parcela_total = models.PositiveIntegerField(blank=True, null=True)

    # Observações livres (ex.: itens da Amazon)
    observacoes = models.TextField(blank=True, null=True)

    # Dedupe/Idempotência (no âmbito da fatura)
    hash_linha = models.CharField(max_length=40)                       # sha1(data|valor_cent|desc|cidade|pais|parcela)
    hash_ordem = models.PositiveSmallIntegerField(default=1)
    is_duplicado = models.BooleanField(default=False)

    # Compat com OFX (opcional)
    fitid = models.CharField(max_length=100, blank=True, null=True)

    # Atribuição de membros (opcional por linha; mantém flexibilidade)
    membros = models.ManyToManyField(Membro, blank=True, related_name="transacoes_cartao")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["fatura", "hash_linha", "hash_ordem"],
                name="uniq_lcto_por_fatura_hash_ordem",
            ),
        ]
        indexes = [
            models.Index(fields=["fatura", "data"]),
        ]

    def __str__(self) -> str:
        return f"{self.data} - {self.descricao} (R$ {self.valor})"


class RegraMembroCartao(models.Model):
    TIPO_PADRAO_CHOICES = [
        ('exato', 'Texto exato'),
        ('contem', 'Contém o texto'),
        ('inicia_com', 'Inicia com'),
        ('termina_com', 'Termina com'),
        ('regex', 'Expressão regular'),
    ]

    TIPO_VALOR_CHOICES = [
        ('nenhum', 'Sem condição de valor'),
        ('igual', 'Igual a'),
        ('maior', 'Maior que'),
        ('menor', 'Menor que'),
    ]

    # Identificação
    nome = models.CharField(max_length=120)

    # Padrão (aplicado em Transacao.descricao)
    tipo_padrao = models.CharField(max_length=20, choices=TIPO_PADRAO_CHOICES, default='contem')
    padrao = models.CharField(max_length=200)

    # Condição por valor absoluto (em BRL, campo Transacao.valor)
    tipo_valor = models.CharField(max_length=10, choices=TIPO_VALOR_CHOICES, default='nenhum')
    valor = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)

    # Alvo (para quem atribuir)
    membros = models.ManyToManyField(Membro, blank=True, related_name="regras_membro_cartao")

    # Controle
    ativo = models.BooleanField(default=True)
    prioridade = models.PositiveIntegerField(default=100, help_text="Quanto menor, mais cedo esta regra é avaliada.")

    # Auditoria
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regra de Membro (Cartão)"
        verbose_name_plural = "Regras de Membro (Cartão)"
        ordering = ("prioridade", "nome")
        indexes = [
            models.Index(fields=["ativo", "prioridade"]),
        ]

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_padrao_display()})"

    # --- lógica principal da regra ---
    def aplica_para(
        self,
        descricao: str,
        valor: Decimal,
        *,
        cartao_membro_id: int | None = None,
        **_
    ) -> bool:
        """
        Verifica se a regra casa com (descricao, valor).
        Param extra `cartao_membro_id` vem do titular do cartão; use se quiser
        que a regra dependa do titular. Mantido opcional para compat.
        """
        if not self.ativo:
            return False

        # ---- match por descrição ----
        desc = (descricao or "")
        alvo_txt = (self.padrao or "")
        tipo = self.tipo_padrao

        if tipo == "exato":
            desc_ok = desc.lower() == alvo_txt.lower()
        elif tipo == "contem":
            desc_ok = alvo_txt.lower() in desc.lower()
        elif tipo == "inicia_com":
            desc_ok = desc.lower().startswith(alvo_txt.lower())
        elif tipo == "termina_com":
            desc_ok = desc.lower().endswith(alvo_txt.lower())
        elif tipo == "regex":
            try:
                desc_ok = re.search(self.padrao, desc, re.I) is not None
            except re.error:
                desc_ok = False
        else:
            desc_ok = False

        if not desc_ok:
            return False

        # ---- match por valor (ignorando sinal) ----
        if self.tipo_valor == "nenhum":
            return True
        if self.valor is None:
            return False

        # Comparação robusta (duas casas, tolerância 1 centavo)
        v = abs(Decimal(valor or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        alvo = abs(Decimal(self.valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tol = Decimal("0.01")

        if self.tipo_valor == "igual":
            return abs(v - alvo) <= tol
        elif self.tipo_valor == "maior":
            return v > (alvo - tol)
        elif self.tipo_valor == "menor":
            return v < (alvo + tol)
        return False

    # --- coerção/validação para UX melhor e consistência ---
    def clean(self):
        # Se há valor mas tipo_valor ficou "nenhum" -> ajusta para "igual"
        if self.valor is not None and self.tipo_valor == "nenhum":
            self.tipo_valor = "igual"

        # Se tipo_valor exige valor e ele não foi informado -> erro
        if self.tipo_valor != "nenhum" and self.valor is None:
            raise ValidationError({"valor": "Informe um valor quando há condição de valor."})

        # Se tipo_valor é 'nenhum', zera valor para manter consistência
        if self.tipo_valor == "nenhum":
            self.valor = None

    def save(self, *args, **kwargs):
        # Garante coerção também se salvar sem passar por forms (ex.: script)
        self.full_clean()
        return super().save(*args, **kwargs)
