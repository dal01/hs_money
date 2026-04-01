## 

## Core
Colocar login

## Conta corrente

## Cartao de credito
Fazer controle de pagamentos parcelados
Criar uma forma visual de ver os pagamentos parcelados futuros
    fazer gráfico de parcelados mes a mes para ver se o volume esta aumentando ou diminuindo


## Investimentos
  
## Relatorios
Precisa achar solucao pra pagamentos que fazemos para os amigos. Ex: paguei Xique xique para todos e depois dividimos
Hoje só aparece a despesa completa, deveria descontar o pagamento dos amigos
Venda de acoes tenho que ocultar do relatorio, porque passa a impressao que foi uma renda extra

## Planejamento
  Nas tabelas deve mostrar o total sem os investimentos e com os investimentos, hoje está mostrando sempre com
  Está apresentando valores confusos porque o créditos - débitos não dá o total (porque está somando os rendimentos)
  Colocar na tabela: 
    mes, creditos, debitos, parcial, investimentos, saldo do mes
  Fazer uma nova template com o que foi projetado e o que foi realizado. 
    AInda não sei como fazer isso porque tudo é calculado na hora
    uma opção é usar o mês seguinte como parametro

  ## Lançamentos recorrentes (conta corrente)
  Contas variáveis (água, luz):pega média dos últimos 12 meses
  precisa de um botao para recalcular, mas eu mudei o nome, acho que vai precisar guardar o nome original no BD


## Obs
Transferencias entre Dalton e Andrea devem ser ocultas, elas não são receitas nem despesas
  Isso vai dar diferença apenas quando analisar saldos individuais
Transacoes estornadas, devem ser ignoradas
  Fazer uma ferramenta para detectar lançamentos com valores opostos Ex: +100,00 e -100,00. QUando detectados esses lançamentos posso ignorar/ocultar



venv/Scripts/activate
python manage.py runserver