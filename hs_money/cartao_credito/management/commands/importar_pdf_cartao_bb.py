# cartao_credito/management/commands/importar_pdf_bb.py
from __future__ import annotations

import pathlib
from uuid import uuid4
from decimal import Decimal
from typing import Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings

import pdfplumber

from hs_money.core.models import InstituicaoFinanceira, Membro
from hs_money.cartao_credito.models import Cartao, FaturaCartao, Transacao
from hs_money.cartao_credito.parsers.bb.dados_fatura import parse_dados_fatura
from hs_money.cartao_credito.parsers.bb.lancamentos import parse_lancamentos


# ------------------ utils ------------------
def extrair_texto(pdf_path: str) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def style_header(stdout, title: str) -> str:
    try:
        return stdout.style.MIGRATE_HEADING(title)
    except Exception:
        return f"===== {title} ====="


def iter_pdfs(path: pathlib.Path) -> Iterable[pathlib.Path]:
    if path.is_file():
        yield path
    else:
        yield from sorted(path.rglob("*.pdf"))


# ------------------ command ------------------
class Command(BaseCommand):
    help = "Importa faturas do Banco do Brasil (PDF). Lê um arquivo único ou uma pasta (recursiva)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Caminho do PDF ou da pasta contendo PDFs")
        parser.add_argument("--dry-run", action="store_true", help="Não grava no banco; apenas exibe o que seria importado")
        parser.add_argument("--debug-unmatched", action="store_true", help="Mostra blocos não reconhecidos")
        parser.add_argument("--debug-max", type=int, default=40)
        parser.add_argument("--replace", action="store_true", help="Apaga lançamentos e atualiza fatura existente")
        parser.add_argument("--titular", type=str, default="", help="Força o titular (Membro) do cartão")
        parser.add_argument("--instituicao", type=str, default="Banco do Brasil", help="Instituição financeira")
        parser.add_argument("--fonte", type=str, default="", help="Fonte_arquivo na fatura (por padrão, caminho do PDF)")
        parser.add_argument("--force", action="store_true", help="Apaga fatura existente antes de importar")
        parser.add_argument("--force-all", action="store_true", help="(PERIGOSO) Apaga TODAS as faturas e lançamentos antes")

    def handle(self, *args, **opts):
        base_path = pathlib.Path(opts["path"])
        dry = opts["dry_run"]
        dbg = opts["debug_unmatched"]
        dbg_max = opts["debug_max"]
        force_replace = opts["replace"]
        titular_nome = (opts.get("titular") or "").strip()
        instituicao_nome = (opts.get("instituicao") or "Banco do Brasil").strip()
        fonte_force = (opts.get("fonte") or "").strip()
        force = opts["force"]
        force_all = opts["force_all"]

        if not base_path.exists():
            base2 = pathlib.Path(settings.DADOS_DIR) / str(base_path)
            if base2.exists():
                base_path = base2
        if not base_path.exists():
            raise CommandError(f"Caminho inválido: {base_path} (cwd={pathlib.Path.cwd()})")

        pdfs = list(iter_pdfs(base_path))
        if not pdfs:
            self.stdout.write(self.style.WARNING(f"Nenhum PDF encontrado em {base_path}"))
            return
        if base_path.is_dir():
            self.stdout.write(self.style.NOTICE(f"Encontrados {len(pdfs)} PDFs em {base_path}"))

        # --force-all: limpa tudo
        if force_all:
            self.stdout.write(self.style.WARNING("Apagando TODAS as faturas e lançamentos..."))
            Transacao.objects.all().delete()
            FaturaCartao.objects.all().delete()
            Cartao.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Base limpa para reimportação."))

        ok = erros = ignorados = 0

        for pdf in pdfs:
            self.stdout.write(self.style.NOTICE(f"Processando {pdf}"))
            try:
                texto = extrair_texto(str(pdf))
                if not texto or len(texto.strip()) < 30:
                    self.stdout.write(self.style.WARNING(f"[{pdf}] Pouco texto extraído (talvez OCR ausente)."))
                    continue

                # Etapa 1: dados gerais
                dados = parse_dados_fatura(texto, str(pdf))
                fonte_arquivo = fonte_force or str(pdf)

                # resolve instituição
                instituicao, _ = InstituicaoFinanceira.objects.get_or_create(nome=instituicao_nome)

                # resolve titular (membro)
                membro = None
                if titular_nome:
                    membro = Membro.objects.filter(nome__iexact=titular_nome).first()

                # resolve cartão
                cartao, _ = Cartao.objects.get_or_create(
                    instituicao=instituicao,
                    bandeira=(dados.bandeira or ""),
                    cartao_final=dados.cartao_final,
                    defaults={"membro": membro, "ativo": True},
                )

                # Etapa 2: lançamentos
                linhas = parse_lancamentos(texto, dados, debug_unmatched=dbg, debug_max=dbg_max)

                soma = sum((l.valor for l in linhas), Decimal("0"))
                total_str = f"{dados.total:.2f}" if dados.total is not None else "—"
                self.stdout.write(
                    f"[{pdf}] {len(linhas)} lançamentos | Soma capturada R$ {soma:.2f} | Total PDF: {total_str}"
                )
                if dados.total is not None and abs(soma - dados.total) > Decimal("0.05"):
                    self.stdout.write(self.style.WARNING(
                        f"[AVISO] Divergência: soma R$ {soma:.2f} ≠ total PDF R$ {dados.total:.2f}"
                    ))

                if dry:
                    ok += 1
                    continue

                # --force: remove previamente fatura alvo
                if force:
                    FaturaCartao.objects.filter(cartao=cartao, competencia=dados.competencia).delete()

                with transaction.atomic():
                    fatura, created = FaturaCartao.objects.get_or_create(
                        cartao=cartao,
                        competencia=dados.competencia,
                        defaults=dict(
                            fechado_em=dados.fechado_em,
                            vencimento_em=dados.vencimento_em,
                            total=dados.total,
                            arquivo_hash=dados.arquivo_hash,
                            fonte_arquivo=fonte_arquivo,
                            import_batch=uuid4(),
                        ),
                    )

                    if not created and not force:
                        if fatura.arquivo_hash and fatura.arquivo_hash == dados.arquivo_hash and not force_replace:
                            ignorados += 1
                            self.stdout.write(self.style.SUCCESS(f"[{pdf}] Ignorado: fatura já importada (hash igual)."))
                            continue

                        if force_replace:
                            fatura.lancamentos.all().delete()
                            self.stdout.write(self.style.WARNING(f"[{pdf}] Lançamentos antigos removidos."))

                        fatura.fechado_em = dados.fechado_em
                        fatura.vencimento_em = dados.vencimento_em
                        fatura.total = dados.total
                        fatura.arquivo_hash = dados.arquivo_hash
                        fatura.fonte_arquivo = fonte_arquivo
                        fatura.save()

                    for l in linhas:
                        existe = Transacao.objects.filter(
                            fatura=fatura,
                            data=l.data,
                            descricao=l.descricao[:255],
                            valor=l.valor
                        ).exists()

                        print(f"Fatura: {fatura.competencia} | Data: {l.data} | Descrição: {l.descricao[:255]} | Valor: {l.valor}")

                        if existe:
                            self.stdout.write(self.style.WARNING(f"Lançamento já existe, ignorando: {l.descricao}."))
                        else:
                            Transacao.objects.create(
                                fatura=fatura,
                                data=l.data,
                                descricao=l.descricao[:255],
                                cidade=l.cidade or "",
                                pais=l.pais or "",
                                secao=l.secao,
                                valor=l.valor,
                                moeda=None,
                                valor_moeda=None,
                                taxa_cambio=None,
                                parcela_num=l.parcela_num,
                                parcela_total=l.parcela_total,
                                observacoes=None,
                                hash_linha=l.hash_linha,
                                hash_ordem=l.hash_ordem,
                                is_duplicado=l.is_duplicado,
                                fitid=None,
                            )

                ok += 1
                self.stdout.write(self.style.SUCCESS(f"[{pdf}] Importação concluída ({len(linhas)} lançamentos)."))

            except Exception as e:
                erros += 1
                self.stderr.write(self.style.ERROR(f"[{pdf}] ERRO: {e}"))

        # Resumo
        self.stdout.write("")
        self.stdout.write(style_header(self.stdout, "Resumo"))
        self.stdout.write(f"  PDFs processados : {len(pdfs)}")
        self.stdout.write(f"  Importados       : {ok}")
        self.stdout.write(f"  Ignorados        : {ignorados}")
        self.stdout.write(f"  Com erro         : {erros}")
