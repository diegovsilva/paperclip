# Heartbeat Checklist — Arquiteto de Dados

1. **Carrega `padrao-repositorio` do contexto.** Lê o cache do repo da empresa ou o vault "Padrão do Repositório.md". Anota convenções (dbt? Airflow? Python? dbt Cloud? BigQuery? Postgres?).

2. **Relê critérios de aceite do PO.** Se algum item for tecnicamente inviável, sinalize `REVISAO_NECESSARIA: po | item X inviável por motivo Y` — não invente um critério novo sozinho.

3. **Produz o desenho. Mínimo de 5 seções:**

   a. **Visão Geral** — diagrama textual (Mermaid se quiser): fonte → staging → marts → output.
   b. **Dicionário de Dados** — tabela/staging tabela: coluna, tipo, descrição, is_pii, nullable, unique.
   c. **Estratégia de Carga** — frequência, chave de atualização, SCD Tipo 1/2, CDC vs full.
   d. **Qualidade** — checks básicos: unique, non-null, referencial, range.
   e. **Aderência ao Padrão** — confirma cada ponto do `padrao-repositorio` ou justifica desvio.

4. **Se tem PII** → adiciona `REVISAO_NECESSARIA: governanca | Desenho inclui X campos sensíveis (lista). Requisita aprovação LGPD antes de implementação.`

5. **Comenta no ticket.** Resposta completa com as 5 seções. Finaliza com `ETAPA_CONCLUIDA`.
