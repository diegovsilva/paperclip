# Interestelar

Time de engenharia de dados multi-agente (6 agentes de demanda + 1 Curador de Skills)
rodando **sobre** o [Paperclip](../README.md) — não é um fork, é um harness Python
separado que conversa com o Paperclip pela API HTTP dele.

```
Você cria um ticket → Head classifica e monta um plano → o ticket passa pelos
agentes certos (PO, Arquiteto, Engenheiro, Governança, Analista) → cada um aplica
suas skills, pode devolver revisão pra outro → Head fecha e grava a demanda
consolidada num vault Obsidian.
```

Este documento é o manual de quem está começando do zero. Se você já tem tudo rodando
e só quer o histórico do que foi construído/corrigido, veja
[doc/plans/2026-08-14-interestelar-progresso.md](../doc/plans/2026-08-14-interestelar-progresso.md).

---

## Pré-requisitos

- **Docker Desktop** instalado e rodando (o projeto sobe Postgres + Paperclip + o
  harness Python, tudo via `docker compose`).
- **Uma chave de API de algum provider de LLM.** [Groq](https://console.groq.com/keys)
  tem free tier generoso e é o mais rápido pra começar; OpenAI e Anthropic também são
  suportados (dá pra trocar depois pela interface, sem precisar decidir agora).
- **Windows:** nada de especial a fazer — o repo já tem um `.gitattributes` que evita
  problema de final de linha (CRLF) nos scripts, e o `start.ps1` funciona no
  PowerShell 5.1 que já vem instalado.

Não precisa instalar Python, Node, nem nada além do Docker — tudo roda dentro dos
containers.

---

## Primeiro uso — passo a passo

Todos os comandos abaixo rodam de dentro da pasta `interestelar/`.

### 1. Subir os serviços

```bash
./start.sh              # Linux/Mac/Git Bash
.\start.ps1              # Windows PowerShell
```

Isso builda as imagens (a primeira vez demora bastante — o Paperclip é um monorepo
Node grande; da segunda vez em diante é rápido), sobe Postgres + Paperclip + harness, e
espera os dois ficarem saudáveis. No final mostra:

```
Paperclip UI       : http://localhost:3100
Painel Interestelar: http://localhost:8000/config
```

Se `.env` não existir ainda, o script cria a partir de `.env.example` e gera um
`BETTER_AUTH_SECRET` aleatório sozinho (é obrigatório pro Paperclip subir).

### 2. Criar a primeira conta (bootstrap do Paperclip)

Numa instância nova do Paperclip, ninguém é admin ainda. A própria UI, se você abrir
`http://localhost:3100` agora, vai pedir pra rodar um comando de CLI que **não
funciona** dentro deste ambiente Docker (ele espera um assistente interativo que só
roda fora de container). Em vez disso:

```bash
./start.sh bootstrap
.\start.ps1 bootstrap
```

Isso imprime um link `http://localhost:3100/invite/pcp_bootstrap_...` — abra no
navegador e crie sua conta (e-mail + senha). Esse link expira em 72h e só funciona uma
vez (se já existir um admin, o comando avisa e não faz nada).

### 3. Gerar a API key do harness

O harness (o Python que roda os 7 agentes) precisa de uma API key pra falar com o
Paperclip em seu nome. Não existe um botão "gerar chave" nas configurações — o fluxo
real é um pedido de acesso que você aprova logado:

```bash
./start.sh chave-api
.\start.ps1 chave-api
```

O comando imprime um link de aprovação, fica esperando você clicar (com a conta criada
no passo 2, já logada), e assim que aprovar **salva a chave sozinho** em `.env` e
recria o harness pra carregar. Não precisa copiar/colar nada.

### 4. Criar os 7 agentes, projeto, skills e a routine

```bash
./start.sh setup
.\start.ps1 setup
```

Roda `scripts/setup_paperclip.py` dentro do container: cria a company (ou reaproveita
uma existente pelo nome), os 7 agentes (Head, PO, Arquiteto, Engenheiro, Governança,
Analista, Curador de Skills) com o org chart certo, o projeto "Demandas de Dados", 2
labels, as 6 skills, e a routine semanal do Curador. É idempotente — rodar de novo não
duplica nada.

### 5. Escolher o provider de LLM

Abra **http://localhost:8000/config** — o painel do Interestelar. Escolha
Groq/OpenAI/Anthropic, cole a chave, clique em **Testar conexão** (chama o modelo de
verdade antes de você confirmar) e depois em **Salvar**. Vale no próximo heartbeat, sem
precisar reiniciar nada.

### 6. Testar: criar uma demanda de verdade

No Paperclip (`http://localhost:3100`), dentro do projeto "Demandas de Dados", crie um
ticket e atribua ao agente **Head de Dados**. Em poucos segundos ele deve classificar a
demanda, montar um `#PLANO:` e reatribuir pro primeiro agente da lista. Acompanhe pelos
comentários do próprio ticket.

---

## O painel (`/config`)

- **Status**: Harness, conexão com o Paperclip, Vault/Repositórios, provider ativo.
- **Provider de LLM**: cartões pra Groq/OpenAI/Anthropic — clique num pra selecionar,
  preencha modelo + chave, teste, salve. A chave nunca aparece crua na tela depois de
  salva (fica mascarada, tipo `gsk_********yQ8b`).
- **Avançado**: temperatura e limite de tokens por resposta.

Hoje a página **não tem autenticação** — mesmo padrão do resto do harness (nenhum
endpoint tem auth por padrão). Não exponha a porta 8000 fora do seu `localhost` sem
colocar alguma camada de proteção na frente (proxy reverso com auth, VPN, etc.).

---

## Arquitetura em 1 minuto

```
docker-compose.yml
├── db          Postgres 17 — banco do Paperclip
├── paperclip   build da imagem raiz do repo — a instância que os agentes usam
└── harness     este projeto (Python/FastAPI) — os 7 agentes + o painel
```

Dentro de `harness/`:

| Arquivo | O que faz |
|---|---|
| `webhook.py` | Servidor FastAPI — recebe heartbeats do Paperclip (`/webhook/<agente>`), roteia entre agentes, fecha demandas |
| `engine_prompt.py` | Monta o prompt (identidade + skills + ticket + histórico) e chama o LLM |
| `llm_client.py` + `runtime_config.py` | Provider de LLM configurável (Groq/OpenAI/Anthropic), resolvido em runtime |
| `tools_memoria.py` | SQLite: harness de revisão (limite 3 total/2 por par), cache de padrão de repo, config dinâmica |
| `tools_obsidian.py` | Escrita atômica no vault (`vault/Demandas/`, `vault/Agentes/`) |
| `tools_repo.py` | Detecta o padrão de desenvolvimento do repo da empresa (Reversa → GitHub API → GitLab API → local) |
| `tools_skill_curator.py` | Ciclo semanal que verifica se as skills externas mudaram e propõe atualização (nunca aplica sozinho) |
| `ui_routes.py` + `static/config.html` | O painel `/config` |
| `paperclip_client.py` | Wrapper HTTP pra API do Paperclip |

Cada agente tem uma identidade em `agents/<slug>/` (`SOUL.md` = persona, `AGENTS.md` =
papel/regras/skills, `HEARTBEAT.md` = checklist) e as skills reais ficam em
`skills/<nome>/SKILL.md`.

**Os 3 princípios inegociáveis** (não quebre isso):
1. Máximo 3 revisões totais por demanda, máximo 2 idas-e-voltas entre o mesmo par de agentes.
2. Skill externa proposta pelo Curador nunca aplica sozinha — fica em `skills_pendentes/` até aprovação humana (`POST /aprovar-skill/<nome>`).
3. Sem acesso cross-company — cada harness atende uma única empresa (`PAPERCLIP_COMPANY_ID`).

---

## Rodando os testes

```bash
cd interestelar
python -m venv .venv
.venv/Scripts/activate   # ou source .venv/bin/activate no Linux/Mac
pip install -r requirements-dev.txt
pytest
```

Suíte cobre o harness de revisão, o parsing do LLM, o roteamento (inclusive as
condições de corrida entre heartbeats concorrentes), a config dinâmica de LLM e as
rotas do painel — tudo com dublês (não chama Groq/OpenAI/Anthropic/Paperclip de
verdade), então roda em segundos.

---

## Comandos do dia a dia

```bash
./start.sh              # sobe tudo (rebuilda as imagens)
./start.sh --no-build   # sobe sem rebuildar (mais rápido depois da primeira vez)
./start.sh logs         # segue os logs dos dois serviços
./start.sh status       # docker compose ps
./start.sh stop         # derruba tudo
./start.sh restart      # stop + start
```

Depois de mudar código do harness, `--build`/`--no-build` às vezes não é suficiente
pra recriar o container com a imagem nova (é um comportamento observado do Docker
Compose neste ambiente, não um bug do projeto) — se a mudança não parecer surtir
efeito, force:

```bash
docker compose up -d --force-recreate --no-deps harness
```

---

## Troubleshooting

**"Hostname 'paperclip' is not allowed for this Paperclip instance"** — não deveria
mais acontecer (o `docker-compose.yml` já configura `PAPERCLIP_ALLOWED_HOSTNAMES`), mas
se você mudou o nome do serviço no compose, ajuste essa variável de ambiente também.

**Um ticket fica reprocessando sem parar / vários comentários "loop de revisões
detectado" seguidos** — não deveria mais acontecer (a proteção de loop hoje desatribui
o ticket antes de comentar). Se acontecer mesmo assim, pare na hora:
```bash
curl -X PATCH "http://localhost:3100/api/issues/<id>" \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" -H "Content-Type: application/json" \
  -d '{"status":"cancelled","assigneeAgentId":null}'
```

**`db` demora demais pra ficar `healthy` e o `paperclip` nunca sobe** — normal no
primeiro start a frio em alguns Docker Desktop (Postgres inicializando o data
directory). Espere um pouco e rode `./start.sh status` — se `db` já estiver `healthy`,
só rode `docker compose up -d` de novo que os outros dois sobem.

**Erro de modelo da Groq ("model does not exist")** — o catálogo da Groq muda com
frequência. Veja o catálogo atual em `https://api.groq.com/openai/v1/models` (com sua
chave) e ajuste o modelo pelo painel `/config`.

**Resposta vazia do modelo, mas a chave é válida** — alguns modelos (a família
`openai/gpt-oss-*` da Groq, por exemplo) gastam tokens em "raciocínio" antes do texto
final. Se `max_tokens` estiver baixo demais, a resposta visível pode vir vazia. Aumente
em Configurações avançadas no painel.

---

## O que ainda não está pronto

- **Autenticação no painel `/config`** — hoje aberto, sem senha.
- **Curador de Skills** — o ciclo semanal nunca rodou de ponta a ponta contra fontes
  externas reais (só testado com mocks).
- **Tickets automáticos do Paperclip** ("Review productivity for X", "Recover stalled
  issue for X") — o Head ainda não reconhece esses títulos como especiais; trata como
  demanda normal.
- **Fase 6 (opcional)** — badges de UI no core do Paperclip (Revisão N/3, botão Aprovar
  Skill) não foram feitos.

Histórico completo de decisões, bugs encontrados e como foram corrigidos:
[doc/plans/2026-08-14-interestelar-progresso.md](../doc/plans/2026-08-14-interestelar-progresso.md).
Plano original: [doc/plans/2026-08-14-interestelar-roadmap.md](../doc/plans/2026-08-14-interestelar-roadmap.md).
