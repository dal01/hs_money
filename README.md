# Importadores — `cartao_credito`

Este documento descreve o comportamento dos importadores presentes em `cartao_credito`, suas opções principais, regras de deduplicação e recomendações de uso.

**Formato e comandos principais**

- `importar_cartoes` — importa arquivos OFX (usa `ofxparse`). Dedupe por `fitid` (FITID do OFX), atualiza lançamentos existentes com `update_or_create`.
- `importar_pdf_cartao_bb` — importa faturas em PDF do Banco do Brasil (usa `pdfplumber` e parsers internos). Não usa FITID; parseia texto do PDF e insere `FaturaCartao` / `Lancamento`.

**Comportamento geral ao importar**

- Fatura identificada por: `cartao` + `competencia` (mês/ano).
- Para PDFs: o importador calcula um `arquivo_hash` (sha1) a partir do PDF. Se a `FaturaCartao` existente tiver o mesmo `arquivo_hash` e você não passar `--replace`, a fatura é ignorada.
- Para cada lançamento do PDF o importador verifica existência por combinação: `fatura` + `data` + `descricao[:255]` + `valor`. Se existir, o lançamento é ignorado; caso contrário, é criado.
- Para OFX: o identificador principal é o `fitid` (campo `tx.id`); se presente, o código faz `update_or_create` por `fitid` para evitar duplicatas.

**Duplicatas / importações repetidas**

- Importar a mesma fatura duas vezes (mesma hash): a segunda importação é ignorada (a não ser que use `--replace` ou `--force`).
- Importar um PDF provisório e depois o PDF final do mesmo mês:
  - Se o `arquivo_hash` for diferente (comum), a fatura é atualizada e apenas lançamentos ausentes (com base em `data+descricao+valor`) são adicionados.
  - Se a descrição mudar por causa de OCR/parse, o importador pode criar lançamentos duplicados.
- Lembre-se: o parser gera `hash_linha`, mas o importador PDF atual não usa `hash_linha` para dedupe — apenas `data+descricao+valor`.

**Flags e opções importantes**

- `--dry-run` : simula a importação sem gravar no banco (recomendado para checagem).
- `--replace` : apaga os lançamentos da fatura alvo antes de reimportar (substitui lançamentos na fatura existente).
- `--force` : apaga a fatura alvo antes de criar novamente (recria fatura + lançamentos).
- `--force-all` : apaga TODAS as faturas e lançamentos antes (perigoso).
- `--titular`, `--instituicao`, `--fonte` : parâmetros para forçar titular/instituição/fonte do arquivo.
- `--debug-unmatched`, `--debug-max` : ajudam a diagnosticar blocos do PDF que o parser não reconheceu.
- OFX specific: `--usuario/-u` obrigatório (subpastas por usuário), `--pasta-base/-p`, `--reset`, `--limite`.

**Dependências**

- `pdfplumber` (PDF import). Instalar no venv: `python -m pip install pdfplumber`.
- `ofxparse` (OFX import). Instalar se usar `importar_cartoes`.

**Exemplos de uso**

1) Dry-run (PDF BB) — não grava no DB:

```
python manage.py importar_pdf_cartao_bb "F:\\sistemas\\dev\\hs_money\\data\\cartao_credito\\dalton" --dry-run
```

2) Import real (substituir lançamentos da fatura alvo):

```
python manage.py importar_pdf_cartao_bb path\\to\\pdfs --replace
```

3) Import OFX (usuários em subpastas):

```
python manage.py importar_cartoes -u dalton -u andrea -p cartao_credito/data --dry-run
```

**Recomendações / boas práticas**

- Sempre rode `--dry-run` primeiro para validar parsing e contagens.
- Faça backup antes de importações reais:

```
python manage.py dumpdata > backup.json
```

- Para garantir substituição completa da fatura provisória pela final, use `--replace` ou `--force` (dependendo do nível de substituição desejado).
- Se tiver muitos PDFs escaneados com OCR ruim, considere pré-processar (OCR) ou melhorar regras de `parsers.bb`.

**Onde os parsers vivem**

- Parsers de PDF Banco do Brasil: `hs_money/cartao_credito/parsers/bb/` (módulos `dados_fatura` e `lancamentos`).
- OFX importer usa `cartao_credito.services.regras_membro` para aplicar regras de atribuição de membro após inserir/atualizar lançamentos.

Se quiser, posso:

- adicionar uma flag `--dedupe-by` para escolher método de dedupe;
- alterar o importador para preferir `hash_linha` quando disponível;
- ou rodar um `--dry-run` nos PDFs da sua pasta e enviar o resumo.

***Fim***
