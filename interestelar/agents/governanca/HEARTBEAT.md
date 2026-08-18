# Heartbeat Checklist — Governança

1. **Coleta contexto.** Lê ticket, comentários, descrição, critérios de aceite do PO, desenho do Arquiteto, implementação do Engenheiro (se houver).

2. **Extrai inventário de dados pessoais.** Tabela com:
   - Campo
   - Tipo de dado (identificável, sensível, anonimizado)
   - Base legal (consentimento, legítimo interesse, contrato, etc.)
   - Retenção estimada
   - Quem acessa

3. **Aplica SKILL checklist-lgpd.** Preenche cada item do checklist:
   - 1. Mapeamento de fluxo de dados
   - 2. Base legal
   - 3. Consentimento (se aplicável)
   - 4. Direitos do titular (ACESSO, CORREÇÃO, EXCLUSÃO, PORTABILIDADE)
   - 5. Rastreabilidade / logs de acesso
   - 6. Anonimização / pseudonimização
   - 7. Retenção e descarte
   - 8. Segurança (criptografia em repouso e trânsito)
   - 9. Transferência internacional (se houver)
   - 10. Rastreabilidade de incidentes

4. **Classifica risco.** BAIXO / MÉDIO / ALTO, cada item com justificativa e ação recomendada.

5. **Resposta final.** Estrutura:
   - Resumo executivo (1 frase)
   - Inventário (tabela)
   - Checklist preenchido (10 itens)
   - Classificação de risco + ações
   - APROVADO / APROVADO COM RESSALVAS / NÃO APROVADO
   - `ETAPA_CONCLUIDA`

6. **Se for stage de implementação faltando item de risco alto**: `REVISAO_NECESSARIA: engenheiro | Item X de risco alto precisa ser resolvido antes da aprovação final`.
