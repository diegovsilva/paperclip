# PROJETO: Interestelar

> Este documento é o prompt de contexto completo do projeto. Cole isso no início de
> qualquer sessão com Claude, Cursor, Codex ou outro coding agent antes de pedir
> implementação, revisão ou extensão de qualquer parte do sistema. Ele descreve o
> quê, o porquê de cada escolha técnica, e as regras que nunca devem ser quebradas.

---

## 1. Visão geral

**Interestelar** é um harness multi-agente que simula um time de engenharia de
dados dentro de qualquer empresa. Uma demanda chega (ex: "criar pipeline de
ingestão de vendas", "expor base de clientes pra um parceiro"), e agentes
especializados — Head de Dados, PO, Arquiteto, Engenheiro, Eng. de Governança e
Analista — colaboram pra resolvê-la, incluindo **revisão cruzada entre si** quando
um agente identifica um problema fora da própria alçada (ex: o Engenheiro percebe
que a modelagem do Arquiteto não escala e devolve a tarefa pra ele).

O sistema é **acoplável a qualquer repositório**: antes de qualquer agente agir,
o padrão de desenvolvimento da empresa (arquitetura, convenções, domínio) é
detectado automaticamente. Cada decisão é documentada numa memória navegável
(vault Obsidian), e o dashboard visual do Paperclip serve como interface humana.

Objetivo de portfólio: demonstrar competência em engenharia agêntica aplicada a um
problema real de processo (triagem e execução de demandas de dados), não um
chatbot de FAQ.

## 2. Princípios não-negociáveis

Estes valem em qualquer parte da implementação, sem exceção:

1. **Harness de revisão com limite**: máximo 3 revisões no total por demanda,
   máximo 2 idas e voltas entre o mesmo par de agentes. Sem isso, o sistema pode
   entrar em loop.
2. **Skills externas nunca aplicam sozinhas**: qualquer atualização de skill vinda
   de fonte externa (documentação, changelog) fica em `skills_pendentes/` até um
   humano aprovar explicitamente. Nunca escrever direto em `skills/`.
3. **O padrão do repositório sempre é consultado** antes de qualquer proposta de
   arquitetura/pipeline. Desvio do padrão detectado precisa ser justificado
   explicitamente pelo agente que propõe.
4. **Tudo gratuito, exceto onde documentado o contrário**: o único componente que
   não é gratuito é a análise via Reversa, que depende de Claude Code CLI
   autenticado (requer assinatura). Há fallback gratuito (API do GitHub/GitLab)
   quando isso não está disponível.
5. **Sem Jarvis / assistente pessoal cross-empresa**: descartado por limitação
   confirmada da API do Paperclip (cross-company access é bloqueado por design —
   ver seção 9). Não reintroduzir esse conceito sem resolver isso primeiro.

## 3. Componentes e por que cada um foi escolhido

| Componente | Papel | Por que esse e não outro |
|---|---|---|
| **Paperclip** (github.com/paperclipai/paperclip) | Plataforma — org chart de agentes, tickets, skills, aprovações, dashboard | Modela nativamente cargo/hierarquia/delegação; descartamos o Composio Agent Orchestrator porque ele é feito pra fleets de coding agents com PR/CI, não pra agentes de processo/negócio |
| **Reversa** (github.com/sandeco/reversa) | Detecta o padrão de desenvolvimento do repositório da empresa | Não é uma lib Python — é um framework Node que roda dentro de um coding agent (Claude Code) e produz specs reais de arquitetura, não só lista arquivos |
| **Groq** | LLM gratuito por trás de cada agente | Free tier rápido, sem cartão de crédito |
| **Obsidian** (só a estrutura de vault — sem app rodando) | Memória navegável do time, por repositório | Wikilinks nativos, zero custo, zero API — é literalmente uma pasta de markdown |
| **SQLite** | Sidecar de estado — cache do padrão do repo, contador de revisões por ticket | Leve, sem servidor extra, cabe num container |
| **FastAPI** (nosso código) | Servidor que recebe os webhooks/heartbeats do Paperclip e roda a lógica de cada agente | Ponte entre o adapter `http` do Paperclip e nossos agentes Python |
| **Docker Compose** | Empacotamento — harness + Paperclip na mesma rede | Reprodutibilidade, um `docker compose up` sobe tudo |

## 4. Os agentes (org chart no Paperclip)

```
Head de Dados (roteador — decide quem entra em cada demanda, sem ordem fixa)
   ├── PO de Dados            escopo, critérios de aceite
   ├── Arquiteto de Dados     modelagem, desenho de pipeline
   ├── Engenheiro de Dados    implementação
   ├── Eng. de Governança     LGPD, qualidade, conformidade — pode virar approval gate real
   └── Analista de Dados      análise sob demanda

Curador de Skills (7º agente — não participa de demandas, roda em Routine agendada)
   └── verifica fontes externas, propõe atualização de skill, NUNCA aplica sozinho
```

Todos os 6 agentes de demanda + o Curador usam **adapter `http`**: o LLM call
acontece no nosso servidor (Groq), não no runtime interno do Paperclip. Isso
significa que **skill/identidade não é carregada automaticamente pelo Paperclip**
— é o nosso código que lê os arquivos e monta o prompt (seção 6).

## 5. Fluxo de uma demanda, passo a passo

1. Demanda chega → criada como **ticket** no Paperclip, atribuída ao Head de Dados.
   O padrão do repositório (cacheado em SQLite, ou recalculado via Reversa) é
   anexado como contexto na descrição do ticket.
2. Heartbeat acorda o Head → ele decide qual agente entra primeiro (sem ordem
   fixa — pode ser só o PO, só o Engenheiro, ou os cinco em sequência, depende
   da natureza da demanda) → reatribui o ticket.
3. O agente designado acorda por heartbeat → carrega sua identidade
   (`SOUL.md`+`AGENTS.md`+`HEARTBEAT.md`) e as skills relevantes → processa com
   o LLM → comenta o resultado no ticket.
4. Se esse agente identificar um problema fora da própria alçada, termina a
   resposta com `REVISAO_NECESSARIA: <agente> | <motivo>` → o ticket é
   reatribuído direto pra esse agente (respeitando o harness da seção 2.1) →
   senão, o ticket volta pro Head decidir o próximo passo.
5. Quando não há mais nada a fazer, o Head fecha: resultado final vira comentário
   consolidado, e uma nota é criada em `vault/Demandas/`, anexada ao ticket como
   work product.

## 6. Identidade e skills dos agentes

Cada agente tem, no nosso próprio repositório (não no Paperclip):

```
agents/<papel>/
├── SOUL.md        persona e voz — curto, até ~40 linhas, não é instrução
├── AGENTS.md       papel, segurança, referências às skills relevantes
└── HEARTBEAT.md    checklist do que fazer a cada ticket atribuído
```

Skills (procedimentos reutilizáveis, podem ser usados por mais de um agente):

| Skill | Quem usa | Fonte externa? |
|---|---|---|
| `revisao-cruzada` | todos os 6 | não — protocolo interno |
| `criterios-aceite` | PO | não |
| `registro-vault` | todos os 6 | não |
| `padrao-repositorio` | Arquiteto, Engenheiro, Governança | sim — changelog do Reversa |
| `modelagem-dados` | Arquiteto | sim — boas práticas de mercado |
| `checklist-lgpd` | Governança (consultável pelo Arquiteto) | sim — ANPD |

O nosso `webhook.py` monta o prompt de cada chamada concatenando identidade +
skills relevantes + a demanda + qualquer feedback de revisão pendente — ver
`harness/webhook.py` na estrutura de repositório (seção 8).

## 7. Curadoria automática de skills (com aceite manual obrigatório)

Skills com fonte externa são checadas semanalmente (Routine agendada) pelo
Curador de Skills:

1. Verifica se o conteúdo das fontes mudou (hash) desde a última checagem
2. Se mudou, pede ao LLM pra redigir uma versão atualizada do `SKILL.md`
3. Salva o rascunho em `skills_pendentes/<nome>/SKILL.md` — **nunca** em `skills/`
4. Abre um ticket de aprovação no Paperclip, com o diff completo (atual vs.
   proposto) visível no dashboard
5. Só quando um humano aprova explicitamente (clique no ticket → webhook
   `/aprovar-skill/{nome}`), o conteúdo é copiado pra `skills/<nome>/SKILL.md`

Skills sem fonte externa (protocolo interno) nunca entram nesse ciclo.

## 8. Estrutura completa do repositório

```
interestelar/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── harness/
│   ├── webhook.py               # servidor FastAPI, um endpoint por agente
│   ├── tools_repo.py            # integração com Reversa + fallback GitHub/GitLab API
│   ├── tools_memoria.py         # cache SQLite (padrão do repo, contador de revisões)
│   ├── tools_obsidian.py        # escrita das notas no vault
│   ├── tools_skill_curator.py   # checagem/rascunho de skills externas
│   └── paperclip_client.py      # wrapper das chamadas à API do Paperclip
├── agents/
│   ├── head/  po/  arquiteto/  engenheiro/  governanca/  analista/
│   │   └── SOUL.md, AGENTS.md, HEARTBEAT.md (um conjunto por pasta)
├── skills/
│   ├── revisao-cruzada/SKILL.md
│   ├── criterios-aceite/SKILL.md
│   ├── registro-vault/SKILL.md
│   ├── padrao-repositorio/SKILL.md
│   ├── modelagem-dados/SKILL.md
│   └── checklist-lgpd/SKILL.md
├── skills_pendentes/             # rascunhos do Curador — vazio até haver proposta
├── repositorios/
│   └── <slug-empresa>/           # repositório da empresa, ANINHADO dentro do Interestelar
│                                  # (clone persistente via git, ou git submodule)
├── vault/                        # abre direto no Obsidian
│   ├── Padrão do Repositório.md
│   ├── Agentes/
│   └── Demandas/
└── db/
    └── interestelar.db           # SQLite (cache de repo + contador de revisões)
```

**Nota importante sobre `repositorios/<slug>/`**: o repositório da empresa não é
clonado num diretório temporário e descartado — ele vive persistente dentro do
próprio projeto Interestelar. `tools_repo.py` tem duas funções pra isso:
`garantir_repo_local()` (clone simples + `git pull`) e `garantir_repo_submodulo()`
(via `git submodule`, se quiser versionar a referência exata do repo da empresa
junto do histórico do Interestelar).

## 9. Integração com Paperclip — detalhes que importam

- **Adapter `http`**: cada agente é registrado via `POST /api/agents` com
  `adapterType: "http"` e uma URL própria (`http://harness:8000/webhook/<papel>`).
  Ainda não aparece no dropdown da UI ("Coming soon" na doc), mas funciona via API.
- **Heartbeat**: Paperclip faz `POST` pra URL do agente com
  `{runId, agentId, companyId, context: {taskId, wakeReason, commentId}}`. Resposta
  pode ser síncrona (200 + `{"status": "completed", "result": "..."}`) ou
  assíncrona (202 + callback depois em `/api/heartbeat-runs/:runId/callback`) —
  usar assíncrono se a chamada ao Groq puder passar do `timeoutMs` configurado.
- **Cross-company access é bloqueado por design** — confirmado na doc oficial de
  segurança do Paperclip ("Cross-company access is blocked at the API layer").
  Token de agente só acessa a company que o emitiu; token de board user só acessa
  companies das quais é membro, uma chamada por vez. **Foi por essa limitação que
  o "Jarvis Executivo Pessoal" (assistente cross-empresa) foi descartado** — não
  reintroduzir esse conceito sem resolver isso via iteração empresa-por-empresa
  com um Board API Key.
- **Governança pode virar approval gate real**: em vez de só um agente opinando
  em texto, a etapa de Eng. de Governança pode ser configurada como aprovação
  formal antes do ticket fechar (pillar "Governance & Approvals" do Paperclip).
- Endpoints exatos de `/api/tasks`, `/api/agents`, `/api/companies` foram
  inferidos por convenção REST a partir da doc pública — **confirmar contra
  docs.paperclip.ing antes de rodar em produção**, não foram copiados 1:1 de
  um exemplo funcional testado.

## 10. O que foi deliberadamente descartado (não reintroduzir sem motivo novo)

- **Kanboard** — usado numa versão anterior pra visualizar cards entre agentes;
  aposentado porque o sistema de tickets nativo do Paperclip já cobre isso
  (ticket mudando de agente = card mudando de coluna)
- **Composio Agent Orchestrator** — descartado porque é feito pra fleets de
  coding agents com PR/CI, não pra agentes de processo de negócio; Paperclip
  modela org chart e tickets nativamente, sem gambiarra
- **Jarvis Executivo Pessoal** — assistente cross-empresa com visão de agenda e
  projetos; descartado pela limitação de cross-company access da seção 9

## 11. Variáveis de ambiente

```
GROQ_API_KEY=
PAPERCLIP_API_URL=http://paperclip:3100/api
PAPERCLIP_API_KEY=
PAPERCLIP_COMPANY_ID=
BETTER_AUTH_SECRET=
PAPERCLIP_PUBLIC_URL=http://localhost:3100
```

## 12. Como subir o projeto

```bash
git clone <este repositório> interestelar
cd interestelar
cp .env.example .env   # preencher as chaves
docker compose up -d
# Paperclip: http://localhost:3100 (criar a Company, org chart, gerar API key)
# harness:   http://localhost:8000 (recebe os webhooks)
```

Depois de subir: registrar os 6 agentes + o Curador de Skills via API (seção 9),
montar o org chart no Paperclip (Head no topo, os 5 reportando a ele), e criar o
primeiro ticket de teste pra validar o fluxo ponta a ponta.

---

Este documento é a fonte da verdade do projeto. Qualquer implementação, revisão
ou extensão — feita por mim ou por um coding agent — deve seguir esta estrutura
e, principalmente, os princípios da seção 2, que não têm exceção.
