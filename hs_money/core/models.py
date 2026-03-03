# core/models.py
from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError

# =========================================
# Categoria (2 níveis: macro e sub)
# =========================================
class Categoria(models.Model):
    NIVEL_CHOICES = [(1, "Macro"), (2, "Sub")]

    nome = models.CharField(max_length=100)
    nivel = models.PositiveSmallIntegerField(choices=NIVEL_CHOICES, default=1)
    categoria_pai = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subcategorias",
    )

    class Meta:
        ordering = ["nivel", "nome"]
        constraints = [
            # nome único por escopo do pai (macros não têm pai)
            models.UniqueConstraint(
                fields=["categoria_pai", "nome"], name="uix_categoria_pai_nome"
            ),
            # nível 1 não pode ter pai; nível 2 deve ter pai
            models.CheckConstraint(
                check=(
                    models.Q(nivel=1, categoria_pai__isnull=True) |
                    models.Q(nivel=2, categoria_pai__isnull=False)
                ),
                name="chk_categoria_nivel_vs_pai",
            ),
        ]

    def clean(self):
        # evita loop pai->filho
        if self.categoria_pai:
            p = self.categoria_pai
            while p:
                if p == self:
                    raise ValidationError("Categoria-pai não pode formar ciclo.")
                p = p.categoria_pai

    def __str__(self):
        if self.categoria_pai:
            return f"{self.categoria_pai.nome} > {self.nome}"
        return self.nome

    @property
    def macro(self) -> "Categoria":
        return self.categoria_pai or self

    @property
    def is_macro(self) -> bool:
        return self.nivel == 1


# =========================================
# Estabelecimento
# =========================================
class Estabelecimento(models.Model):
    nome_fantasia = models.CharField(max_length=200, unique=True)
    # Categoria padrão (opcional) — usada se nenhuma regra bater
    categoria_padrao = models.ForeignKey(
        Categoria, null=True, blank=True, on_delete=models.SET_NULL, related_name="estabelecimentos"
    )

    class Meta:
        ordering = ["nome_fantasia"]

    def __str__(self):
        return self.nome_fantasia


# =========================================
# AliasEstabelecimento
# =========================================
class AliasEstabelecimento(models.Model):
    nome_alias = models.CharField(max_length=200)
    nome_base = models.CharField(
        max_length=200,
        db_index=True,
        blank=True,
        default="",
        help_text="Forma normalizada do alias para agrupar variações (preenchido automaticamente).",
    )
    estabelecimento = models.ForeignKey(
        Estabelecimento,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    mestre = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="variantes",
        help_text="Alias principal ao qual esta variante pertence (opcional).",
    )

    class Meta:
        ordering = ["nome_base", "nome_alias"]
        constraints = [
            models.UniqueConstraint(
                fields=["estabelecimento", "nome_alias"],
                name="uix_estabelecimento_nome_alias",
            )
        ]

    def save(self, *args, **kwargs):
        try:
            from core.utils.normaliza import normalizar
            normalizado = normalizar(self.nome_alias or "")
        except Exception:
            normalizado = (self.nome_alias or "").strip().upper()
        if self.nome_base != normalizado:
            self.nome_base = normalizado
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome_alias


# =========================================
# Regras de Alias -> Estabelecimento (já existia)
# =========================================
class RegraAlias(models.Model):
    padrao_regex = models.CharField(
        max_length=255,
        help_text=r"Regex aplicada sobre o texto normalizado (ex.: r'\bAMAZON\b|\bAMAZON MARKET\b')",
    )
    estabelecimento = models.ForeignKey(
        Estabelecimento,
        on_delete=models.CASCADE,
        related_name="regras_alias",
    )
    prioridade = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1)],
        help_text="Menor número = regra aplicada primeiro.",
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["prioridade", "id"]

    def __str__(self):
        estado = "ativo" if self.ativo else "inativo"
        return f"/{self.padrao_regex}/ -> {self.estabelecimento} ({estado}, p={self.prioridade})"


# =========================================
# Regras de Categoria (opcional, refinam após achar o estabelecimento)
# - Podem usar regex no nome_base OU em descricao/historico da transacao.
# - Se bater, define/ajusta a Categoria da transacao.
# =========================================
class RegraCategoria(models.Model):
    descricao = models.CharField(max_length=140, blank=True, default="")
    padrao_regex = models.CharField(
        max_length=255,
        help_text=r"Regex aplicada sobre o texto normalizado (alias_base/descrição).",
    )
    categoria = models.ForeignKey(
        Categoria, on_delete=models.CASCADE, related_name="regras_categoria"
    )
    prioridade = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(1)],
        help_text="Menor número = regra aplicada primeiro.",
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["prioridade", "id"]

    def __str__(self):
        estado = "ativo" if self.ativo else "inativo"
        return f"/{self.padrao_regex}/ -> {self.categoria} ({estado}, p={self.prioridade})"


# =========================================
# InstituicaoFinanceira / Membro (como você já tinha)
# =========================================
class InstituicaoFinanceira(models.Model):
    TIPO_CHOICES = [
        ("banco", "Banco"),
        ("corretora", "Corretora"),
        ("fintech", "Fintech"),
        ("cooperativa", "Cooperativa"),
        ("outro", "Outro"),
    ]
    nome = models.CharField(max_length=100)
    codigo = models.CharField(max_length=20, blank=True, null=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default="banco")

    def __str__(self):
        return self.nome


class Membro(models.Model):
    nome = models.CharField("Nome", max_length=100)
    adulto = models.BooleanField(default=True)
    
    class Meta:
        ordering = ["-adulto", "nome"]

    def __str__(self):
        return self.nome
