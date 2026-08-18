# Heartbeat Checklist — Analista de Dados

1. **Entende a pergunta.** Lê ticket e reformula a pergunta de negócio em linguagem analítica clara (1 frase). Se ambígua: `REVISAO_NECESSARIA: head | Pergunta ambígua, proponho estas 3 interpretações, qual é a correta?`.

2. **Identifica fontes.** Consulte vault/padrão-do-repositório para nomes de tabelas, data warehouse, conexões. Se não tiver → `REVISAO_NECESSARIA: engenheiro | Preciso de acesso à tabela X para responder`.

3. **Explora & valida.**
   - Conta linhas, datas mínima/máxima, distinct counts.
   - Procura nulos / outliers.
   - Produz análise.

4. **Escreve resposta com output padrão** (resumo, metodologia, resultados, limitações, gráfico se couber).

5. **Fecha com ETAPA_CONCLUIDA** e volta ao Head.
