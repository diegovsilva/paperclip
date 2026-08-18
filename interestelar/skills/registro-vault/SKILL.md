# Skill: registro-vault

## Descrição
Registro em vault Obsidian (pasta markdown pura com wikilinks) de tudo o que o time produz. Todo agente usa no final da sua etapa; o Head usa para consolidar a demanda final.

## Estrutura do vault
```
vault/
├── Padrão do Repositório.md      ← 1 arquivo por repo, atualizado pelo tools_repo
├── Agentes/
│   ├── Head/
│   ├── PO/
│   ├── Arquiteto/
│   ├── Engenheiro/
│   ├── Governança/
│   └── Analista/
│       └── <ticket-id>-<slug>.md
└── Demandas/
    └── <YYYY>-<MM>-<slug>.md      ← Nota consolidada final (Head escreve)
```

## O que cada agente escreve, quando
- **Head, PO, Arquiteto, Engenheiro, Governança, Analista** ao finalizar sua etapa:
  - Escrevem uma nota resumo em `vault/Agentes/<Papel>/<ticket-id>-<slug>.md`
  - Conteúdo mínimo: data, ticket_id, resumo de 3-10 linhas do que fez, principais decisões, wikilink p/ demanda final.
- **Head ao fechar demanda:**
  - Escreve `vault/Demandas/<YYYY>-<MM>-<slug>.md` consolidando tudo.
  - Anexa este arquivo como **work product** no ticket Paperclip.

## Formato YAML frontmatter OBRIGATÓRIO em todo arquivo novo
```markdown
---
ticket_id: ISS-123
tipo: etapa-agente | demanda-consolidada
pessoa: Arquiteto
data_criacao: 2026-08-14
agentes_envolvidos: [Head, PO, Arquiteto, Engenheiro, Governança]
status: done
repo_empresa: slug-empresa-xyz
tags: [pipeline, modelagem, lgpd]
links:
  - "[[Padrão do Repositório]]"
  - "[[ISS-122 demanda-anterior]]"
---

# Conteúdo em markdown
...
```

## Regras de escrita
1. **NUNCA** coloque PII, credenciais, secrets no vault. Use placeholders.
2. Use wikilinks `[[Nome-da-Nota]]` o tempo todo para conexão entre notas.
3. Escrita **atômica**: sempre escreva em arquivo temporário → `os.replace()` para evitar corromper notas abertas no Obsidian.
4. Se arquivo já existir, **adicione seção com data** no final — NÃO sobreescreva histórico.
5. Slugs de nome de arquivo: minúsculo, hífens, sem acento, sem espaço (ex: `2026-08-pipeline-ingestao-vendas.md`).

## O que NÃO vai no vault
- Dados brutos / tabelas em CSV
- Código fonte (isso vai no `repositorios/<slug>/`)
- Segredos de qualquer tipo
