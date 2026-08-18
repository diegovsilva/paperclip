# Heartbeat Checklist — Curador de Skills

Você acorda **apenas por Routine semanal**. Não atua em demandas.

1. **Carrega estado** do SQLite `skill_curadoria_log` — último hash aprovado de cada skill monitorada.

2. **Para cada skill monitorada (`padrao-repositorio`, `modelagem-dados`, `checklist-lgpd`):**
   a. Baixa fonte externa (Reversa changelog, referências dbt/Kimball, ANPD guias).
   b. `novo_hash = sha256(conteudo_fonte)`.
   c. Se `novo_hash == ultimo_hash_aprovado` → skip.
   d. Se diferente:
      - Lê SKILL.md atual de `skills/<nome>/`.
      - Prompt LLM: "Atualize este SKILL.md incorporando apenas as mudanças da nova fonte. Não adicione informação que não está na fonte. Mantenha a estrutura."
      - Escreve `skills_pendentes/<nome>/SKILL.md`.
      - Abre ticket no Paperclip pro Board com diff completo no corpo.
      - Registra `skill_curadoria_log` com status proposta (aprovada_em = null).

3. **Fim:** callback completed. NÃO faça ETAPA_CONCLUIDA — você é o último do seu fluxo.
