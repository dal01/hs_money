"""
Cria a tabela cartao_credito_transacao caso não exista.
Necessário porque o 0001_initial foi modificado in-place para incluir o model
Transacao, mas bancos criados com a versão anterior não têm essa tabela.
Usa CREATE TABLE/INDEX IF NOT EXISTS para ser segura em bancos novos também.
"""
from django.db import migrations

SQL_TRANSACAO = """
CREATE TABLE IF NOT EXISTS "cartao_credito_transacao" (
    "id" serial NOT NULL PRIMARY KEY,
    "data" date NOT NULL,
    "descricao" varchar(255) NOT NULL,
    "cidade" varchar(80) NULL,
    "pais" varchar(8) NULL,
    "secao" varchar(40) NULL,
    "oculta" bool NOT NULL,
    "oculta_manual" bool NOT NULL,
    "valor" decimal(12, 2) NOT NULL,
    "moeda" varchar(10) NULL,
    "valor_moeda" decimal(12, 2) NULL,
    "taxa_cambio" decimal(12, 6) NULL,
    "etiqueta_parcela" varchar(20) NULL,
    "parcela_num" integer NULL,
    "parcela_total" integer NULL,
    "observacoes" text NULL,
    "hash_linha" varchar(40) NOT NULL,
    "hash_ordem" smallint NOT NULL,
    "is_duplicado" bool NOT NULL,
    "fitid" varchar(100) NULL,
    "categoria_id" integer NULL REFERENCES "core_categoria" ("id") DEFERRABLE INITIALLY DEFERRED,
    "fatura_id" integer NOT NULL REFERENCES "cartao_credito_faturacartao" ("id") DEFERRABLE INITIALLY DEFERRED
)
"""

SQL_TRANSACAO_MEMBROS = """
CREATE TABLE IF NOT EXISTS "cartao_credito_transacao_membros" (
    "id" serial NOT NULL PRIMARY KEY,
    "transacao_id" integer NOT NULL REFERENCES "cartao_credito_transacao" ("id") DEFERRABLE INITIALLY DEFERRED,
    "membro_id" integer NOT NULL REFERENCES "core_membro" ("id") DEFERRABLE INITIALLY DEFERRED
)
"""

SQL_IDX_M2M = """
CREATE UNIQUE INDEX IF NOT EXISTS "cartao_credito_transacao_membros_transacao_id_membro_id_uniq"
ON "cartao_credito_transacao_membros" ("transacao_id", "membro_id")
"""

SQL_IDX_FATURA_DATA = """
CREATE INDEX IF NOT EXISTS "cartao_cred_fatura__50765a_idx"
ON "cartao_credito_transacao" ("fatura_id", "data")
"""

SQL_UNIQ_HASH = """
CREATE UNIQUE INDEX IF NOT EXISTS "uniq_lcto_por_fatura_hash_ordem"
ON "cartao_credito_transacao" ("fatura_id", "hash_linha", "hash_ordem")
"""

class Migration(migrations.Migration):
    dependencies = [
        ("cartao_credito", "0002_invert_transacao_valor"),
        ("core", "0001_initial"),
    ]
    operations = [
        migrations.RunSQL(SQL_TRANSACAO, migrations.RunSQL.noop),
        migrations.RunSQL(SQL_TRANSACAO_MEMBROS, migrations.RunSQL.noop),
        migrations.RunSQL(SQL_IDX_M2M, migrations.RunSQL.noop),
        migrations.RunSQL(SQL_IDX_FATURA_DATA, migrations.RunSQL.noop),
        migrations.RunSQL(SQL_UNIQ_HASH, migrations.RunSQL.noop),
    ]