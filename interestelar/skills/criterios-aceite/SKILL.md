# Skill: criterios-aceite

## Descrição
Usado pelo PO para converter pedido vago do negócio em critérios de aceite SMART.

## Quando usar
Sempre que:
- O Head atribuir um ticket marcado `[ESCOPO_PO]`
- Um agente devolver com `REVISAO_NECESSARIA: po | item X ambíguo`

## Estrutura obrigatória (não mude a ordem)

```
## Escopo definido

### Contexto
<parágrafo curto — 2-4 frases — explicando o problema de negócio, quem pediu, impacto esperado.>

### Critérios de Aceite
1. <Critério 1, SMART, sem ambiguidade.>
2. <Critério 2, SMART...>
3. ...
<n — mínimo 5, máximo 12 critérios.>

### Fora de Escopo
- <Item 1 que NÃO será feito, para não dar retrabalho.>
- <Item 2 que NÃO será feito.>
- <Item 3 que NÃO será feito.>
<Mínimo 3 itens.>

ETAPA_CONCLUIDA
```

## Regras SMART (lembre sempre)
- **Específico:** use nomes de tabela, coluna, métrica. Não "dados de clientes". Sim "Tabela `mart_clientes` com 1 linha por CPF ativo".
- **Mensurável:** quantidades, SLA, taxas. Não "rápido". Sim "latência < 2 min".
- **Atingível:** não prometa o impossível.
- **Relevante:** ligado diretamente ao pedido do usuário.
- **Temporal:** se houver SLA/frequência, sempre explícito.

## Checklist de qualidade final
Antes de marcar ETAPA_CONCLUIDA, confira:
- [ ] Pelo menos 1 critério menciona tabela de saída ou local esperado.
- [ ] Pelo menos 1 critério menciona granularidade/frequência.
- [ ] Pelo menos 1 critério de qualidade (unique, non-null, validade).
- [ ] Se mencionar integração, qual sistema/pasta/fonte de dados.
- [ ] 3 itens de Fora de Escopo.

## Gatilhos para revisão LGPD
Se no escopo aparecer qualquer um destes, SEMPRE sinalize ao final:
- CPF, CNPJ de clientes/parceiros
- E-mail pessoal, telefone, celular
- Endereço completo / geolocalização
- Dados de saúde, religiosos, biométricos
- Menores de idade

Use:
```
REVISAO_NECESSARIA: governanca | Escopo inclui campos pessoais sensíveis (lista breve). Requisita analise LGPD antes de implementacao.
ETAPA_CONCLUIDA
```
