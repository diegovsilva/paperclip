# Skill: checklist-lgpd

## Descrição
Checklist de conformidade LGPD com base em referências públicas da ANPD (Agência Nacional de Proteção de Dados). Fonte externa monitorada pelo Curador:
- Resolução CD/ANPD nº 2/2023 (Regulamento do RGPD)
- Guias publicados em gov.br/anpd

Usado pela Governança. **Consultável** pelo Arquiteto e Engenheiro quando eles suspeitam de PII.

## Quando usar
Sempre que:
- A demanda ou o escopo do PO mencionar qualquer dado pessoal ou sensível
- Houver tabela com nome `*cliente*`, `*usuario*`, `*paciente*`, `*funcionario*`, `*lead*`, `*parceiro*`
- O Arquiteto/Engenheiro sinalizar REVISAO_NECESSARIA

## Inventário OBRIGATÓRIO antes de julgar
1. Tabela de inventário:
   | Campo | Tabela | Tipo dado pessoal | Categoria (LGPD) | Base legal | Retenção prevista |
   |---|---|---|---|---|---|
   | | | Identificável / Sensível / Anonimizado | Dado pessoal / Dado sensível / Não se aplica | Consentimento / Legítimo interesse / Contrato / Obrigação legal / Tutela / Saúde / Exercício de direito | X anos / Indefinida |

## Os 10 itens do checklist

1. **Mapeamento de fluxo.** Documente: origem → processamento → armazenamento → compartilhamento → descarte.
2. **Base legal válida.** Cada operação tem 1 (e apenas 1 principal) base legal do art. 7º LGPD. Justifique 1 frase.
3. **Consentimento (se aplicável).** Quando base legal = consentimento, documente: momento de coleta, texto apresentado, prova de coleta, revogabilidade (1 clique).
4. **Direitos dos titulares (ARCO +).** Assegura mecanismo para:
   - Acesso, Correção, Exclusão, Portabilidade, Informação sobre compartilhamento, Oposição.
   - Prazo máximo de resposta: 15 dias úteis.
5. **Rastreabilidade / logs de acesso.** Todo acesso a dado pessoal tem log (quem, quando, finalidade, IP, ação). Retenção de log ≥ 6 meses.
6. **Anonimização / Pseudonimização.** Dado pessoal em camada analítica é pseudonimizado ou anonimizado (defina e documente a diferença para o caso).
7. **Retenção e descarte.** Política: quanto tempo cada dado fica, evento de descarte, método seguro (formato seguro / exclusão lógica + física).
8. **Segurança.** Criptografia em repouso (AES-256) e trânsito (TLS 1.2+). Controles de acesso (RBAC, mínimo privilégio).
9. **Transferência internacional (se houver).** Países destino, garantia de nível adequado ou cláusulas contratuais padrão (CCPs).
10. **Incidentes.** Plano de resposta: detecção → contenção → comunicação ANPD em até 48h úteis (para incidentes relevantes) → comunicação titular → análise de causa raiz.

## Matriz de risco (após checklist)

| Nível | Critérios | Ação |
|---|---|---|
| **Risco ALTO** | 1+ itens do checklist NÃO atendidos e envolvem dado sensível ou multiplicação de dados de milhares de titulares | **NÃO APROVADO.** Enumere itens pendentes. Bloqueie avanço. |
| **Risco MÉDIO** | Itens parcialmente atendidos, sem dado sensível ou com poucos titulares | **APROVADO COM RESSALVAS.** Especifique itens a resolver até fechamento. |
| **Risco BAIXO** | Todos os 10 itens atendidos | **APROVADO.** Documente a aprovação. |

## Formato OBRIGATÓRIO de resposta da Governança
```
## Análise de Conformidade LGPD — <ticket-id>

### Resumo Executivo
<1 frase: aprovado / aprovado com ressalvas / não aprovado + grau de risco.>

### Inventário de Dados Pessoais
<tabela inventário>

### Checklist
1. Mapeamento de fluxo — ✅ / ⚠️ / ❌ + <1 frase observação>
2. Base legal — ...
...
10. Incidentes — ...

### Matriz de Risco
Risco classificado: BAIXO / MÉDIO / ALTO

### Ações Recomendadas
<bulleted se houver.>

### Resultado Final
APROVADO | APROVADO COM RESSALVAS: <texto curto> | NÃO APROVADO: <itens bloqueantes>

ETAPA_CONCLUIDA
```

## Regra para Arquiteto e Engenheiro (consultáveis)
Se vocês consultarem este skill sozinhos e detectarem item 6 ou 8 não atendidos, **NÃO tentem resolver sozinhos.** Sempre disparem REVISAO_NECESSARIA para a Governança com a evidência.
