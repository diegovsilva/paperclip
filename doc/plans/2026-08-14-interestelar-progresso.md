# Progresso: Implementação Interestelar

> Início: 2026-08-14
> Última atualização: 2026-08-17

---

## Resumo Geral

| Fase | Status | Itens concluídos | Última atualização |
|---|---|---|---|
| 0 — Scaffolding | Concluída | Estrutura de diretórios (20 pastas), requirements.txt, .env.example, Dockerfile, docker-compose.yml | 2026-08-14 |
| 1 — Harness (cliente + webhook esqueleto) | Concluída | paperclip_client.py (23 métodos), config.py, logging_setup.py, webhook.py (9 endpoints) | 2026-08-14 |
| 2 — Identidade & Skills | Concluída | 7 agentes (21 arquivos identidade) + 6 SKILL.md | 2026-08-14 |
| 3 — Tools (memória, obsidian, repo, curador) | Concluída | tools_memoria.py (SQLite + harness de revisão), tools_obsidian.py (escrita atômica), tools_repo.py (fallbacks Reversa→GitHub→GitLab→local), tools_skill_curator.py (ciclo semanal) | 2026-08-14 |
| 4 — Fluxo de demanda & harness de revisão | Concluída | engine_prompt.py (monta prompt + chama Groq com retry), webhook.py (v0.2 — Head roteamento, agente genérico, atribuição automática, fechamento Head, contadores de revisão, loop protection duplo) | 2026-08-14 |
| 5 — Integração Paperclip (setup script) | Concluída e validada contra o real | scripts/setup_paperclip.py rodado com sucesso (100% HTTP 200/201) contra Paperclip real: company + 7 agentes + projeto + 2 labels + 6 skills + routine/trigger | 2026-08-17 |
| 6 — UI opcional | Pendente | — | — |
| 7 — Testes ponta-a-ponta | MVP validado de ponta a ponta contra ambiente real, incidente real corrigido | 30 testes automatizados (pytest); 9 bugs de contrato de API + 2 bugs de roteamento + 3 bugs de concorrência corrigidos (incl. loop do próprio aviso de loop, achado em produção); provider de LLM dinâmico (`harness/llm_client.py`, Groq/OpenAI/Anthropic); `start.sh`/`start.ps1` criados; `docker compose` + bootstrap + `setup_paperclip.py` + fluxo de demanda, tudo validado contra o Paperclip real rodando. | 2026-08-17 |

---

## Registro de Execução

### 2026-08-14 — Início

- Roadmap aprovado: [2026-08-14-interestelar-roadmap.md](file:///d:/orchestration-zero-humans/paperclip/doc/plans/2026-08-14-interestelar-roadmap.md)
- Criação deste doc de progresso
- Início Fase 0

### 2026-08-14 — Fase 0 Concluída

**Criados:**
- Estrutura de diretórios: `interestelar/` com `harness/`, `agents/{head,po,arquiteto,engenheiro,governanca,analista,curador-skills}/`, `skills/{revisao-cruzada,criterios-aceite,registro-vault,padrao-repositorio,modelagem-dados,checklist-lgpd}/`, `skills_pendentes/`, `repositorios/`, `vault/{Agentes,Demandas}/`, `db/`, `scripts/`
- [interestelar/requirements.txt](file:///d:/orchestration-zero-humans/paperclip/interestelar/requirements.txt) — FastAPI, Groq, httpx, aiosqlite, PyGithub, python-gitlab, GitPython, structlog
- [interestelar/.env.example](file:///d:/orchestration-zero-humans/paperclip/interestelar/.env.example) — 14 variáveis (Groq, Paperclip, GitHub/GitLab, Reversa, Harness, paths, log)
- [interestelar/Dockerfile](file:///d:/orchestration-zero-humans/paperclip/interestelar/Dockerfile) — Python 3.12-slim, healthcheck curl /health, entrypoint uvicorn
- [interestelar/docker-compose.yml](file:///d:/orchestration-zero-humans/paperclip/interestelar/docker-compose.yml) — serviços `db` (postgres 17), `paperclip` (build do core, healthcheck api/health 60s start_period), `harness` (depends_on paperclip healthy, volumes vault/repositorios/db montados, skills/agents read-only)

**Observações:**
- Adapter `http` já existe no core Paperclip em [server/src/adapters/http/](file:///d:/orchestration-zero-humans/paperclip/server/src/adapters/http/) — não precisa implementar
- Schemas confirmados via `@paperclip/shared`: `createAgentSchema` (name, role, reportsTo, adapterType="http", adapterConfig={url, timeoutSec}), `createIssueSchema` (title, description, assigneeAgentId, projectId), `addIssueCommentSchema` (body)

### 2026-08-14 — Fase 1 (esqueleto) Concluída

**Criados:**
- [harness/config.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/config.py) — `Settings` via pydantic-settings com 25 variáveis (Groq, Paperclip, GitHub/GitLab, Reversa, Harness, paths, limites harness de revisão, loop protection) + `get_settings()` com `lru_cache`
- [harness/logging_setup.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/logging_setup.py) — structlog JSON/Console renderer conforme log_level
- [harness/paperclip_client.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/paperclip_client.py) — `PaperclipClient` async httpx com **23 métodos**:
  - Companies: `health`, `list_companies`, `create_company`, `get_company`
  - Agents: `list_agents`, `create_agent_http` (adapterType="http", url + timeoutSec), `update_agent`, `create_agent_api_key`, `wakeup_agent`
  - Issues: `list_issues`, `create_issue`, `get_issue`, `update_issue`, `assign_issue`, `add_comment`, `list_comments`, `create_work_product`, `list_work_products`, `get_issue_heartbeat_context`, `upload_attachment`
  - Heartbeat: `callback_heartbeat_run(run_id, "completed|failed|cancelled", result)`
  - Projects: `list_projects`, `create_project`
  - Routines: `list_routines`, `create_routine` (scheduleCron + assigneeAgentId)
  - Labels: `list_labels`, `create_label`
  - Company Skills: `list_company_skills`, `import_company_skill_file`
- [harness/webhook.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/webhook.py) — **FastAPI app com 9 endpoints:**
  - `GET /health` → status + vaultReady/reposReady
  - `POST /webhook/{head,po,arquiteto,engenheiro,governanca,analista,curador-skills}` → **202 Accepted imediato** + `BackgroundTasks` (não bloqueia Paperclip). Cada rota:
    1. Verifica assinatura HMAC-SHA256 do `X-Webhook-Secret` (se configurado)
    2. Hard loop protection: se mesmo `issueId` receber > 10 heartbeats em < 5 min → **falha rápido**, callback "failed", comenta no ticket pedindo intervenção humana
    3. `_load_identity_files(agent_slug)` → lê `SOUL.md / AGENTS.md / HEARTBEAT.md` da pasta `agents/<slug>/` (ainda vazios)
    4. Placeholder: callback com "completed" + mensagem placeholder
  - `POST /aprovar-skill/{nome}` → move `skills_pendentes/<nome>/SKILL.md` → `skills/<nome>/SKILL.md` (princípio 2 do prompt: nunca aplica skill externa sem aprovação humana)
- Helpers já embutidos no webhook: `_detect_review_flag()` (parseia `REVISAO_NECESSARIA: agente | motivo`), `_detect_stage_complete()` (detecta `ETAPA_CONCLUIDA`)

**Endpoints do Paperclip confirmados via código do core:**
- `POST /api/companies` → create company
- `POST /api/companies/:companyId/agents` → create agent (validado por `createAgentSchema`)
- `POST /api/companies/:companyId/issues` → create issue (validado por `createIssueSchema`)
- `GET /api/companies/:companyId/routines` + `POST /api/companies/:companyId/routines` → Routines (scheduler nativo do Paperclip)
- `POST /api/issues/:id/comments` → comentário (validado por `addIssueCommentSchema`)
- `POST /api/issues/:id/work-products` → work product
- `PATCH /api/issues/:id` → atribuição / mudança de status
- `PATCH /api/agents/:id` → update agent / reportsTo (org chart)

### 2026-08-14 — Fase 2 Concluída (Identidade + Skills)

**Identidades criadas (21 arquivos em [agents/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/)):**

Pasta por agente, trinca `SOUL.md` (persona/voz) + `AGENTS.md` (papel/segurança/skills) + `HEARTBEAT.md` (checklist passo-a-passo):
- [head/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/head/) — Roteador. Checklist: classifica demanda em `[ESCOPO_PO]/[MODELAGEM]/[IMPLEMENTACAO]/[GOVERNANCA]/[ANALISE]`, gera `#PLANO:` (ordem variável), reatribui. Fechamento → vault + work product.
- [po/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/po/) — Escopo SMART. Output: Contexto + 5-12 Critérios de Aceite + Fora de Escopo (mínimo 3) → `ETAPA_CONCLUIDA`. Gatilho LGPD sinaliza REVISAO_NECESSARIA.
- [arquiteto/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/arquiteto/) — 5 seções de desenho: Visão Geral, Dicionário de Dados, Estratégia de Carga, Qualidade, Aderência ao Padrão. Desvio do padrão tem que ser justificado.
- [engenheiro/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/engenheiro/) — 5 passos: branch, DDL, transformações/DAG, testes, docs de operação. Segue rigorosamente `padrao-repositorio`.
- [governanca/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/governanca/) — Inventário de dados pessoais + 10 itens checklist LGPD → classifica Risco BAIXO/MÉDIO/ALTO → APROVADO / APROVADO COM RESSALVAS / NÃO APROVADO.
- [analista/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/analista/) — Output padrão (resumo executivo, metodologia, resultados tabela+mermaid, limitações).
- [curador-skills/](file:///d:/orchestration-zero-humans/paperclip/interestelar/agents/curador-skills/) — Só Routine semanal. 3 skills monitoradas; NUNCA escreve em `skills/`, só `skills_pendentes/`; só humano move.

**Skills criadas (6 em [skills/](file:///d:/orchestration-zero-humans/paperclip/interestelar/skills/)):**
- [revisao-cruzada/SKILL.md](file:///d:/orchestration-zero-humans/paperclip/interestelar/skills/revisao-cruzada/SKILL.md) — Protocolo completo REVISAO_NECESSARIA. Slugs válidos, limites 3 total/2 por par, Head como escape.
- [criterios-aceite/SKILL.md](file:///d:/orchestration-zero-humans/paperclip/interestelar/skills/criterios-aceite/SKILL.md) — Estrutura fixa Contexto/CA/Fora Escopo, regras SMART, checklist de qualidade.
- [registro-vault/SKILL.md](file:///d:/orchestration-zero-humans/paperclip/interestelar/skills/registro-vault/SKILL.md) — Estrutura vault, YAML frontmatter OBRIGATÓRIO, escrita atômica, wikilinks.
- [padrao-repositorio/SKILL.md](file:///d:/orchestration-zero-humans/paperclip/interestelar/skills/padrao-repositorio/SKILL.md) — 10 seções obrigatórias (stack → exemplos), regras de desvio do padrão com bloco justificativa, TTL cache 7 dias.
- [modelagem-dados/SKILL.md](file:///d:/orchestration-zero-humans/paperclip/interestelar/skills/modelagem-dados/SKILL.md) — Star/Data Vault/Wide, quando usar qual. Checklist 10 itens. Exemplo de dicionário completo f_vendas + dimensões.
- [checklist-lgpd/SKILL.md](file:///d:/orchestration-zero-humans/paperclip/interestelar/skills/checklist-lgpd/SKILL.md) — Inventário obrigatório → 10 itens (mapeamento → incidentes) → Matriz BAIXO/MÉDIO/ALTO + formato OBRIGATÓRIO de resposta.

### 2026-08-14 — Fase 3 Concluída (Quatro módulos Tools)

**[tools_memoria.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/tools_memoria.py) SQLite sidecar**

Esquema com 3 tabelas + 2 índices:
- `repo_pattern_cache(slug_empresa PK, pattern_md, source, hash_content, obtido_em, expira_em)` — TTL configurável padrão 7 dias.
- `ticket_revisoes(ticket_id PK, total_revisoes, par_revisoes_json)` — Harness de revisão. `incrementar_revisao(tid, de, para)` lança **`ReviewLimitError`** quando: total > `max_review_total` (default 3) OU ida/volta par > `max_review_per_pair` (default 2). Contadores de par são simétricos (`min(a,b)->max(a,b)`). Head é bypassado.
- `skill_curadoria_log(id PK, skill_nome UNIQUE, fonte_hash, proposta_em, aprovada_em, aprovada_por)` — log do Curador.

Funções públicas: `obter_padrao_repo`, `salvar_padrao_repo`, `invalidar_padrao_repo`, `obter_estado_revisoes`, `incrementar_revisao`, `resetar_revisoes`, `registrar_proposta_skill`, `obter_ultimo_hash_skill_aprovado`, `marcar_skill_aprovada`, `hash_conteudo`.

**[tools_obsidian.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/tools_obsidian.py) Escrita atômica vault**

- `_atomic_write(path, content)` → `tempfile.mkstemp` + `fsync` + `os.replace` (não corrompe notas abertas no Obsidian).
- `_yaml_frontmatter(metadata, body)` + `_slugify` (acentos→sem-acentos).
- Funções públicas:
  - `escrever_padrao_repo(slug, md)` → append por empresa em `vault/Padrão do Repositório.md`.
  - `escrever_demanda(ticket_id, titulo, md, meta)` → `vault/Demandas/YYYY-MM-slug.md` com frontmatter completo.
  - `escrever_nota_agente(papel, ticket, titulo, resumo, repo)` → `vault/Agentes/<Papel>/<id>-slug.md`.
  - `listar_demandas(n=20)` → últimas N por mtime.

**[tools_repo.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/tools_repo.py) Detecção padrão 4-estratégia**

Prioridades (Reversa flag opcional → GitHub Tree API → GitLab Tree API → local + Groq):
- `garantir_repo_local(slug, url, auth?)` — `git pull` ou clone com token `oauth2:`.
- `garantir_repo_submodulo(slug, url)` — `git submodule add`, fallback clone.
- `obter_ou_gerar_padrao(slug, url, priority?)` — cache first. Gera markdown 10 seções via prompt Groq e snapshot de arquivos chave (Dockerfile, dbt_project.yml, workflows, models/, dags/, etc.).
- `obter_ou_gerar_padrao_e_escrever_vault(...)` — helper que já escreve no Obsidian.
- `hash_conteudo_fonte` → sha256 para o Curador.

**[tools_skill_curator.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/tools_skill_curator.py) Ciclo semanal**

- `MANAGED_EXTERNAL_SKILLS` = `padrao-repositorio` (Reversa GH), `modelagem-dados` (dbt docs), `checklist-lgpd` (ANPD). Skills internas `revisao-cruzada | criterios-aceite | registro-vault` **NÃO ENTRAM**.
- Fluxo por skill: baixa fontes → `hash_conteudo` → compara com `obter_ultimo_hash_skill_aprovado` → igual=skip; diferente → prompt Groq "atualize só o que a fonte justifica, mantendo estrutura" → salva em `skills_pendentes/<nome>/SKILL.md` → registra log proposta → **abre ticket no Paperclip pro Board com diff unified completo** + link POST para `/aprovar-skill/nome`.
- Função principal:- `executar_ciclo_curadoria(client?, skills?) -> dict[skill: bool_atualizada]`.

### 2026-08-14 — Fase 4 Concluída (Fluxo completo + Groq real)

**[harness/engine_prompt.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/engine_prompt.py) — Engine LLM**

- `SKILLS_POR_AGENTE` + `AGENT_LABELS` (7 slugs mapeados).
- `AgentInput` dataclass: agent_slug, ticket_id/title/description/status/priority, comments_history tuples (autor,ts,body), pattern_md, extra_context, previous_review_total, previous_review_par.
- `AgentOutput` dataclass: raw_text, review (alvo,motivo) opcional, stage_complete (bool), plan (list[str] opcional do #PLANO).
- `_montar_prompt(inp) -> system, user`:
  - System: SOUL + AGENTS + HEARTBEAT + SKILLS_RELEVANTES (apenas as do agente)
  - User: ticket completo + últimos 50 comentários + padrão do repo + contexto extra + **CONTADORES DE REVISÃO (3 total / 2 par)** + instrução final sintaxe REVISAO_NECESSARIA / ETAPA_CONCLUIDA / #PLANO.
- `_parse_output(text)`: regex REVISAO_NECESSARIA (alvo|motivo), STAGE_COMPLETE_RE, PLAN_LINE_RE (extrai tokens de agentes válidos).
- `_groq_chat_completion(system, user, retries=3)`: retry com backoff exponencial em `RateLimitError` / `InternalServerError` (1.2s, 2.4s, 4.8s...).
- `executar_agente(inp) -> AgentOutput`: monta prompt → roda Groq → parseia → log estruturado.

**[harness/webhook.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/webhook.py) v0.2 (reescrito completo)**

Principais adições (comparado ao esqueleto v0.1):
- `lifespan` agora roda `mem.init_db()` no startup.
- `_extract_plan_from_text`: extrai sequência `#PLANO: HEAD → PO → ...` da descrição ou comentários anteriores.
- `_proximo_agente_do_plano(plano, agente_atual)`: navega a sequência. Se último, volta None → Head fecha.
- `_encontrar_agente_id_por_slug(client, company_id, slug)`: resolve nome do agente → id no Paperclip (procura por "Head de Dados", "PO de Dados" ou por metadata `interestelar_slug`).
- `_carregar_padrao_do_contexto(issue_data)`: injeta padrão do repo direto do description se o Head colocou lá.
- `_montar_comentario_contadores`: escreve `#REVISAO_ATUAL: N/3` + contagem por par em comentário separado a cada heartbeat.
- `_resumo_para_vault` + `obs.escrever_nota_agente`: **toda** contribuição de agente vira nota em `vault/Agentes/<Papel>/...md`.
- `_finalizar_como_head`: consolida todos os comentários → `vault/Demandas/YYYY-MM-slug.md` com YAML frontmatter completo → cria `work_product` → faz **upload do .md como attachment** do ticket → status `done` → `mem.resetar_revisoes`.
- `_process_demanda_agent` (fluxo central):
  1. Lê ticket + últimos 50 comentários
  2. Carrega padrão do repo (se veio na description) + estado revisões
  3. Roda `executar_agente` (Groq real)
  4. Comenta resposta no Paperclip
  5. Escreve nota do agente no vault
  6. Recupera plano (do output LLM → do Head → da description)
  7. Escreve comentário contadores
  8. Se REVISAO_NECESSARIA: incrementa contador → se ReviewLimitError volta pro Head; senão atribui direto ao alvo (**não volta pelo Head**, como especificado no prompt §4.2)
  9. Se ETAPA_CONCLUIDA: Head atribui plan[0]; agente comum atribui plan[proximo] ou Head (se último do plano)
  10. Se fim de plano detectado → `_finalizar_como_head`
  11. Atribuição automática → muda status `backlog/todo` → `in_progress`
- `_process_curador`: aciona `tools_skill_curator.executar_ciclo_curadoria()` → baixa fontes, compara hash, propõe skill em skills_pendentes, abre ticket pro Board com diff.
- Dupla proteção contra loops: (1) `_check_loop_protection` memória (10 heartbeats em <5 min → falha + pede humano), (2) harness SQLite 3/2 — qualquer excessão vira ReviewLimitError.
- `aprovar-skill/{nome}` agora também roda `mem.marcar_skill_aprovada` (atualiza log de curadoria, garante que próximo ciclo não re-proponha a mesma versão).

### 2026-08-14 — Fase 5.1 Concluída (Setup one-shot)

**[scripts/setup_paperclip.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/scripts/setup_paperclip.py)**

Script CLI idempotente. Uso:
```bash
cd interestelar
python scripts/setup_paperclip.py \
  --company-name "Minha Empresa" \
  --harness-public-base "http://localhost:8000"
```

O que faz:
1. **Company** — `create_company` / acha existente por nome.
2. **7 agentes HTTP** na ordem correta para respeitar `reports_to`:
   - Head (topo, reportsTo=null)
   - PO / Arquiteto / Engenheiro / Governança / Analista (reportsTo → Head)
   - Curador de Skills (reportsTo=null, não participa do ciclo de demanda)
   Cada agente recebe metadata `interestelar_slug=<slug>` + icon emoji + webhook `http://<harness-host>/webhook/<slug>` + timeout `harness_agent_timeout_sec`.
3. **Projeto default** "Demandas de Dados — Interestelar" (cria ou reutiliza por nome).
4. **Labels** `Interestelar` (roxa #7c3aed) + `LGPD` (azul #2563eb).
5. **6 Company Skills** importadas via `import_company_skill_file` (ler SKILL.md local → payload key/slug/name/sourceType=inline/trustLevel=trusted/compatibility/files).
6. **Routine semanal** do Curador: cron `0 3 * * 1` (segunda 03:00 UTC), assigned_task_template já com título/descrição/prioridade baixa.
7. **Args extras**: `--skip-skills`, `--skip-routine`, `--company-id` (força company existente).
8. **Output final**: company_id + projeto ID + routine ID + tabela slug→id de 7 agentes + IDs das labels.

Depois deste setup, basta criar um ticket no Paperclip (Board) atribuído ao **Head de Dados** e o Interestelar começa.

### 2026-08-17 — Fase 7 iniciada: testes revelaram 8 bugs reais de integração (todos corrigidos)

Ao montar os testes automatizados, comparei cada endpoint que `paperclip_client.py` chama
contra o código real do core (`server/src/routes/*.ts` + Zod schemas em
`packages/shared/src/validators/*.ts`) em vez de assumir que o contrato estimado no
roadmap estava certo. Isso confirmou exatamente o risco "Alto" já sinalizado no roadmap
("Endpoints do Paperclip não batem com o estimado") — 8 problemas reais, todos corrigidos:

1. **Erro de sintaxe em `tools_memoria.py`** (`obter_padrao_repo`) — parêntese de
   `db.execute(...)` nunca fechava. O módulo inteiro não importava (`SyntaxError`).
2. **Erro de indentação em `paperclip_client.py`** (`_request`) — `return r.json()`
   ficava dentro do `if`, tornando código morto/inacessível.
3. **`GROQ_MODEL` apontava para `llama-3.1-70b-versatile`**, modelo descontinuado pela
   Groq — todas as chamadas ao LLM falhariam. Trocado para `llama-3.3-70b-versatile`.
4. **`companyId` nunca chega no payload do webhook.** O adapter `http` do core
   (`server/src/adapters/http/execute.ts`) monta o body como
   `{...payloadTemplate, agentId, runId, context}` — sem `companyId` top-level. Como
   `HeartbeatPayload.companyId` era obrigatório no Pydantic, **todo heartbeat real
   receberia 422** antes mesmo de chegar na lógica do agente. Corrigido em duas frentes:
   `create_agent_http` agora injeta `payloadTemplate: {companyId}` no `adapterConfig`,
   e `webhook.py` ganhou fallback via `PAPERCLIP_COMPANY_ID` do `.env`.
5. **`wakeReason` com `Literal` restrito demais** — o core dispara dezenas de motivos
   internos (`missing_issue_comment`, `process_lost_retry`, `on_demand`, ...) fora da
   lista otimista do harness; qualquer um deles também geraria 422. Relaxado para `str`.
6. **`POST /heartbeat-runs/:runId/callback` não existe no core** (confirmado — sem essa
   rota em `agents.ts`). `callback_heartbeat_run` agora é best-effort
   (`_safe_callback_heartbeat`): loga em debug e nunca derruba o processamento, já que o
   resultado real da demanda (comentários/reatribuição/status/vault) é persistido via
   API antes dessa chamada.
7. **Import de Company Skills usava o endpoint errado.** `POST /companies/:id/skills/import`
   (`companySkillImportSchema`) só aceita `{source: string}` — é pra importar de uma URL
   externa, não pra markdown que já temos. Trocado para `POST /companies/:id/skills`
   (`companySkillCreateSchema`: `{name, slug, description, markdown}`), que é o endpoint
   de criação local de fato usado pelo Curador de Skills.
8. **`create_agent_http`/`setup_paperclip.py` com valores fora dos enums reais:**
   `role` usava `"coder"/"data_engineer"/"security_engineer"/"data_scientist"` — não
   existem em `AGENT_ROLES` (só `ceo/cto/cmo/cfo/security/engineer/designer/pm/qa/devops/
   researcher/general`). `icon` usava emoji cru — o schema exige um slug nomeado de
   `AGENT_ICON_NAMES` (`"radar"`, `"shield"`, etc., não `"🛡️"`). Ambos causariam 400 em
   4 dos 7 agentes. Corrigido o mapeamento completo.
9. **`create_routine`/`create_work_product` com schema inventado.** `createRoutineSchema`
   real usa `title` (não `name`), não tem `scheduleCron` nem `assignedTaskTemplate` — o
   cron é criado à parte via `POST /routines/:id/triggers`
   (`{kind:"schedule", cronExpression, timezone}`), só possível depois que a routine já
   existe. `createIssueWorkProductSchema` exige `type` (enum) + `provider` (obrigatório)
   e não tem `body`/`kind` — o texto vai em `summary`. `paperclip_client.py` ganhou
   `create_routine_trigger()` novo; `setup_paperclip.py` e `_finalizar_como_head` foram
   ajustados para os payloads corretos.

**Bug de lógica de orquestração encontrado ao montar o cenário de teste (não é de
contrato de API):** quando um agente que TAMBÉM aparece no `#PLANO:` principal (ex.
Governança) termina de responder a uma `REVISAO_NECESSARIA` ad-hoc, o código antigo
não sabia distinguir "terminei minha etapa oficial do plano" de "terminei de responder
uma revisão avulsa" — em ambos os casos só existe o sinal `ETAPA_CONCLUIDA`. Resultado:
o controle era roteado para o PRÓXIMO passo do plano (ou, se o revisor nem estivesse no
plano, para `plano[0]` — o começo!) em vez de voltar para quem pediu a revisão, quebrando
o protocolo de `revisao-cruzada` descrito no roadmap (§4.2) e na skill correspondente.

Corrigido com uma **pilha de "retorno pendente"** em `tools_memoria.py`
(`definir_retorno_pendente` / `obter_e_limpar_retorno_pendente`, tabela
`ticket_revisoes.retorno_pendente_pilha_json`): ao disparar `REVISAO_NECESSARIA`,
empilha `{alvo, retornar_para}`; quando o alvo conclui, se ele é o topo da pilha,
desempilha e volta para quem pediu — senão cai no roteamento normal por `#PLANO:`. É
pilha (não slot único) para aguentar revisão-dentro-de-revisão (A pede a B, B pede a C
→ C volta pra B, só depois B volta pra A). Validado com teste de regressão dedicado que
comprova o bug reaparece se a correção for desligada (roteava incorretamente para "po").

**Suíte de testes criada** (`interestelar/tests/`, pytest + pytest-asyncio,
`asyncio_mode=auto` via `pytest.ini`, sem chamar Groq/Paperclip real):
- [tests/test_tools_memoria.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/tests/test_tools_memoria.py) — 12 testes: limite 3 total / 2 por par (com bloqueio confirmado via `pytest.raises`), contadores por ticket isolados, reset ao fechar, cache de padrão de repo com TTL/expiração, pilha de retorno pendente (simples e aninhada), hash roundtrip da curadoria de skills.
- [tests/test_engine_prompt.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/tests/test_engine_prompt.py) — 7 testes: parsing de `REVISAO_NECESSARIA`/`ETAPA_CONCLUIDA`/`#PLANO:`, rejeição de slug de agente inválido.
- [tests/test_webhook_flow_e2e.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/tests/test_webhook_flow_e2e.py) — 2 testes com `FakeClient` em memória + `executar_agente` mockado: fluxo completo Head→PO→Arquiteto→(revisão Governança, retorno correto)→Arquiteto→Engenheiro→Head fecha (grava vault real em `tmp_path`, cria work product, anexa attachment, status `done`); e bloqueio ao estourar limite de revisão por par, devolvendo ao Head.
- `tests/conftest.py` — fixture `isolated_settings` isola SQLite/vault/repositorios em `tmp_path` por teste e limpa o cache do `get_settings()` (padrão `@lru_cache` usado em todo o harness).
- `pytest.ini` + `requirements-dev.txt` (`pytest`, `pytest-asyncio` sobre `requirements.txt`).
- `interestelar/.gitignore` novo (não existia) — cobre `.venv*/`, `__pycache__/`, `db/*.db`, conteúdo gerado do vault, repos clonados e skills pendentes.

**Resultado:** `pytest` → **21 passed**. Todos os módulos do `harness/` e o
`scripts/setup_paperclip.py` importam sem erro (antes, 2 deles nem importavam por erro
de sintaxe).

**Ainda faltando na Fase 7** (não coberto pelos testes acima, exige ambiente real):
- ~~Rodar contra uma instância real do Paperclip~~ **Feito em 2026-08-17** — ver seção abaixo.
- Caso de teste "Curador de Skills — fluxo completo" (mock de fonte externa →
  `skills_pendentes/` → ticket → `POST /aprovar-skill/nome` → `skills/`).
- Caso de teste "Fallback GitHub API" (`tools_repo.obter_ou_gerar_padrao`).
- Caso de teste "Routine semanal dispara" (exige o scheduler nativo do Paperclip rodando,
  agora que `create_routine`/`create_routine_trigger` foram corrigidos — ainda não testado
  contra o real, só o `create_routine` chegou a ser exercitado via `setup_paperclip.py`).
- Não fiz uma auditoria linha-a-linha de *todo* método de `paperclip_client.py` contra o
  schema real — cobri os que o fluxo principal (`webhook.py` + `setup_paperclip.py`)
  realmente usa. `create_agent_api_key`, `wakeup_agent`, `list_*`, `create_label` foram
  conferidos e batem; os métodos de `secrets`/`heartbeat_context` citados no roadmap
  original nem chegaram a ser implementados no client (não são usados no fluxo atual).

### 2026-08-17 — Scripts de start (`start.sh`/`start.ps1`) + validação contra ambiente real

**Criados** [start.sh](file:///d:/orchestration-zero-humans/paperclip/interestelar/start.sh) e
[start.ps1](file:///d:/orchestration-zero-humans/paperclip/interestelar/start.ps1) — sobem o
`docker compose` (build + wait de health + URLs), com subcomandos `setup` (roda
`setup_paperclip.py` dentro do container), `stop`, `restart`, `logs`, `status`. Ambos geram
`.env` a partir do `.env.example` na primeira vez e um `BETTER_AUTH_SECRET` aleatório
automaticamente (é obrigatório no compose e travava o `up` se vazio).

**Rodei os dois de verdade** (Docker Desktop estava disponível e o usuário autorizou
explicitamente rodar). Isso expôs mais gaps reais, todos corrigidos:

1. **`scripts/docker-entrypoint.sh` (Dockerfile raiz do Paperclip, fora do `interestelar/`)
   tinha CRLF** por causa de `core.autocrlf=true` no Windows — quebra o shebang `#!/bin/sh`
   dentro do container Linux (`exec ...: no such file or directory`). Não havia
   `.gitattributes` no repo. Criado [.gitattributes](file:///d:/orchestration-zero-humans/paperclip/.gitattributes)
   na raiz forçando LF em `*.sh`/`Dockerfile*` independente do checkout, e normalizado o
   arquivo já afetado no working tree (sem commitar).
2. **Healthcheck do Postgres (`db`) demorou mais que os 30 retries × 2s configurados**
   no primeiro start a frio no Docker Desktop/Windows — não é bug de código, só lento;
   documentado aqui como algo a esperar (o script de start já reporta e sugere `status`/`logs`
   se isso acontecer; não mudei o healthcheck em si porque não é determinístico o quanto
   demora, aumentar retries só empurra o problema).
3. **`paperclip_client.py` quebrava com `httpx.LocalProtocolError: Illegal header value
   b'Bearer '`** sempre que `PAPERCLIP_API_KEY` está vazio (`Authorization: Bearer `
   com espaço sobrando é header HTTP inválido) — mascarava o que deveria ser um 401 claro
   do servidor. `_headers()` agora só inclui `Authorization` quando `api_key` não é vazio.
4. **`PAPERCLIP_ALLOWED_HOSTNAMES` não configurado** — em modo `authenticated`+`private`
   (usado pelo compose), o middleware `private-hostname-guard.ts` do core bloqueia (403)
   qualquer `Host` header fora de `localhost`/`127.0.0.1`/hostnames explicitamente
   liberados. Como o harness chama `http://paperclip:3100` (hostname interno do docker
   network), toda chamada do harness caía nisso. Adicionado
   `PAPERCLIP_ALLOWED_HOSTNAMES: "paperclip"` ao serviço `paperclip` no
   [docker-compose.yml](file:///d:/orchestration-zero-humans/paperclip/interestelar/docker-compose.yml).
5. **`docker compose up -d --build <serviço>` não recria o container automaticamente**
   mesmo com uma imagem nova buildada (observado empiricamente — o container continuou
   rodando a imagem antiga até um `--force-recreate` explícito). Não é bug do Interestelar,
   é comportamento do Compose neste ambiente — documentado aqui porque quem for iterar
   localmente vai esbarrar nisso: depois de mudar código do harness, use
   `docker compose up -d --force-recreate --no-deps harness` se `--build` sozinho não
   parecer surtir efeito.

**Resultado final:** `paperclip` (healthy) e `harness` (healthy, `vaultReady: true,
reposReady: true`) sobem e se comunicam corretamente na rede docker. Rodei
`setup_paperclip.py` de dentro do container `harness` contra o Paperclip real e ele avançou
até `GET /api/companies` retornar `403 Board access required` — ou seja, todos os fixes de
schema/payload da sessão anterior (agents, issues, routines, skills, work-products) nunca
chegaram a ser exercitados porque o pipeline quebrava antes, em três camadas diferentes
(header HTTP inválido → hostname bloqueado → agora autenticação). O bloqueio atual é
**esperado e correto**: o Paperclip está com `bootstrapStatus: bootstrap_pending` — precisa
que um humano complete o bootstrap (criar a conta admin/board) pela UI em
`http://localhost:3100` e gere uma API key de Board pra colocar em `PAPERCLIP_API_KEY` no
`.env` antes do `setup_paperclip.py` conseguir criar company/agentes/skills/routine de
verdade. Isso não dá pra automatizar sem decisão humana (usuário, senha, etc.) — é o
próximo passo manual.

### 2026-08-17 — Bootstrap completo + `setup_paperclip.py` validado 100% contra o Paperclip real

Diego completou o bootstrap (conta admin) e aprovou um desafio de auth (equivalente ao
`paperclip auth login`) que gerei via `POST /api/cli-auth/challenges` — não existe botão de
"gerar API key" nas configurações; o fluxo real é: criar o desafio (retorna
`approvalUrl` + `boardApiToken` já pré-gerado) → usuário aprova logado no navegador →
o `boardApiToken` vira uma Board API key válida. Configurei em `PAPERCLIP_API_KEY` no
`.env` e recriei o container do harness (`docker compose restart` **não** recarrega
env vars — precisa `up -d --force-recreate --no-deps harness`).

Rodei `setup_paperclip.py --company-name "Interestelar Teste"` de dentro do container
harness contra o Paperclip real. **Resultado: sucesso completo, toda chamada HTTP 200/201:**
- `POST /companies` → company criada
- 7× `POST /companies/:id/agents` → Head, PO, Arquiteto, Engenheiro, Governança, Analista,
  Curador — todos com `role`/`icon` válidos (confirma o fix do item 8 da sessão anterior)
- `POST /companies/:id/projects` → projeto "Demandas de Dados" criado
- 2× `POST /companies/:id/labels` → Interestelar + LGPD
- 6× `POST /companies/:id/skills` → todas as 6 skills importadas com markdown inline
  (confirma o fix do endpoint errado — item 7 da sessão anterior)
- `POST /companies/:id/routines` + `POST /routines/:id/triggers` → routine semanal +
  trigger cron criados em duas chamadas (confirma o fix do schema errado — item 9)

Isso fecha a lacuna que ficava em aberto desde a sessão anterior: os 9 bugs de contrato de
API corrigidos por auditoria de código-fonte agora estão **confirmados por execução real**,
não só por leitura. IDs gerados (ambiente de teste, descartável):
Company `618f17cc-3979-4e3d-9d3e-d0bb8bd1638b`, Projeto `9bf792db-0ea8-402a-924d-d633021a59d2`,
Routine `b8ed4ff5-e5e6-4303-8935-3000ea57af6c`.

### 2026-08-17 — Fluxo de demanda com Groq real: 3 bugs de concorrência/roteamento encontrados e corrigidos

Diego forneceu uma `GROQ_API_KEY` real. Primeiro obstáculo: o catálogo da Groq mudou
completamente desde que o roadmap foi escrito — nenhum `llama-3.x-70b-versatile` existe
mais (confirmado via `GET https://api.groq.com/openai/v1/models`), e o próprio
`openai/gpt-oss-120b` (que existe) estourou o limite de TPM do free tier (8000) com um
prompt pequeno de teste. Modelo trocado pra **`openai/gpt-oss-20b`** (responde limpo, sem
vazar raciocínio como o `qwen/qwen3.6-27b`, e sobra folga de TPM); `groq_max_tokens`
reduzido de 8192 para 2048 (o `max_tokens` pedido conta no orçamento do request mesmo que
a resposta real seja menor).

Criei um ticket real (INT-4, depois INT-7/INT-8 em iterações) atribuído ao Head e disparei
o webhook de verdade. **3 bugs sérios de concorrência/roteamento apareceram só rodando
contra o ambiente real** (nenhum teste automatizado com mocks pegaria isso, porque o mock
não reproduz o comportamento nativo do Paperclip de reacordar agentes):

1. **Comentário do próprio agente reacorda o próprio agente.** Paperclip dispara
   `wakeReason: "issue_commented"` pro assignee atual toda vez que um comentário novo
   entra no issue — inclusive os comentários que O PRÓPRIO harness posta em nome do
   agente. Como a reatribuição só acontecia depois de postar 2 comentários (resposta +
   contadores), cada heartbeat gerava 1-2 heartbeats redundantes extras, consumindo TPM
   da Groq à toa. **Mitigado**: os dois comentários foram consolidados em um só.
2. **Sem lock por ticket → condição de corrida real.** Heartbeats concorrentes pro mesmo
   `issue_id` liam o estado "antigo" do ticket em paralelo e um desfazia a reatribuição
   do outro — confirmado ao vivo: um ticket ficou oscilando entre Head e PO por 5+
   heartbeats seguidos. **Corrigido**: `_issue_locks: dict[str, asyncio.Lock]` em
   `webhook.py` serializa o processamento por `issue_id`.
3. **Heartbeats obsoletos reprocessavam do zero.** Mesmo serializado, um heartbeat pro
   Head que chega DEPOIS que o próprio Head (num heartbeat anterior já processado) já
   reatribuiu o ticket pra outro agente ainda ia até o fim e chamava o LLM de novo.
   **Corrigido**: no início de `_process_demanda_agent`, compara
   `issue_data["assigneeAgentId"]` com `payload.agentId` — se não bate mais, descarta o
   heartbeat sem chamar o LLM (log `heartbeat.obsoleto.ignorado`).
4. **Bônus, achado pelo próprio teste real:** o modelo (`openai/gpt-oss-20b`) escreveu
   `#PLANO: HEAD → PO → ENGENHEIRO → HEAD (final)` — incluindo `head` como primeiro E
   último passo do próprio plano. Como o código trata `plan[0]` como "próximo agente"
   literalmente, isso reatribuía o ticket pro próprio Head em vez de pro PO. Prompt não é
   confiável sozinho com LLM — **corrigido no parser**: `head` é excluído explicitamente
   dos tokens válidos em `_parse_output` (engine_prompt.py) e `_extract_plan_from_text`
   (webhook.py), com reforço também na instrução do prompt.

**Validação final:** ticket de teste limpo (INT-8) rodado com os 3 fixes aplicados —
Head classificou, reatribuiu corretamente pro PO (sem "head" no plano), o heartbeat
redundante do próprio comentário do Head foi descartado pelo guard de idempotência
(log `heartbeat.obsoleto.ignorado`, zero chamada à Groq desperdiçada), e o PO acordou de
verdade e processou. Os 3 tickets de teste foram cancelados manualmente ao final pra não
deixar reprocessamento em background rodando à toa (o PO, em uma resposta, não emitiu
`ETAPA_CONCLUIDA`/`REVISAO_NECESSARIA`, então o ticket ficaria sendo reprocessado a cada
comentário próprio até o teto de 10 heartbeats/5min — comportamento de qualidade de
prompt/resposta do LLM, não bug de concorrência).

**Suíte de testes**: 24 testes agora (2 novos — regressão do bug "head no próprio plano"
em `test_engine_prompt.py` e `test_webhook_flow_e2e.py`, e um teste de heartbeat obsoleto
sendo descartado sem chamar o LLM). Todos passando.

**Ainda não validado**: um fluxo de demanda completo (Head → PO → Arquiteto → ... → Head
fecha) rodando do início ao fim com o LLM real terminando cada etapa corretamente — os
testes de hoje confirmam que o roteamento/concorrência funcionam, mas nenhum ticket real
chegou a ser fechado por completo (todos foram cancelados manualmente antes disso, por
economia de chamadas à Groq). Fica como próximo passo natural se quiser ver o ciclo
completo, inclusive nota no vault + work product + `status: done`.

### 2026-08-17 — Incidente real: loop do próprio aviso de loop + fix + provider dinâmico

**Incidente ao vivo** (reportado por Diego com print da UI): a proteção de loop
(`_check_loop_protection`, cap de 10 heartbeats/5min) disparava, postava um comentário de
aviso ("loop de revisões detectado...") — e esse PRÓPRIO comentário reacordava o agente
de novo (mesmo mecanismo nativo do Paperclip que já tinha causado o problema #1 desta
sessão), que batia no cap de novo, comentava de novo, indefinidamente. A mesma mensagem
de aviso foi postada dezenas de vezes seguidas. Pior: tickets "cancelados" manualmente por
mim via API voltavam pra `in_progress` sozinhos (heartbeats em voo, já lidos antes do
cancelamento, sobrescreviam o status depois) — e o Paperclip também gera sozinho tickets
filho tipo "Review productivity for X" / "Recover stalled issue for X", atribuídos ao
Head automaticamente, mais fontes de heartbeat que eu não tinha mapeado.

**Contenção imediata**: parei tudo via API direta —
`PATCH /issues/:id {"status":"cancelled","assigneeAgentId":null}` em todos os tickets com
agente atribuído (inclusive os auto-gerados), até `GET /live-runs` mostrar 0 ativos.

**Fix definitivo**: o handler de loop protection em `webhook.py` só comentava, nunca
desatribuía. Agora ele chama `client.update_issue(issue_id, status="blocked",
clear_assignee_agent=True)` **antes** de comentar — sem ninguém atribuído, o comentário
não tem quem reacordar. Precisou de um `clear_assignee_agent` novo em
`paperclip_client.py` porque `assignee_agent_id=None` já significava "não mexe nesse
campo" (não dava pra usar o mesmo `None` pra "desatribuir de propósito"). Teste de
regressão adicionado (`test_loop_protection_desatribui_antes_de_comentar`).

**Pedido do Diego**: deixar o provider de LLM dinâmico (Groq/OpenAI/Claude/etc), não só
Groq hardcoded. Criado [harness/llm_client.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/llm_client.py)
— ponto único de chamada ao LLM, escolhido via `LLM_PROVIDER` no `.env`
(`groq` | `openai` | `anthropic`), cada um com sua própria `*_API_KEY`/`*_MODEL`. Os dois
lugares que faziam chamada direta e hardcoded pra Groq (`engine_prompt.py` dos agentes de
demanda, e `tools_skill_curator.py` do Curador — este último nem usava o SDK, era um
`httpx.post` cru) agora passam por esse cliente único. `LLM_TEMPERATURE`/`LLM_MAX_TOKENS`
generalizados (antes eram `GROQ_TEMPERATURE`/`GROQ_MAX_TOKENS`). SDKs `openai` e
`anthropic` adicionados ao `requirements.txt` (import lazy dentro de cada função de
provider — não pesa se você só usa Groq).

**Suíte de testes**: 30 testes agora (+ `tests/test_llm_client.py`: dispatch por
provider desconhecido falha claro, chave ausente falha sem tentar rede, default é groq).
Ambiente real redeployado com os dois fixes, confirmado saudável e com zero
tickets atribuídos / zero runs ativos antes de encerrar a sessão.

### 2026-08-17 — Página de configuração (/config) + provider dinâmico editável em runtime

Pedido do Diego: uma página pra escolher o LLM (Groq/OpenAI/Anthropic) e configurar as
chaves, tudo em português, e melhorar a usabilidade geral (o harness não tinha
NENHUMA interface até então, só endpoints JSON).

**Arquitetura**: até aqui `LLM_PROVIDER` só existia como variável de `.env`, lida uma
vez na subida do container — trocar exigia editar arquivo + `docker compose up
--force-recreate`. Pra dar pra trocar pela UI sem restart, criei uma camada de config
dinâmica:
- Nova tabela `runtime_settings` (chave/valor genérico) em `tools_memoria.py`.
- [harness/runtime_config.py](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/runtime_config.py) —
  resolve a config efetiva com prioridade **banco de dados > `.env`**. `llm_client.py`
  agora chama `resolver_provider_ativo()` a cada `chat_completion()` (não só uma vez no
  boot), então uma troca na página vale já no próximo heartbeat.
- Chave de API sempre mascarada nas respostas GET (`gsk_********yQ8b`) — nunca volta
  crua pro navegador; só é sobrescrita se o usuário realmente digitar uma nova (um
  campo cheio de `*` — o placeholder mascarado sem edição — é ignorado no salvamento).

**Rotas novas** (`harness/ui_routes.py`, servidas pelo mesmo FastAPI do webhook):
`GET /` e `GET /config` (a página), `GET /api/status` (dashboard), `GET|POST
/api/config/llm` (ler/salvar provider+modelo+chave+temperatura+max_tokens), `POST
/api/config/llm/testar` (testa uma combinação provider/modelo/chave sem salvar —
chama o LLM de verdade com um prompt mínimo antes do usuário confirmar).

**Página** ([harness/static/config.html](file:///d:/orchestration-zero-humans/paperclip/interestelar/harness/static/config.html)) —
HTML/CSS/JS autocontido, sem build step, 100% português: cards de status (Harness,
Paperclip, Vault, Provider ativo), seletor visual dos 3 providers, campo de modelo com
sugestões, campo de chave mascarado, botão "Testar conexão" com spinner, configurações
avançadas (temperatura/max_tokens) recolhidas por padrão.

**Bugs achados testando de verdade** (mesmo padrão de hoje — todo teste contra o
ambiente real encontrou algo):
1. Máscara de chave usava um caractere bullet (•) não-ASCII que corrompeu no disco
   neste ambiente Windows (mesma classe de mojibake do incidente do PowerShell, sessão
   anterior) — trocado por `*` (ASCII puro).
2. `resolver_provider_ativo()` caía silenciosamente pra "groq" se o provider salvo
   fosse inválido, escondendo erro de configuração real atrás de uma mensagem
   enganosa. Corrigido pra deixar `chat_completion` reportar o provider desconhecido
   de verdade.
3. Botão "Testar conexão" usava `max_tokens=10` — pequeno demais pra modelos que gastam
   tokens com raciocínio antes do texto final (`openai/gpt-oss-*`), retornando sucesso
   com resposta vazia. Subido pra 64 + prompt reforçando "sem raciocínio".

**Suíte de testes**: 44 no total agora (+14 — `test_runtime_config.py` cobre
precedência banco>env, mascaramento, proteção contra sobrescrever com placeholder;
`test_ui_routes.py` usa o `TestClient` do FastAPI pra bater nas rotas de verdade,
inclusive confirmando que a chave real nunca aparece crua no HTML/JSON). Deployado e
validado contra o ambiente real: `/config` carrega, `/api/config/llm` mascara
corretamente, "testar conexão" funciona com a chave Groq real.

- ~~**Fase 7 — testes ponta-a-ponta:** script Python mockando 1 ticket...~~ **Feito em 2026-08-17** — 44 testes automatizados, 9 bugs de contrato de API + 2 bugs de roteamento pós-revisão/plano + 3 bugs de concorrência (lock, heartbeat obsoleto, loop-do-próprio-aviso-de-loop) + 3 bugs da página de config, corrigidos.
- ~~**Fase 7 — validação contra ambiente real**~~ **Feito em 2026-08-17** — `docker compose up`, bootstrap, `setup_paperclip.py` e fluxo de demanda com Groq real, todos validados contra uma instância viva.
- ~~**Provider de LLM dinâmico**~~ **Feito em 2026-08-17** — `harness/llm_client.py` + `runtime_config.py` com `LLM_PROVIDER=groq|openai|anthropic`, editável em runtime.
- ~~**Página de configuração / melhoria de UX**~~ **Feito em 2026-08-17** — `/config`, painel de status + seleção de provider/chaves em português.
- **Ideias de UX pra depois** (não implementadas, só anotadas): autenticação na página `/config` antes de expor a porta 8000 fora do localhost (hoje sem auth, mesmo padrão do resto do harness); histórico de demandas/tickets processados direto na página; indicador visual de "revisão N/3" por ticket ativo; log ao vivo (WebSocket/SSE) dos heartbeats em vez de só nos logs do container.
- **Investigar mais a fundo os tickets auto-gerados pelo Paperclip** ("Review productivity for X", "Recover stalled issue for X") — são um recurso nativo do core, atribuídos ao Head automaticamente. Hoje o Head trataria isso como uma demanda normal (tentando montar #PLANO: pra um ticket que na verdade é um review interno). Vale o Head reconhecer esses títulos e simplesmente fechar/comentar sem disparar o pipeline completo.
- **Opcional:** rodar um ticket real do início ao fim sem cancelar, pra ver o fechamento completo (vault + work product + `done`) — ainda não observado ao vivo, só coberto pelo teste automatizado com mock.
- **Fase 7 — casos restantes:** Curador de Skills fluxo completo, fallback GitHub API, disparo da routine semanal (a routine foi criada com sucesso, mas seu disparo automático no horário marcado — segunda 03:00 UTC — ainda não foi observado).
- **Ajuste menor opcional:** Head de Dados, ao acordar o primeiro heartbeat, chamar automaticamente `tools_repo.obter_ou_gerar_padrao_e_escrever_vault(...)` se metadata do ticket tiver `repo_url` e anexar resultado na descrição do ticket para os próximos agentes consumirem direto.
- **Fase 6 opcional:** Badge "Revisão N/3" no IssueRow do UI, botão "Aprovar Skill" em CommentThread.
- **Governança como Approval Gate:** após MVP rodar; configurar approval do Paperclip que requer ação do agente Governança antes de `done` (§5.2 roadmap).
