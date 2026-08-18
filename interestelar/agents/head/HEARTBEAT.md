# Heartbeat Checklist — Head de Dados

Ao receber um ticket atribuído, execute SEMPRE nesta ordem:

1. **Abra o ticket.** Leia título, descrição, anexos e TODOS os comentários anteriores. Procure:
   - Prefixo `#PLANO:` no primeiro comentário (plano de execução)
   - Marcadores `#REVISAO_ATUAL: N/3`
   - Sinalizador `[COMPLETO_ULTIMA_ETAPA]` vindo do agente anterior
   - Qualquer `REVISAO_NECESSARIA: agente | motivo` não resolvida

2. **Decida a situação.**
   - Se é a primeira vez no ticket (sem #PLANO): classifique a demanda → gere #PLANO.
   - Se é retorno de agente com etapa concluída: veja próximo agente no plano, reatribua.
   - Se é retorno de agente com REVISAO_NECESSARIA direcionada a OUTRO agente: respeite (verifique harness de revisão primeiro).
   - Se é retorno do ÚLTIMO agente do plano: feche a demanda.

3. **Classificação de demanda.** Marque quais categorias se aplicam:
   - `[ESCOPO_PO]` — critérios de aceite vagos ou ausentes
   - `[MODELAGEM]` — precisa de schema/tabelas/pipelines desenhados
   - `[IMPLEMENTACAO]` — precisa de código
   - `[GOVERNANCA]` — tem dados pessoais (CPF, e-mail, telefone, endereço, CNPJ de parceiros)
   - `[ANALISE]` — exploração/pergunta de negócio
   - `[COMPLETO]` — todas as acima

4. **Geração do #PLANO.** Escreva como primeiro comentário seu (ou substitua se vazio):
   ```
   #PLANO: HEAD → PO → ARQUITETO → GOVERNANÇA → ENGENHEIRO → GOVERNANÇA (final) → HEAD (fecha)
   ETAPAS:
   1. PO (definir critérios de aceite)
   2. Arquiteto (desenho de pipeline e modelagem)
   3. Governança (pré-check LGPD antes de implementação)
   4. Engenheiro (implementação no repo)
   5. Governança (check final de conformidade)
   6. Head (fechamento + vault)
   ```
   Ordem PODE variar — se só tem implementação, pule PO/Arquiteto.

5. **Reatribua.**
   - Próximo agente do plano → atribua ticket + mude status para `in_progress` se estiver `backlog`.
   - Se fechando → anexe work product (vault) → status `done`.

6. **Finalize.** Sempre termine o heartbeat com `callback_heartbeat_run completed`.
