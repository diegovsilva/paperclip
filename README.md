# DataCorp AI

Empresa multiagente de dados para pipelines, analytics, governanca, automacao e machine learning em GCP, AWS, Azure e stack open-source.

Este repositório contem um pacote de empresa no formato `agentcompanies/v1`, pronto para importacao no Paperclip em `company-package/`.

## O que esta empresa faz

`DataCorp AI` foi desenhada para operar uma area de dados completa com agentes especializados, cadeia de reporte clara e delegacao em cascata.

Capacidades principais:

- ingestao e transformacao de dados
- modelagem canonica e semantic layer
- automacao operacional com N8N
- governanca, privacidade e lineage
- observabilidade e confiabilidade de pipelines
- entrega de features e modelos de ML

## Como a empresa opera

O fluxo da empresa segue um modelo `hub-and-spoke` com distribuicao em dois niveis:

1. O board ou operador envia objetivos para o `Data Lead`.
2. O `Data Lead` transforma esses objetivos em trabalho executavel e distribui para liderancas e especialistas.
3. `Cloud Engineer`, `Data Architect` e `N8N Engineer` coordenam dominios tecnicos e podem repassar trabalho para especialistas downstream.
4. Especialistas entregam artefatos duraveis, testes, riscos e proximos passos para o agente responsavel pelo handoff.
5. Mudancas com risco de custo, producao, privacidade ou arquitetura sobem para aprovacao antes da execucao.

## Organograma

| Agente | Papel | Reporta para | Skills principais |
| --- | --- | --- | --- |
| `data-lead` | Lider de operacoes de dados | `null` | `paperclip`, `data-lead` |
| `cloud-engineer` | Plataforma de dados multi-cloud | `data-lead` | `cloud-data-platform`, `data-observability` |
| `data-architect` | Arquitetura e contratos canonicos | `data-lead` | `data-architecture` |
| `n8n-engineer` | Automacao e workflows | `data-lead` | `n8n-data-automation` |
| `analytics-engineer` | Semantic layer e metricas certificadas | `data-architect` | `analytics-engineering`, `data-quality` |
| `ml-engineer` | Features, treino e readiness de ML | `data-architect` | `ml-platform`, `data-quality` |
| `data-governance` | Politicas, privacidade e controles | `data-architect` | `data-governance` |
| `senior-data-engineer` | Implementacao de pipelines | `data-architect` | `senior-data-engineering`, `data-quality` |
| `python-engineer` | Conectores, APIs e servicos de dados | `senior-data-engineer` | `python-data-services` |
| `data-tester` | Qualidade e regressao de dados | `senior-data-engineer` | `data-quality` |
| `data-observability-engineer` | Telemetria, alertas e confiabilidade | `cloud-engineer` | `data-observability` |

## Agentes

- `Data Lead`: recebe objetivos do board, prioriza, delega, resolve conflitos e aplica gates de aprovacao.
- `Cloud Engineer`: cuida de infraestrutura, ambientes, CI/CD, custo e runtime operacional.
- `Data Architect`: define modelos, contratos, ownership e estrategia de armazenamento.
- `N8N Engineer`: cria automacoes, integracoes e workflows operacionais.
- `Analytics Engineer`: entrega marts, semantic layer e metricas certificadas.
- `ML Engineer`: transforma contratos aprovados em features, experimentos e readiness de deploy.
- `Data Governance`: aplica politicas, classificacao, lineage e revisoes de conformidade.
- `Senior Data Engineer`: implementa pipelines e coordena entrega tecnica de dados.
- `Python Engineer`: desenvolve conectores, APIs e servicos auxiliares.
- `Data Tester`: valida regressao, contratos e qualidade dos ativos entregues.
- `Data Observability Engineer`: monitora freshness, falhas, drift e aderencia a SLA.

## Estrutura do pacote

```text
.
├── COMPANY.md
├── .paperclip.yaml
├── agents/
│   ├── analytics-engineer/AGENTS.md
│   ├── cloud-engineer/AGENTS.md
│   ├── data-architect/AGENTS.md
│   ├── data-governance/AGENTS.md
│   ├── data-lead/AGENTS.md
│   ├── data-observability-engineer/AGENTS.md
│   ├── data-tester/AGENTS.md
│   ├── ml-engineer/AGENTS.md
│   ├── n8n-engineer/AGENTS.md
│   ├── python-engineer/AGENTS.md
│   └── senior-data-engineer/AGENTS.md
├── teams/
│   ├── architecture/TEAM.md
│   ├── delivery/TEAM.md
│   └── platform/TEAM.md
├── projects/
│   ├── canonical-data-platform/
│   ├── operating-rhythm/
│   └── platform-foundation/
├── tasks/
│   └── weekly-operating-review/TASK.md
└── skills/
    ├── analytics-engineering/SKILL.md
    ├── cloud-data-platform/SKILL.md
    ├── data-architecture/SKILL.md
    ├── data-governance/SKILL.md
    ├── data-lead/SKILL.md
    ├── data-observability/SKILL.md
    ├── data-quality/SKILL.md
    ├── ml-platform/SKILL.md
    ├── n8n-data-automation/SKILL.md
    ├── python-data-services/SKILL.md
    └── senior-data-engineering/SKILL.md
```

## Teams

| Team | Manager | Escopo |
| --- | --- | --- |
| `platform` | `cloud-engineer` | runtime multi-cloud, ambientes, confiabilidade e observabilidade |
| `architecture` | `data-architect` | contratos canonicos, governanca, ownership e evolucao de modelo |
| `delivery` | `senior-data-engineer` | implementacao de pipelines, analytics, ML, automacao e validacao |

## Projetos iniciais

| Projeto | Owner | Objetivo |
| --- | --- | --- |
| `platform-foundation` | `cloud-engineer` | Estabelecer runtime multi-cloud, postura operacional e observabilidade inicial |
| `canonical-data-platform` | `data-architect` | Definir o primeiro modelo canonico governado e base de ingestao |
| `operating-rhythm` | `data-lead` | Criar a cadencia de execucao, revisao e baseline de qualidade |

## Starter tasks

| Task | Assignee | Projeto |
| --- | --- | --- |
| `bootstrap-multicloud-runtime` | `cloud-engineer` | `platform-foundation` |
| `establish-pipeline-observability` | `data-observability-engineer` | `platform-foundation` |
| `stand-up-n8n-automation-backbone` | `n8n-engineer` | `platform-foundation` |
| `design-canonical-sales-model` | `data-architect` | `canonical-data-platform` |
| `build-orders-ingestion-foundation` | `senior-data-engineer` | `canonical-data-platform` |
| `define-governance-control-baseline` | `data-governance` | `canonical-data-platform` |
| `design-ml-feature-readiness-slice` | `ml-engineer` | `canonical-data-platform` |
| `stand-up-data-quality-baseline` | `data-tester` | `operating-rhythm` |
| `weekly-operating-review` | `data-lead` | recorrente |

## Getting Started

### Importar no Paperclip

Caminho canonico de importacao:

```bash
paperclipai company import d:\\orchestration-zero-humans\\paperclip\\company-package
```

Se voce estiver na raiz do repositório:

```bash
paperclipai company import .\\company-package
```

Nao use a raiz inteira do repo como origem do import. O importador varre os markdowns recursivamente, entao a pasta correta para operacao e distribuicao eh `company-package/`.

### Arquivos principais

- `COMPANY.md` define a identidade, os objetivos e o modelo operacional da empresa.
- `agents/*/AGENTS.md` define papel, reporte, skills e contrato de execucao de cada agente.
- `teams/*/TEAM.md` documenta subarvores organizacionais reutilizaveis da empresa.
- `projects/*/PROJECT.md` organiza as primeiras frentes de execucao da empresa.
- `projects/*/tasks/*/TASK.md` define starter tasks por frente de trabalho.
- `tasks/*/TASK.md` guarda rotinas operacionais recorrentes da empresa.
- `skills/*/SKILL.md` define capacidades reutilizaveis locais da empresa.
- `.paperclip.yaml` define adapters Paperclip por agente e rotinas agendadas.

### Observacao sobre import

O formato `teams/` segue a spec `agentcompanies/v1`, mas o fluxo atual de import/export do Paperclip nesta base ainda esta centrado em `company`, `agents`, `projects`, `tasks` e `skills`. Assim, as equipes funcionam hoje como camada organizacional e documental do pacote.

## Adapters configurados

- `claude_local`: `data-lead`, `cloud-engineer`, `data-architect`, `n8n-engineer`, `analytics-engineer`, `ml-engineer`, `data-governance`, `senior-data-engineer`, `python-engineer`, `data-observability-engineer`
- `gemini_local`: `data-tester`

## Rotinas

- `weekly-operating-review`: roda toda segunda-feira as `09:00` em `America/Sao_Paulo`

## Referencias

- Agent Companies Specification: [agentcompanies.io/specification](https://agentcompanies.io/specification)
- Paperclip: [github.com/paperclipai/paperclip](https://github.com/paperclipai/paperclip)
- COMPANY root: [COMPANY.md](file:///d:/orchestration-zero-humans/paperclip/COMPANY.md)
- Configuracao Paperclip: [.paperclip.yaml](file:///d:/orchestration-zero-humans/paperclip/.paperclip.yaml)

## Licenca

MIT
