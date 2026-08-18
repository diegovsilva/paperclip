# Skill: modelagem-dados

## Descrição
Boas práticas de modelagem dimensional, Data Vault 2.0 e wide tables. Referências externas (monitoradas pelo Curador):
- dbt docs Learning Center (docs.getdbt.com/best-practices)
- Kimball Group classic guides
- Data Vault 2.0 specification (danlinstedt.com)

Usado pelo Arquiteto de Dados.

## Quando usar
Sempre que a demanda cai em categoria `[MODELAGEM]` (Head classifica).

## Três padrões, quando usar qual

| Cenário | Padrão | Quando |
|---|---|---|
| Relatórios / BI consolidados | **Star Schema (Kimball)** | 90% dos casos de dados analíticos. Fato + Dimensões. |
| Dados brutos históricos + auditoria + múltiplas fontes | **Data Vault 2.0** | Hub + Link + Satellite. Requer volume/casos de uso justificados. |
| Dashboard de baixa latência / app operacional | **Wide Table** | Todas colunas em 1 tabela, bem particionada. Evitar para casos genéricos. |

## Regras obrigatórias em qualquer padrão

### Star Schema
- 1 fato = 1 processo de negócio. Não misture processos.
- Toda dimensão tem `sk_*` surrogate key + NK (natural key) + atributos + metadados.
- Fato tem todas as FKs p/ dimensões + métricas aditivas/semi-aditivas.
- Dimensão data/hora SEMPRE separada (não use campo data como texto).
- SCD Tipo 1 / 2 sempre explicitado por dimensão.

### Data Vault 2.0
- Todo Hub: `hk_hub_*` (hash business key) + `business_key` + `load_date` + `record_source`.
- Todo Satellite: `hk_hub_*` + `load_date` + atributos + `hashdiff`.
- Todo Link: `hk_link_*` + `hk_*` dos hubs participantes + load_date.
- Nunca atualize Satellite — sempre INSERT + novo load_date.

### Wide Tables
- Particionamento por data (diário ou mensal).
- Campos de auditoria: `_created_at`, `_updated_at`, `_source`.
- Evite > 50 colunas a menos que o dashboard exija.

## Checklist OBRIGATÓRIO antes de finalizar o desenho
- [ ] Declarou qual padrão adotou e por quê (1 frase).
- [ ] Todas tabelas: PK (ou surrogate) + FKs com tabela alvo.
- [ ] Todas colunas: tipo, descrição, is_pii (booleano), nullable (booleano).
- [ ] Dicionário de dados completo (mesmo que resumido).
- [ ] Marcações SCD Tipo 1/2 por dimensão (se Star).
- [ ] Se PII presente: `REVISAO_NECESSARIA: governanca | <motivo específico>` SEMPRE, sem exceção.
- [ ] Declarou aderência ao `padrao-repositorio` ou justificou desvios (bloco Desvio do Padrão Detectado).
- [ ] Estratégia de carga (full, incremental, CDC, upsert) com chave de atualização.
- [ ] Granularidade explícita de fato (1 linha = o quê?).
- [ ] 2 queries de exemplo que um analista escreveria contra o modelo (SELECT JOIN...).

## Exemplo de output final
```
### Modelo: Star Schema — Vendas

Justificativa: demanda é BI de vendas com múltiplas dimensões de análise → Kimball.

#### Fato f_vendas
| Coluna | Tipo | Descrição | FK | PII? | Nul? |
|---|---|---|---|---|---|
| sk_venda | uuid | Surrogate | | | N |
| fk_data | int | Dimensão data → sk_data | d_data | | N |
| fk_cliente | uuid | | d_cliente | Sim | N |
| fk_produto | uuid | | d_produto | | N |
| fk_loja | uuid | | d_loja | | N |
| valor_total | decimal(18,2) | Soma item | | | N |
| qtd_itens | int | Quantidade | | | N |
| _source | text | Origem ingestão | | | N |
| _loaded_at | timestamptz | | | | N |
1 linha por item de nota fiscal.
Carga: incremental por updated_at (CDC).

#### Dimensão d_cliente (SCD Tipo 2)
...

#### Dicionário + 2 queries exemplo
...
```
