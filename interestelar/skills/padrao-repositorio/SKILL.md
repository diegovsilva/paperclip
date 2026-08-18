# Skill: padrão-repositório

## Descrição
Detecta e documenta o padrão de desenvolvimento do repositório da empresa antes de qualquer proposta de desenho ou implementação. Usado por Arquiteto, Engenheiro e Governança.

## Fonte externa (monitorada pelo Curador)
- Fonte primária: **Reversa** (github.com/sandeco/reversa) — framework Node que analisa repo e produz spec real de arquitetura. Requer Claude Code CLI autenticado (não gratuito).
- Fallback gratuito 1: GitHub / GitLab Tree API + contents de arquivos chave + Groq sumarizando.
- Fallback gratuito 2: ls estrutural local + Groq.

## Quando usar
- **Head:** ao receber um ticket novo de demanda — verifica se já tem padrão cacheado para a empresa; se NÃO, aciona tools_repo.py para gerar. Anexa o MD como contexto na descrição do ticket.
- **Arquiteto:** ANTES de qualquer desenho de pipeline/modelagem.
- **Engenheiro:** ANTES de qualquer código.
- **Governança:** ao avaliar segurança, criptografia e logs de acesso.

## O que contém o padrão (seção obrigatória)
Um `Padrão do Repositório.md` válido SEMPRE tem estas 10 seções:

1. **Stack de dados** — DW (Snowflake, BigQuery, Postgres?), transformação (dbt, Spark, SQL puro?), orquestração (Airflow, Dagster, n8n?), ingestão (Airbyte, Fivetran, script Python?).
2. **Convenções de nomenclatura** — tabelas (stg_*, dwd_*, dws_*, mart_*), colunas (snake_case, camelCase?), branches (feat/, fix/), arquivos .sql.
3. **Estrutura de diretórios** — dbt models/, pipelines/, macros/, seeds/, snapshots/; pastas de DAGs etc.
4. **Controle de qualidade** — dbt tests, Great Expectations, Soda, check unique/non-null por padrão?
5. **Versionamento** — GitFlow vs Trunk-based, merge squash, conventional commits, CI.
6. **Deploy / Ambientes** — dev/staging/prod, dbt targets, Airflow environments, CICD pipeline.
7. **Segurança & segredos** — secrets manager, criptografia em repouso e trânsito, mascaramento de PII.
8. **Observabilidade** — logs (estruturados?), alertas, monitoramento (Prometheus, Grafana, dbt artefatos?).
9. **Padrões de modelagem** — Star schema, Data Vault, wide-table, SCD Tipo 1/2 padrão.
10. **Exemplos concretos** — links para 2-3 modelos / DAGs de referência no repo.

## Regra de desvio do padrão
Se você (Arquiteto / Engenheiro) propuser algo que NÃO siga o padrão detectado, OBRIGATÓRIAMENTE no mesmo documento escreva bloco:

```
### Desvio do Padrão Detectado
- Item: <o que desvia>
- Motivo: <justificativa de 2 linhas, no máximo 3>
- Risco: <baixo/médio/alto> + 1 frase
```

Sem este bloco, o Head vai devolver com REVISAO_NECESSARIA.

## Cache e TTL
- Padrão é cacheado em SQLite (`tools_memoria.py`) com TTL padrão de **7 dias** (configurável em `repo_pattern_ttl_days`).
- Se houver mudança grande no repo (ex: migração de dbt 1.7 → 1.8), o Curador ou Arquiteto deve invalidar cache manualmente.
