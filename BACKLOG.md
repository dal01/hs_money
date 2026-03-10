## 
Fazer um app por vez
Acho que tudo funciona melhor se buscar pelo Django, em vez de usar o Pandas
Talvez criar funcoes que faca as buscas no Django facilite 

## Core


## Conta corrente
pix de mim para mim ou da Andrea para mim, ignora

## Cartao de credito
Ler as faturas e lancar no BD
Poder ocultar transacao
Atribuir transacao a usuario

## Relatorios
Vou atribuir membros para todas transacoes, o filtro do pagamento de cartao de credito deve vir da view do relatorio
Colocar filtros para excluir categorias/subcategorias
Precisa achar solucao pra pagamentos que fazemos para os amigos. Ex: paguei Xique xique para todos e depois dividimos
Hoje só aparece a despesa completa, deveria descontar o pagamento dos amigos
Venda de acoes tenho que ocultar do relatorio, porque passa a impressao que foi uma renda extra

## Planejamento
Quero que seja possível calcular quanto vou ter nos próximos meses.

## Ativos
Lançar o quanto tenho de cada ativo para controlar o caixa

## Obs
Transferencias entre Dalton e Andrea devem ser ocultas, elas não são receitas nem despesas
  Isso vai dar diferença apenas quando analisar saldos individuais
Transacoes extornadas, devem ser ignoradas



venv/Scripts/activate
python manage.py runserver