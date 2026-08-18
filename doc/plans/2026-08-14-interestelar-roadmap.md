# Roadmap: Implementação do Projeto Interestelar sobre Paperclip

> Data: 2026-08-14
> Fonte da verdade: [interestelar-PROMPT-COMPLETO.md](file:///d:/orchestration-zero-humans/paperclip/interestelar-PROMPT-COMPLETO.md)
> Contexto base: Paperclip V1 — [SPEC-implementation.md](file:///d:/orchestration-zero-humans/paperclip/doc/SPEC-implementation.md)

---

## Resumo Executivo

O **Interestelar** é um harness multi-agente *acoplado* ao Paperclip (não um fork). Ele implementa um time de engenharia de dados (6 agentes de demanda + 1 Curador de Skills) com roteamento dinâmico, revisão cruzada limitada, curadoria de skills com aprovação humana obrigatória, detecção automática do padrão do repositório da empresa e memória navegável em vault Obsidian.

Todo o código novo do Interestelar fica **fora do core do Paperclip** — numa pasta própria `interestelar/` no repo, com seu próprio `docker-compose.yml` que sobe o Paperclip (imagem existente) junto com o harness Python.

---

## Princípios Não-Negociáveis (SEÇÃO 2 DO PROMPT)

Nenhuma implementação deve quebrar estes:

1. **Harness de revisão com limite**: máximo 3 revisões no total por demanda, máximo 2 idas e voltas entre o mesmo par de agentes.
2. **Skills externas nunca aplicam sozinhas**: qualquer atualização fica em `skills_pendentes/` até aprovação humana explícita via endpoint dedicado.
3. **Padrão do repositório sempre consultado** antes de proposta de arquitetura/pipeline. Desvio precisa ser justificado.
4. **Tudo gratuito, exceto análise via Reversa** (Claude Code CLI autenticado). Fallback: API GitHub/GitLab.
5. **Sem cross-company / Jarvis pessoal**: confirmado bloqueio na API layer do Paperclip — não reintroduzir.

---

## Fase 0 — Scaffolding e Infraestrutura Base

### 0.1 Criar estrutura de diretórios `interestelar/`

```
interestelar/
├── docker-compose.yml          # Paperclip + harness na mesma rede
├── Dockerfile                  # Imagem Python do harness
├── requirements.txt            # FastAPI, Groq, httpx, PyGithub, python-gitlab, etc.
├── .env.example                # Todas as variáveis da seção 11
├── harness/
├── agents/
├── skills/
├── skills_pendentes/           # Vazio até proposta do Curador
├── repositorios/               # Repos persistentes (clone / submodule)
├── vault/                      # Abre direto no Obsidian
│   ├── Padrão do Repositório.md
│   ├── Agentes/
│   └── Demandas/
└── db/
    └── interestelar.db         # SQLite (criado em runtime)
```

**Arquivos a criar (12 dirs + 4 arquivos raiz):**

| Caminho | Descrição |
|---|---|
| `interestelar/docker-compose.yml` | Serviços `paperclip` (imagem ou build do core) + `harness` (Python 3.12) + volume compartilhado p/ `repositorios/` e `vault/` |
| `interestelar/Dockerfile` | Python 3.12-slim, `pip install -r requirements.txt`, entrypoint `uvicorn harness.webhook:app --host 0.0.0.0 --port 8000` |
| `interestelar/requirements.txt` | `fastapi`, `uvicorn[standard]`, `groq`, `httpx`, `pyyaml`, `python-dotenv`, `aiosqlite`, `PyGithub`, `python-gitlab`, `GitPython`, `pydantic`, `pydantic-settings` |
| `interestelar/.env.example` | `GROQ_API_KEY`, `PAPERCLIP_API_URL`, `PAPERCLIP_API_KEY`, `PAPERCLIP_COMPANY_ID`, `BETTER_AUTH_SECRET`, `PAPERCLIP_PUBLIC_URL`, `GITHUB_TOKEN` (opcional), `GITLAB_TOKEN` (opcional), `REVERSA_CLAUDE_CODE_AUTH` (opcional) |

**Dependências do core do Paperclip que já existem — NÃO reimplementar:**
- Adapter `http` — já existe em [server/src/adapters/http/index.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/adapters/http/index.ts#L1-L21)
- Heartbeat service — já existe em [server/src/services/heartbeat.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/heartbeat.ts)
- Company Skills CRUD — já existe em [server/src/services/company-skills.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/company-skills.ts#L1-L80)
- Routines scheduler — já existe em [server/src/services/routines.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/routines.ts#L1-L80)

### 0.2 Docker Compose integrado

O `docker-compose.yml` do Interestelar deve:
- Usar a imagem do Paperclip (ou build do `../Dockerfile`) na porta 3100
- Serviço `harness` na porta 8000, na mesma rede Docker
- Volumes: `./repositorios`, `./vault`, `./db` montados no harness
- Healthcheck do Paperclip antes do harness subir

---

## Fase 1 — Harness FastAPI e Cliente Paperclip

### 1.1 `harness/paperclip_client.py` — Wrapper da API do Paperclip

Módulo de baixo nível que abstrai as chamadas REST do Paperclip (confirmar endpoints contra docs.paperclip.ing antes de rodar em produção).

**Métodos obrigatórios:**

| Método | Endpoint (estimado) | Payload |
|---|---|---|
| `criar_agente_http(company_id, nome, role, webhook_url)` | `POST /api/agents` | `{name, adapterType:"http", config:{url,timeoutSec}}` |
| `atribuir_ticket(ticket_id, agent_id)` | `PATCH /api/issues/:id` | `{assigneeId}` |
| `comentar_ticket(ticket_id, texto, work_product_url?)` | `POST /api/issues/:id/comments` | `{body, attachments?}` |
| `atualizar_status_ticket(ticket_id, status)` | `PATCH /api/issues/:id` | `{status}` (backlog/todo/in_progress/in_review/blocked/done/cancelled) |
| `criar_ticket(company_id, titulo, descricao, assignee_id, project_id?)` | `POST /api/issues` | `{title, description, assigneeId, priority}` |
| `ler_ticket(ticket_id)` | `GET /api/issues/:id` | — |
| `listar_comentarios(ticket_id)` | `GET /api/issues/:id/comments` | — |
| `callback_heartbeat(run_id, status, result)` | `POST /api/heartbeat-runs/:runId/callback` | `{status:"completed", result}` |
| `listar_agentes(company_id)` | `GET /api/agents?companyId=...` | — |
| `anexar_work_product(ticket_id, file_path, mime)` | `POST /api/assets` + `PATCH /api/issues/:id` | upload + attach |
| `criar_segredo(company_id, key, value)` | `POST /api/secrets` | `{key, encryptedValue, scope}` |
| `criar_routine(company_id, nome, cron, agent_id, description)` | `POST /api/routines` | `{name, scheduleCron, description, assignedAgentId}` |

### 1.2 `harness/webhook.py` — Servidor FastAPI

**Endpoints principais (um por agente, assíncronos por padrão — timeout Groq > 30s):**

```
POST /webhook/head            # Head de Dados (roteador)
POST /webhook/po              # PO de Dados
POST /webhook/arquiteto       # Arquiteto de Dados
POST /webhook/engenheiro      # Engenheiro de Dados
POST /webhook/governanca      # Eng. de Governança
POST /webhook/analista        # Analista de Dados
POST /webhook/curador-skills  # Curador de Skills (Routine semanal)

POST /aprovar-skill/{nome}    # Aprovação humana de skill pendente
GET  /health                  # Healthcheck
```

**Contrato de entrada (heartbeat do Paperclip):**
```json
{
  "runId": "string",
  "agentId": "string",
  "companyId": "string",
  "context": {
    "taskId": "string",
    "wakeReason": "assigned|commented|routine|manual",
    "commentId": "string?"
  }
}
```

**Fluxo interno de cada endpoint:**
1. Recebe payload → responde **imediatamente 202 Accepted** (não bloquear no Paperclip)
2. Lê ticket + comentários via `paperclip_client`
3. Carrega identidade do agente (`SOUL.md` + `AGENTS.md` + `HEARTBEAT.md`)
4. Carrega skills relevantes (por agente, vide seção 6 do prompt)
5. Monta prompt completo: `identidade + skills + ticket + feedbacks_revisao_pendentes`
6. Chama Groq (modelo padrão: `llama-3.1-70b-versatile` ou `mixtral-8x7b-32768` — checar disponibilidade no free tier)
7. Parseia resposta → detecta `REVISAO_NECESSARIA: <agente> | <motivo>` no final
8. Verifica harness de revisão (SQLite: contadores por ticket + par de agentes)
9. Comenta resultado no ticket
10. Reatribui ticket: Head → proximo agente / agente → Head ou agente alvo da revisão
11. Callback `heartbeat-runs/:runId/callback` com status final

**Middleware do FastAPI:**
- Logger estruturado (JSON)
- Rate limit por IP (100 req/min — evitar loop acidental)
- Auth: header `X-Webhook-Secret` comparado com hash do `PAPERCLIP_API_KEY` (não expor a chave real no header)

---

## Fase 2 — Identidade dos Agentes e Skills

### 2.1 Criar 7 conjuntos de identidade de agentes

**Local:** `interestelar/agents/<papel>/`

Estrutura por pasta:
```
<head | po | arquiteto | engenheiro | governanca | analista | curador-skills>/
├── SOUL.md        # Persona e voz — ~40 linhas, não instrução
├── AGENTS.md       # Papel, regras de segurança, referências às skills relevantes
└── HEARTBEAT.md    # Checklist do que fazer a cada ticket atribuído
```

**Mapeamento de skills por agente (seção 6 do prompt):**

| Agente | Skills obrigatórias |
|---|---|
| Head de Dados | `revisao-cruzada`, `registro-vault`, `padrao-repositorio` |
| PO de Dados | `criterios-aceite`, `registro-vault`, `revisao-cruzada` |
| Arquiteto | `padrao-repositorio`, `modelagem-dados`, `registro-vault`, `revisao-cruzada`, `checklist-lgpd` (consultável) |
| Engenheiro | `padrao-repositorio`, `registro-vault`, `revisao-cruzada` |
| Governança | `checklist-lgpd`, `padrao-repositorio`, `registro-vault`, `revisao-cruzada` |
| Analista | `registro-vault`, `revisao-cruzada` |
| Curador Skills | Nenhuma das demandas — usa `tools_skill_curator.py` diretamente |

### 2.2 Criar 6 skills iniciais

**Local:** `interestelar/skills/<nome>/SKILL.md`

| Skill | Fonte externa? | Fonte | Quem usa |
|---|---|---|---|
| `revisao-cruzada` | Não | Protocolo interno | Todos 6 agentes de demanda |
| `criterios-aceite` | Não | Interno | PO |
| `registro-vault` | Não | Interno | Todos 6 |
| `padrao-repositorio` | Sim | Changelog do Reversa (github.com/sandeco/reversa) | Arquiteto, Engenheiro, Governança |
| `modelagem-dados` | Sim | Boas práticas de mercado (Kimball, Data Vault 2.0, dbt docs) | Arquiteto |
| `checklist-lgpd` | Sim | ANPD ( Resolução CD/ANPD nº 2/2023 + guias oficiais ) | Governança (Arquiteto consulta) |

**Formato `SKILL.md` (seguir o padrão das skills existentes no core, ex: [skills/paperclip/SKILL.md](file:///d:/orchestration-zero-humans/paperclip/skills/paperclip/SKILL.md)):**
- Título + descrição curta
- Quando usar / quando NÃO usar
- Passo a passo (checklist numerado)
- Exemplos concretos
- Referências / fontes

---

## Fase 3 — Ferramentas de Suporte (Harness Tools)

### 3.1 `harness/tools_memoria.py` — Cache SQLite

Esquema mínimo do `interestelar.db`:

```sql
-- Cache do padrão do repositório (por slug de empresa)
CREATE TABLE repo_pattern_cache (
    slug_empresa TEXT PRIMARY KEY,
    pattern_md TEXT NOT NULL,
    source TEXT NOT NULL,    -- 'reversa' | 'github_api' | 'gitlab_api' | 'manual'
    hash_content TEXT NOT NULL,
    obtido_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expira_em DATETIME NOT NULL  -- padrão: 7 dias depois
);

-- Contador de revisões por ticket (harness seção 2.1)
CREATE TABLE ticket_revisoes (
    ticket_id TEXT PRIMARY KEY,
    total_revisoes INTEGER NOT NULL DEFAULT 0,
    par_revisoes TEXT NOT NULL DEFAULT '{}'  -- JSON: {"agenteA->agenteB": 2, ...}
);

-- Histórico de curadoria de skills
CREATE TABLE skill_curadoria_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_nome TEXT NOT NULL,
    fonte_hash TEXT NOT NULL,
    proposta_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    aprovada_em DATETIME,
    aprovada_por TEXT  -- user id ou 'board'
);

CREATE INDEX idx_ticket_revisoes_total ON ticket_revisoes(total_revisoes);
CREATE INDEX idx_skill_curadoria_nome ON skill_curadoria_log(skill_nome);
```

**Métodos públicos:**
- `obter_padrao_repo(slug_empresa) -> PatternCache | None`
- `salvar_padrao_repo(slug_empresa, pattern_md, source, hash_content, ttl_dias=7)`
- `incrementar_revisao(ticket_id, de_agente, para_agente) -> (total_atual, contagem_par)`
  - **Lança exceção** se `total_atual >= 3` OU `contagem_par >= 2` (harness 2.1)
- `resetar_revisoes(ticket_id)` — ao fechar demanda

### 3.2 `harness/tools_repo.py` — Detecção do padrão do repositório

**Estratégia de fallback (do prompt seção 2.4):**

```
Prioridade 1: Reversa (Claude Code CLI autenticado)
    → requer REVERSA_CLAUDE_CODE_AUTH configurada
    → roda: cd repositorios/<slug> && npx reversa@latest analyze
    → parseia output em MD
    
Prioridade 2: GitHub / GitLab API
    → tree + contents dos arquivos chave (.github/, docker-compose, package.json/pyproject.toml, README, docs/)
    → prompt Groq: "dado estes arquivos, extraia o padrão de desenvolvimento..."
    
Prioridade 3: Análise local (GitPython + Groq)
    → ls -R estrutural + 10% de arquivos aleatórios
    → prompt Groq (mesmo da prioridade 2)
```

**Métodos públicos:**
- `garantir_repo_local(slug_empresa, repo_url, auth=None) -> Path`
  - `git clone` se não existe, `git pull` se existe
- `garantir_repo_submodulo(slug_empresa, repo_url) -> Path`
  - `git submodule add` se não existe, `git submodule update --remote` se existe
- `obter_ou_gerar_padrao(slug_empresa, repo_url, strategy_priority?) -> str`
  - Consulta `tools_memoria.obter_padrao_repo` primeiro
  - Se expirado/ausente: roda estratégias em ordem
  - Salva cache com hash do conteúdo + expiração
- `hash_conteudo_fonte(texto) -> str` (SHA-256 — usado pelo Curador)

### 3.3 `harness/tools_obsidian.py` — Escrita no vault Obsidian

**Métodos públicos:**
- `escrever_padrao_repo(slug_empresa, conteudo_md)` → `vault/Padrão do Repositório.md` (com subseção por empresa se múltiplas)
- `escrever_demanda(ticket_id, titulo, conteudo_md, metadados)` → `vault/Demandas/<YYYY>-<MM>-<slug-titulo>.md`
  - Frontmatter YAML: `ticket_id`, `data_criacao`, `agentes_envolvidos`, `status`, `repo`, `links` (wikilinks p/ agente, padrão do repo)
- `escrever_nota_agente(papel_agente, ticket_id, resumo)` → `vault/Agentes/<papel>/<ticket-id>-resumo.md`
- `listar_demandas(limite=20)` →últimas N demandas (por data no frontmatter)

Toda escrita usa **append atômico** com `tempfile.NamedTemporaryFile` + `os.replace()` para não corromper notas já abertas no Obsidian.

### 3.4 `harness/tools_skill_curator.py` — Curadoria automática de skills

**Apenas skills com `fonte_externa=True` entram nesse ciclo (4 skills):**
- `padrao-repositorio`, `modelagem-dados`, `checklist-lgpd`
- Observação: `revisao-cruzada`, `criterios-aceite`, `registro-vault` são internos — **nunca** passar pelo Curador.

**Passos do ciclo (Routine semanal do Curador):**

1. Para cada skill com fonte externa:
   - Baixar conteúdo atual da fonte (Reversa changelog, ANPD, etc.) via `httpx`
   - Computar `novo_hash = sha256(conteudo_baixado)`
   - Consultar `skill_curadoria_log` → último hash aprovado para essa skill
   - Se hash igual: pular (nada mudou)
2. Se hash diferente:
   - Prompt Groq: "Compare o SKILL.md atual com o novo conteúdo da fonte. Produza um novo SKILL.md atualizado, mantendo o formato interno e não inventando informação que não está na fonte."
   - Salvar em `interestelar/skills_pendentes/<nome>/SKILL.md`
   - Criar ticket no Paperclip (atribuído ao board / usuário humano):
     - Título: `[Skill Curadoria] Proposta de atualização: <nome>`
     - Descrição: Diff completo (old vs new) em bloco de diff markdown
     - Botão / link para `POST /aprovar-skill/<nome>` no harness
3. Endpoint `POST /aprovar-skill/{nome}` (webhook.py):
   - Valida se arquivo existe em `skills_pendentes/<nome>/`
   - Copia conteúdo para `skills/<nome>/SKILL.md` (overwrite)
   - Registra em `skill_curadoria_log` (`aprovada_em=NOW`, `aprovada_por='board'`)
   - Remove da pasta `skills_pendentes/`
   - Comenta no ticket de curadoria + fecha como `done`

---

## Fase 4 — Fluxo de Demanda e Harness de Revisão

### 4.1 Lógica do Head de Dados (roteamento dinâmico)

**Quando um ticket chega ao Head:**

1. Lê descrição + anexos (inclui padrão do repositório, se houver)
2. Prompt Groq classifica a demanda em uma ou mais categorias:
   - `[ESCOPO_PO]` — precisa de critérios de aceite
   - `[MODELAGEM]` — precisa de desenho do Arquiteto
   - `[IMPLEMENTACAO]` — precisa de Engenheiro
   - `[GOVERNANCA]` — precisa de conformidade LGPD/qualidade
   - `[ANALISE]` — precisa de análise de dados
   - `[COMPLETO]` — todas as etapas
3. Monta **plano de execução** (ordem dos agentes) — não é fixa:
   - Ex: só `IMPLEMENTACAO` → direto Engenheiro (sem passar por PO/Arquiteto)
   - Ex: `ESCOPO_PO + MODELAGEM + IMPLEMENTACAO + GOVERNANCA` → PO → Arquiteto → Governança → Engenheiro → Governança (final)
4. Armazena plano no primeiro comentário do ticket (tag `#PLANO:`)
5. Reatribui ao primeiro agente do plano

### 4.2 Lógica do agente genérico (todos menos Head)

1. Carrega identidade + skills
2. Identifica etapa do plano (lê comentário `#PLANO:` do Head)
3. Processa com LLM
4. **Fim da resposta — parse de flags:**
   - `REVISAO_NECESSARIA: <agente> | <motivo>` → problema fora da alçada
   - `ETAPA_CONCLUIDA` → etapa do plano cumprida
5. Se `REVISAO_NECESSARIA`:
   - **Chama `tools_memoria.incrementar_revisao(ticket_id, eu, agente_alvo)`**
     - Se lançar exceção (limite estourado): **não reatribui** → comenta "Limite de revisões excedido. Voltando para Head decisão humana." → atribui de volta ao Head
   - Reatribui direto ao agente alvo (não volta ao Head)
6. Se `ETAPA_CONCLUIDA`:
   - Lê plano do Head → vê qual é o próximo agente
   - Se existe próximo: reatribui → próximo
   - Se é o último do plano: reatribui → Head (para fechamento)

### 4.3 Fechamento pelo Head

1. Quando Head recebe ticket de volta do último agente:
2. Consolida todos os comentários em uma nota final
3. Chama `tools_obsidian.escrever_demanda(ticket_id, titulo, nota_final, metadados)`
4. Anexa arquivo `vault/Demandas/...md` como **work product** no ticket
5. Atualiza status do ticket → `done`
6. `tools_memoria.resetar_revisoes(ticket_id)`

---

## Fase 5 — Integração Paperclip: Agentes, Routines e Aprovações

### 5.1 Script de setup inicial (one-shot)

**Arquivo:** `interestelar/scripts/setup_paperclip.py`

Roda manualmente após `docker compose up`. Ele:

1. Cria Company (se não existir) via `POST /api/companies`
2. Registra **7 agentes HTTP** via `paperclip_client.criar_agente_http()`:
   - Head de Dados → `http://harness:8000/webhook/head`
   - PO de Dados → `http://harness:8000/webhook/po`
   - Arquiteto → `http://harness:8000/webhook/arquiteto`
   - Engenheiro → `http://harness:8000/webhook/engenheiro`
   - Governança → `http://harness:8000/webhook/governanca`
   - Analista → `http://harness:8000/webhook/analista`
   - Curador de Skills → `http://harness:8000/webhook/curador-skills`
3. Monta org chart:
   - Head no topo (reportsTo = null)
   - Outros 5 de demanda → reportsTo = Head
   - Curador → reportsTo = null ou Head (não participa de demandas, só Routine)
4. Importa 6 skills via Company Skills API (usa `paperclip_client` ou `POST /api/company-skills` — ler [services/company-skills.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/company-skills.ts) para contrato exato)
5. Cria Routine semanal do Curador:
   - Cron: `0 3 * * 1` (segunda-feira 03:00 UTC)
   - Agente atribuído: Curador de Skills
   - Descrição: "Verifica fontes externas de skills e propõe atualizações"
6. Cria projeto default "Demandas de Dados"

### 5.2 Governança como Approval Gate (opcional, fase avançada)

Na primeira versão, a Governança é só um agente que comenta. Depois, pode virar **aprovação formal** do Paperclip:

- Configurar que tickets marcados com label `governanca-requer-aprovacao` exigem approval do agente Governança antes de `done`
- Usa o Approval Gate nativo do Paperclip (ver [services/approvals.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/approvals.ts) e [routes/approvals.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/routes/approvals.ts))

---

## Fase 6 — Configuração de UI/UX no Core do Paperclip (Opcional, não bloqueante)

Estes são ajustes **no core do Paperclip** (`server/` e `ui/`) que melhoram a experiência do Interestelar, mas NÃO são obrigatórios para ele funcionar. Fazer apenas se houver tempo após o MVP.

| Item | Onde mexer | Descrição |
|---|---|---|
| Badge visual de "Revisão X/3" no ticket | [ui/src/components/IssueRow.tsx](file:///d:/orchestration-zero-humans/paperclip/ui/src/components/IssueRow.tsx) + campo custom no description ou metadata | Parseia `#REVISAO_ATUAL: x/3` no ticket e mostra barra de progresso |
| Link "Aprovar Skill" no ticket de curadoria | [ui/src/components/CommentThread.tsx](file:///d:/orchestration-zero-humans/paperclip/ui/src/components/CommentThread.tsx) | Detecta texto `[APROVAR SKILL: nome]` e renderiza botão POST para `/aprovar-skill` (configurado em environment do harness) |
| Label colorida "Interestelar" em tickets do fluxo | [packages/db/src/schema/labels.ts](file:///d:/orchestration-zero-humans/paperclip/packages/db/src/schema/labels.ts) + seed | Label roxa padrão criada pela company do Interestelar |
| Dashboard com card "Demandas do Interestelar" | [server/src/routes/dashboard.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/routes/dashboard.ts) + [ui/src/components/ActivityCharts.tsx](file:///d:/orchestration-zero-humans/paperclip/ui/src/components/ActivityCharts.tsx) | Filtro por projeto "Demandas de Dados" |

---

## Fase 7 — Testes e Validação Ponta-a-Ponta

### 7.1 Casos de teste obrigatórios

| Teste | Como validar |
|---|---|
| **Criação de ticket → Head roteia → PO responde → conclui** | Ticket de teste: "Criar escopo para pipeline de vendas". Verificar PO recebe, aplica `criterios-aceite`, marca `ETAPA_CONCLUIDA`, volta ao Head. |
| **Revisão cruzada com 1 ida e volta** | Arquiteto manda `REVISAO_NECESSARIA: governanca | LGPD de dados sensíveis`. Governança responde → volta ao Arquiteto. Contadores: `total=1`, `arquiteto->governanca=1` |
| **Limite de 2 idas e voltas entre mesmo par** | Forçar 3x arquiteto→governança. Na 3ª: harness bloqueia, volta ao Head, comenta sobre limite. |
| **Limite de 3 revisões totais** | Forçar 4 revisões aleatórias. Na 4ª: bloqueio geral. |
| **Curador de Skills — fluxo completo** | Mockar fonte externa com hash diferente → skill aparece em `skills_pendentes/` → ticket aberto → chamar `POST /aprovar-skill/nome` → skill move para `skills/` → log registrado. |
| **Fallback GitHub API** | Não configurar Reversa → rodar `obter_ou_gerar_padrao()` → confirmar cache salvo em SQLite e MD no vault. |
| **Work product anexado** | Fechar demanda → confirmar arquivo vault no ticket como attachment. |
| **Routine semanal do Curador dispara** | Mockar cron ou disparar manualmente a Routine via UI do Paperclip. |

### 7.2 Check de não-regressão do core do Paperclip

Depois de qualquer ajuste opcional da Fase 6:
```bash
pnpm -r typecheck
pnpm test:run
pnpm build
```

---

## Fase 8 — Documentação e Onboarding

**Nota: Estes arquivos só são criados SE o usuário explicitamente pedir documentação. Por enquanto ficam como placeholder.**

- `interestelar/README.md` — Como subir (docker compose up, setup_paperclip.py)
- `interestelar/TROUBLESHOOTING.md` — Problemas comuns: webhook não chega, Groq rate limit, cache SQLite expirado
- `interestelar/EXEMPLO_FLUXO.md` — Print/screenshot do primeiro ticket ponta-a-ponta

---

## Ordem de Implementação Recomendada (Prioridade)

| Ordem | Fase | Itens | Dependências |
|---|---|---|---|
| **1** | 0.1 + 0.2 | Estrutura de pastas + docker-compose + .env + Dockerfile | Nenhuma |
| **2** | 1.1 + 1.2 | `paperclip_client.py` + `webhook.py` (esqueleto vazio, só /health) | Fase 0 rodando |
| **3** | 3.1 + 3.3 | `tools_memoria.py` (SQLite init + tabelas) + `tools_obsidian.py` | Fase 2 |
| **4** | 2.1 + 2.2 | 7 identidades de agentes + 6 skills iniciais | Fase 0 |
| **5** | 1.2 (aprimorar) | Lógica de montagem de prompt + chamada Groq real em 1 endpoint (Head) | Fase 3, 4 |
| **6** | 4.1 + 4.2 + 4.3 | Fluxo Head roteamento + agente genérico + revisão + fechamento | Fase 5 + 3.1 |
| **7** | 3.2 | `tools_repo.py` com fallback GitHub API (sem Reversa ainda) | Fase 3.1 |
| **8** | 5.1 | Script `setup_paperclip.py` — cadastra 7 agentes, skills, Routine, projeto | Fase 7 + core rodando |
| **9** | 3.4 | Curador de Skills + endpoint `/aprovar-skill` | Fase 3.1 + 5.1 |
| **10** | 7 | Testes ponta-a-ponta dos 8 casos de teste | Tudo anterior |
| **11** | 6 (opcional) | Ajustes de UI no core do Paperclip | MVP funcionando |
| **12** | 5.2 (opcional) | Governança como Approval Gate real | Fase 11 ou posterior |

---

## Riscos e Mitigações

| Risco | Impacto | Mitigação |
|---|---|---|
| Endpoints `/api/agents`, `/api/issues` do Paperclip não batem com o estimado | **Alto** — quebra toda integração | Confirmar com `docs.paperclip.ing` ANTES de codar `paperclip_client.py`. Usar `GET /api/health` primeiro. Se incerto: criar cliente tipado a partir de OpenAPI se disponível. |
| Adapter `http` no Paperclip tem timeout < tempo do Groq | **Alto** — heartbeat falha | Já especificado: usar **202 Accepted + callback assíncrono**. Nunca responder sincronicamente. Ajustar `timeoutSec` no config do agente (300s recomendado). |
| Groq free tier tem rate limit rigoroso (RPM/TPD) | **Médio** — falhas intermitentes | Backoff exponencial (1s, 2s, 4s, 8s) + cache de prompts idênticos em Redis ou SQLite. Alternativa barata: chave OpenRouter. |
| Reversa requer Claude Code CLI autenticado (não gratuito) | **Baixo** — prompt prevê fallback | Implementar **primeiro** só o fallback GitHub/GitLab API. Reversa fica como feature flag (`REVERSA_CLAUDE_CODE_AUTH` vazio → pula). |
| Loop infinito de revisão (borda do harness) | **Alto** — consumo infinito de tokens | Dois níveis: (1) SQLite `incrementar_revisao` falha rápido. (2) Hard cap no webhook.py: se mesmo ticket recebeu > 10 heartbeats em < 5 min → pausa agente, requer intervenção board. |
| Cross-company access é bloqueado (confirmado) | **Informativo** | Já descartado no prompt. Não implementar Jarvis. Se necessário no futuro: Board API Key + iteração empresa-por-empresa. |

---

## Checkpoint de Aceitação do MVP

O Interestelar está "funcionando" quando:

1. ✅ `docker compose up` sobe Paperclip (3100) + Harness (8000) — ambos healthcheck OK
2. ✅ Script `setup_paperclip.py` executa sem erro: 7 agentes, org chart, 6 skills, 1 routine semanal
3. ✅ Criação manual de um ticket "Criar pipeline de ingestão de clientes do Salesforce" no Paperclip → atribuído ao Head
4. ✅ Head acorda, classifica em `ESCOPO_PO + MODELAGEM + IMPLEMENTACAO + GOVERNANCA`, comenta `#PLANO:`, atribui ao PO
5. ✅ PO acorda → aplica `criterios-aceite` → marca `ETAPA_CONCLUIDA` → atribui ao Arquiteto
6. ✅ Arquiteto acorda → lê padrão do repo (fallback GitHub) → manda `REVISAO_NECESSARIA: governanca | Contém CPF, precisa LGPD` → atribui direto
7. ✅ Governança acorda → responde com `checklist-lgpd` → `ETAPA_CONCLUIDA` → volta ao Arquiteto
8. ✅ Arquiteto acorda → `ETAPA_CONCLUIDA` → Engenheiro
9. ✅ Engenheiro acorda → `ETAPA_CONCLUIDA` → Head
10. ✅ Head fecha → nota no vault anexada como work product → status `done`
11. ✅ Tudo respeitou contadores (SQLite): `total_revisoes=1`, `arquiteto->governanca=1`

---

## Referências de Código no Core do Paperclip

Estes são os locais do core que o Interestelar consome via API / onde o adapter `http` vive — são referência para debug:

| Componente Paperclip | Caminho |
|---|---|
| Adapter HTTP server-side | [server/src/adapters/http/](file:///d:/orchestration-zero-humans/paperclip/server/src/adapters/http/) |
| Adapter HTTP UI-side | [ui/src/adapters/http/](file:///d:/orchestration-zero-humans/paperclip/ui/src/adapters/http/) |
| Execução do adapter HTTP | [server/src/adapters/http/execute.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/adapters/http/execute.ts) |
| Service de Heartbeat | [server/src/services/heartbeat.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/heartbeat.ts) |
| Service de Agentes | [server/src/services/agents.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/agents.ts) |
| Service de Issues/Tickets | [server/src/services/issues.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/issues.ts) |
| Service de Company Skills | [server/src/services/company-skills.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/company-skills.ts) |
| Service de Routines (scheduler) | [server/src/services/routines.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/routines.ts) |
| Service de Approvals | [server/src/services/approvals.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/approvals.ts) |
| Service de Work Products | [server/src/services/work-products.ts](file:///d:/orchestration-zero-humans/paperclip/server/src/services/work-products.ts) |
| Adapter type shared | [packages/shared/src/adapter-type.ts](file:///d:/orchestration-zero-humans/paperclip/packages/shared/src/adapter-type.ts) |
| Db Schema agents/issues | [packages/db/src/schema/](file:///d:/orchestration-zero-humans/paperclip/packages/db/src/schema/) |
| Docker compose core | [docker/docker-compose.yml](file:///d:/orchestration-zero-humans/paperclip/docker/docker-compose.yml) |
