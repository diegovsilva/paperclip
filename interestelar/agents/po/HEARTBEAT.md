# Heartbeat Checklist — PO de Dados

1. **Lê ticket + descrição completa.** Extrai o pedido core do solicitante, contexto de negócio, e exemplos de uso (se existirem).

2. **Consulta vault/Demandas** (via contexto do ticket) para ver se há demanda similar já fechada.

3. **Rascunha critérios de aceite:**
   - Entre 5 e 10 itens numerados, SMART.
   - Cada critério deve ser verificável: o Engenheiro e QA devem conseguir marcar SIM/NÃO sem interpretar.
   - Itens de dado: nome de tabela, colunas + tipos, granularidade (uma linha por...), SLA/frequência.
   - Itens de qualidade: unique key, não-nulos, validação de ranges.

4. **Escreve FORA DE ESCOPO.** Minimo 3 itens: ex: "Não implementa dashboard", "Não faz limpeza histórica antes de 2024", "Não integra com legado ERP X".

5. **Comenta no ticket** resposta com esta estrutura:
   ```
   ## Escopo definido
   
   ### Contexto
   ... parágrafo curto ...
   
   ### Critérios de Aceite
   1. ...
   2. ...
   ...
   
   ### Fora de Escopo
   - ...
   - ...
   
   ETAPA_CONCLUIDA
   ```
   Se detectar dado pessoal sensível, adicione ANTES do ETAPA_CONCLUIDA:
   ```
   REVISAO_NECESSARIA: governanca | Escopo contém CPF e e-mail de clientes — requisita análise LGPD antes da implementação
   ```

6. **Retorna ao Head** (não atribua você mesmo ao próximo — `ETAPA_CONCLUIDA` faz o Head decidir).
