# Skill: revisao-cruzada

## Descrição
Protocolo interno do Interestelar que governa devoluções entre agentes quando um detecta problema fora da própria alçada. Toda a equipe usa.

## Quando usar
Sempre que um agente identificar:
- Requisito mal formulado que só o PO pode corrigir
- Desenho de arquitetura inviável (volta pro Arquiteto)
- Campo de dado sensível que precisa de validação LGPD (chama Governança)
- Pergunta de negócio que requer novo critério de aceite
- Algo que só o Head resolve (loop detectado, disputa de prioridade)

## Quando NÃO usar
- Quando a tarefa está dentro da sua alçada e você consegue resolver
- Quando é só uma dúvida de interpretação que você mesmo consegue inferir do contexto
- Quando é uma melhoria pequena que não quebra contrato com etapa anterior

## Protocolo
1. No final da sua resposta, escreva EXATAMENTE 1 linha:
   ```
   REVISAO_NECESSARIA: <agente-slug> | <motivo em uma linha, específico>
   ```
   Agentes-slug válidos: `head`, `po`, `arquiteto`, `engenheiro`, `governanca`, `analista`.

2. **Não mude** a atribuição manualmente. O harness faz isso automaticamente depois de checar o contador de revisões.

3. O harness (webhook.py) aplica estes limites em SQLite:
   - Máximo **3 revisões TOTAIS por ticket**
   - Máximo **2 idas e voltas entre o MESMO par** de agentes (A→B e B→A = 1 ida e volta)
4. Se qualquer um destes limites for atingido:
   - O ticket volta AUTOMATICAMENTE para o Head
   - É adicionado um comentário visível no dashboard: "Limite de revisões excedido. Requer decisão humana."
   - O Head decide ou reatribui manualmente

## Marcadores auxiliares
- `ETAPA_CONCLUIDA` → sinaliza que a sua etapa do plano foi cumprida; Head decide o próximo
- `REVISAO_NECESSARIA: head | <motivo>` → puxa decisão humana; não conta como par (pois head é roteador)

## Exemplos CORRETOS
```
Resposta do Arquiteto:
...desenho da modelagem...

REVISAO_NECESSARIA: governanca | Tabela clientes contem CPF, email, telefone e endereco completo. Preciso de validacao LGPD antes do Engenheiro implementar.
```

```
Resposta do Engenheiro:
...implementacao concluida, mas...

REVISAO_NECESSARIA: arquiteto | Item 5 do desenho (chave composta por 4 colunas) causa performance ruim em queries de historico. Proponho surrogate key.
```

## Exemplos INCORRETOS
- Várias linhas no motivo → mantenha 1 linha.
- `REVISAO_NECESSARIA: PO` → use slug minúsculo `po`.
- Motivo genérico: `REVISAO_NECESSARIA: po | precisa ajustar` → seja específico.
