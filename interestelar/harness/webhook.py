from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import unicodedata
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Deque, Literal, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from .auth import exigir_auth_ui
from .config import get_settings
from .engine_prompt import (
    AGENT_LABELS,
    AgentInput,
    AgentOutput,
    executar_agente,
)
from . import tools_memoria as mem
from . import tools_obsidian as obs
from . import tools_skill_curator as curador
from . import runtime_config
from . import ui_routes
from .logging_setup import setup_logging
from .paperclip_client import PaperclipClient, PaperclipHTTPError

log = setup_logging()
settings = get_settings()


class HeartbeatContext(BaseModel):
    taskId: Optional[str] = None
    # O core do Paperclip usa dezenas de wakeReason internos (ex.: "missing_issue_comment",
    # "process_lost_retry", "on_demand", ...) além dos "óbvios". Um Literal restrito aqui
    # rejeitaria (422) qualquer heartbeat real com valor fora da lista — mantemos livre e
    # só usamos o campo para log/contexto, nunca para branching de lógica.
    wakeReason: str = "manual"
    commentId: Optional[str] = None


class HeartbeatPayload(BaseModel):
    runId: str
    agentId: str
    # O adapter http do core (server/src/adapters/http/execute.ts) monta o body como
    # {...payloadTemplate, agentId, runId, context} — companyId NÃO é incluído por padrão.
    # setup_paperclip.py injeta companyId via adapterConfig.payloadTemplate, mas mantemos
    # opcional aqui e resolvemos via runtime_config.resolver_paperclip_company_id como
    # fallback (ver _resolve_company_id) para não quebrar com 422 em agentes configurados
    # manualmente.
    companyId: Optional[str] = None
    context: HeartbeatContext = Field(default_factory=HeartbeatContext)


_heartbeat_timestamps: dict[str, Deque[float]] = defaultdict(deque)

# Paperclip reacorda o agente atribuído a cada novo comentário no issue ("issue_commented"),
# e como cada agente só se reatribui DEPOIS de comentar, heartbeats concorrentes pro mesmo
# issue_id são o normal, não a exceção. Sem serializar, dois heartbeats podem ler o mesmo
# estado "antigo" do ticket, processar em paralelo e um desfazer a reatribuição do outro —
# confirmado num teste real (ticket oscilando entre Head e PO, o Head nunca "grudava" no
# próximo agente). Um lock por issue_id garante que o segundo heartbeat só começa a ler o
# ticket depois que o primeiro terminou de escrever nele.
_issue_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "harness.startup",
        port=settings.harness_port,
        groq_model=settings.groq_model,
        vault_path=str(settings.vault_path),
        sqlite_path=str(settings.sqlite_path),
    )
    settings.vault_path.mkdir(parents=True, exist_ok=True)
    settings.repositorios_path.mkdir(parents=True, exist_ok=True)
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    await mem.init_db()
    yield
    log.info("harness.shutdown")


app = FastAPI(title="Interestelar Harness", version="0.2.0", lifespan=lifespan)
app.include_router(ui_routes.router)


async def _verify_webhook_signature(raw_body: bytes, header_signature: Optional[str]) -> bool:
    secret = await runtime_config.resolver_harness_webhook_secret()
    if not secret:
        return True
    if not header_signature:
        return False
    mac = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, header_signature)


async def _check_loop_protection(issue_id: Optional[str]) -> bool:
    if not issue_id:
        return True
    tuning = await runtime_config.obter_tuning_resumo()
    now = time.time()
    window_sec = tuning.hard_loop_window_min * 60
    dq = _heartbeat_timestamps[issue_id]
    while dq and dq[0] < now - window_sec:
        dq.popleft()
    dq.append(now)
    if len(dq) > tuning.hard_loop_heartbeat_cap:
        log.error(
            "loop.hard_cap_exceeded",
            issue_id=issue_id,
            count=len(dq),
            cap=tuning.hard_loop_heartbeat_cap,
        )
        return False
    return True


def _normalizar_slug(token: str) -> str:
    """Remove acentos antes de comparar com os slugs válidos (ASCII). O modelo
    frequentemente escreve "GOVERNANÇA" (com ç/ã) no #PLANO:, mas o slug válido é
    "governanca" — sem normalizar, esse token nunca batia com `valid` e o passo de
    governança sumia silenciosamente do plano (confirmado num teste real: ticket com
    #PLANO: ... → GOVERNANÇA → ... foi recuperado como plano sem nenhum "governanca")."""
    normalizado = unicodedata.normalize("NFKD", token)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _extract_plan_from_text(text: str) -> list[str]:
    if not text:
        return []
    import re as _re
    # "head" nunca é um passo válido do plano (ver mesma checagem em engine_prompt.py
    # _parse_output — o modelo já escreveu "#PLANO: HEAD → PO → ENGENHEIRO → HEAD" num
    # teste real, o que reatribuía o ticket pro próprio Head em vez de seguir o plano).
    valid = set(AGENT_LABELS.keys()) - {"head"}
    plan_line = None
    for ln in text.splitlines():
        if ln.strip().startswith("#PLANO:"):
            plan_line = ln.split("#PLANO:", 1)[1].strip()
            break
    if not plan_line:
        return []
    tokens = [
        normalizado
        for t in _re.split(r"[→→, ]+", plan_line)
        for normalizado in [_normalizar_slug(t.strip().lower())]
        if normalizado in valid
    ]
    return tokens


def _descobrir_plano_do_historico(
    history_tuples: list[tuple[str, str, str]],
    issue_data: dict[str, Any],
) -> list[str]:
    """Mesma busca que o fluxo principal faz quando `output.plan` vem vazio (comentário
    anterior com `#PLANO:`, senão a description) — fatorado pra ser reutilizável também
    pelo caminho de wake de approval, que não chama o LLM e por isso não tem `output`."""
    for _autor_nome, _ts, corpo in history_tuples:
        plano_detectado = _extract_plan_from_text(corpo)
        if plano_detectado:
            return plano_detectado
    if issue_data.get("description"):
        return _extract_plan_from_text(issue_data["description"]) or []
    return []


def _proximo_agente_do_plano(
    plano: list[str],
    agente_atual: str,
) -> Optional[str]:
    if agente_atual not in plano:
        return plano[0] if plano else None
    idx = plano.index(agente_atual)
    if idx + 1 < len(plano):
        return plano[idx + 1]
    return None


def _agente_para_papel(agent_slug: str) -> str:
    return AGENT_LABELS.get(agent_slug, agent_slug.title())


# Tickets que o próprio Paperclip cria sozinho (revisão de produtividade, recuperação de
# ticket parado, escalonamento de liveness, avaliação de run silenciosa) — não são
# demandas de dados, então o Head não deve tentar montar um #PLANO: e rotear pelos
# agentes da DataCorp AI (PO/Arquiteto/Engenheiro/...) neles. Detectado via `originKind`
# (campo real da linha do banco, devolvido por `GET /issues/:id` — ver
# server/src/routes/issues.ts `res.json({ ...issue, ... })`), não pelo texto do título:
# título é string livre e pode mudar no core sem aviso, `originKind` é o contrato de
# verdade (ver server/src/services/recovery/origins.ts RECOVERY_ORIGIN_KINDS).
_ORIGENS_INTERNAS_DO_PAPERCLIP = {
    "issue_productivity_review": "revisão de produtividade de um ticket",
    "stranded_issue_recovery": "recuperação de ticket parado",
    "harness_liveness_escalation": "escalonamento de liveness de uma execução",
    "stale_active_run_evaluation": "avaliação de execução ativa silenciosa",
}


def _descricao_ticket_interno_paperclip(issue_data: dict[str, Any]) -> Optional[str]:
    return _ORIGENS_INTERNAS_DO_PAPERCLIP.get(issue_data.get("originKind") or "")


async def _resolve_company_id(payload: HeartbeatPayload) -> str:
    """companyId pode não vir no payload real do adapter http (ver HeartbeatPayload).
    Cai pro company_id configurado (página /config > PAPERCLIP_COMPANY_ID do .env) —
    cada harness atende uma única empresa."""
    cid = payload.companyId or await runtime_config.resolver_paperclip_company_id()
    if not cid:
        raise RuntimeError(
            "companyId ausente no heartbeat e nenhum company_id configurado "
            "(página /config nem PAPERCLIP_COMPANY_ID no .env)."
        )
    return cid


async def _encontrar_agente_id_por_slug(
    client: PaperclipClient,
    company_id: str,
    agent_slug: str,
) -> Optional[str]:
    slug_to_agent_name: dict[str, str] = {
        "head": "Head de Dados",
        "po": "PO de Dados",
        "arquiteto": "Arquiteto de Dados",
        "engenheiro": "Engenheiro de Dados",
        "governanca": "Engenheiro de Governança",
        "analista": "Analista de Dados",
        "curador-skills": "Curador de Skills",
    }
    expected_name = slug_to_agent_name.get(agent_slug) or agent_slug
    try:
        agents = await client.list_agents(company_id)
    except Exception:  # noqa: BLE001
        return None
    for a in agents:
        name = a.get("name") or ""
        if expected_name.lower() in name.lower():
            return a.get("id")
        metadata = a.get("metadata") or {}
        if metadata.get("interestelar_slug") == agent_slug:
            return a.get("id")
    return None


async def _carregar_padrao_do_contexto(
    issue_data: Optional[dict[str, Any]],
) -> str:
    if not issue_data:
        return ""
    desc = issue_data.get("description") or ""
    markers = [
        "## Padrão do Repositório",
        "========== PADRÃO REPO ==========",
        "Padrão do Repositório:",
    ]
    for m in markers:
        if m in desc:
            try:
                return desc.split(m, 1)[1].strip()[:12000]
            except Exception:  # noqa: BLE001
                return ""
    return ""


async def _montar_comentario_contadores(ticket_id: str, state: mem.ReviewState) -> str:
    tuning = await runtime_config.obter_tuning_resumo()
    lines = [
        f"#REVISAO_ATUAL: {state.total_revisoes}/{tuning.max_review_total}",
        "Contadores por par (máx " + str(tuning.max_review_per_pair) + " idas/voltas):",
    ]
    if state.par_revisoes:
        for par, cnt in sorted(state.par_revisoes.items()):
            lines.append(f"- {par}: {cnt}/{tuning.max_review_per_pair}")
    else:
        lines.append("- (nenhuma revisão ainda)")
    return "\n".join(lines)


def _resumo_para_vault(agent_slug: str, llm_output: str) -> str:
    lines = [ln.strip() for ln in llm_output.splitlines() if ln.strip()]
    excerpt = "\n".join(lines[:40])
    return (
        f"## {_agente_para_papel(agent_slug)} — contribuição\n\n"
        f"{excerpt}\n"
    )


async def _finalizar_como_head(
    client: PaperclipClient,
    issue_id: str,
    issue_data: dict[str, Any],
    comments_history: list[dict[str, Any]],
    plan: list[str],
) -> None:
    partes: list[str] = []
    for c in comments_history:
        body = c.get("body") or ""
        autor = c.get("authorName") or c.get("authorId") or "desconhecido"
        ts = c.get("createdAt") or ""
        if body.strip():
            partes.append(f"### [{ts}] {autor}\n{body[:5000]}\n")
    corpo = (
        f"## Resumo do Ticket #{issue_id}\n\n"
        f"**Título:** {issue_data.get('title','')}\n"
        f"**Status final:** done\n"
        f"**Plano executado:** HEAD → {' → '.join(AGENT_LABELS.get(a, a) for a in plan)}\n\n"
        + "\n".join(partes)
    )
    agentes: list[str] = [_agente_para_papel("head")] + [_agente_para_papel(a) for a in plan]
    seen: list[str] = []
    for a in agentes:
        if a not in seen:
            seen.append(a)
    repo_slug = issue_data.get("metadata", {}).get("repo_empresa") or ""
    demanda_path = obs.escrever_demanda(
        ticket_id=issue_id,
        titulo=issue_data.get("title", issue_id),
        conteudo_md=corpo,
        meta=obs.DemandaMeta(
            ticket_id=issue_id,
            repo_empresa=repo_slug or None,
            agentes_envolvidos=seen,
            status="done",
            tags=["demanda-fechada"],
            links=[f"[[Padrão do Repositório]]"] if repo_slug else [],
        ),
    )
    try:
        await client.create_work_product(
            issue_id=issue_id,
            title="Nota consolidada no Vault Obsidian",
            summary=(
                "Esta demanda foi consolidada automaticamente no vault do Interestelar.\n\n"
                f"Arquivo: `{demanda_path.name}`\n"
                f"Path no container: `{demanda_path}`"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("work_product.create.failed", issue=issue_id, err=str(exc))
    try:
        await client.upload_attachment(
            issue_id=issue_id,
            file_path=demanda_path,
            mime="text/markdown",
            filename=demanda_path.name,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("attachment.upload.failed", issue=issue_id, err=str(exc))
    # clear_assignee_agent=True é essencial aqui: sem isso o ticket "done" continua
    # atribuído ao Head, e como Paperclip reacorda o assignee atual a cada novo
    # comentário no issue, o PRÓPRIO comentário de fechamento (postado antes desta
    # chamada) reacordava o Head de novo pra um ticket já concluído — gastando uma
    # chamada de LLM à toa a cada fechamento (confirmado num teste real). Mesmo padrão
    # já usado na proteção de loop (_process_agent_webhook) e no bloqueio por falha de
    # LLM (llm_failed do Head).
    await client.update_issue(issue_id, status="done", clear_assignee_agent=True)
    await mem.resetar_revisoes(issue_id)
    log.info("demanda.fechada", issue=issue_id, vault=str(demanda_path))


# ─── Approval Gate da Governança (roadmap §5.2) ────────────────────────────────────
#
# Tickets com a label abaixo não fecham automaticamente quando o plano termina — ficam
# bloqueados esperando um humano aprovar/rejeitar formalmente pela aba "Approvals" do
# Paperclip antes de virar `done`. Usa o mecanismo nativo de approvals do core
# (server/src/services/approvals.ts / server/src/routes/approvals.ts), não um
# comentário nem uma convenção interna do Interestelar.
#
# Duas descobertas ao verificar contra o código real do core antes de implementar
# (mesmo hábito de nunca confiar no contrato estimado do roadmap original):
# 1. `type` é um enum FECHADO (`APPROVAL_TYPES` em packages/shared/src/constants.ts):
#    só `hire_agent` / `approve_ceo_strategy` / `budget_override_required` /
#    `request_board_approval` — não dá pra criar um tipo próprio "governanca_sign_off"
#    (o Zod rejeitaria com 400). Usamos `request_board_approval` — o único genérico o
#    bastante — com um marcador nosso dentro do `payload` pra distinguir esta approval
#    de qualquer outra que a empresa tenha por outro motivo.
# 2. Só um humano autenticado como Board resolve (`assertBoard` em
#    POST /approvals/:id/approve|reject) — nenhum agente "auto-aprova" via API, mesmo a
#    Board API key do harness sendo usada em toda outra chamada do Interestelar. É um
#    gate de verdade, com fricção manual real — decisão explícita do operador (ver o
#    registro de progresso do dia desta implementação), não um jeito de automatizar a
#    Governança sozinha.
#
# Assimetria importante: aprovar acorda automaticamente quem pediu a approval
# (heartbeat wakeReason="approval_approved", ver server/src/routes/approvals.ts) — mas
# REJEITAR NÃO acorda ninguém (confirmado lendo o handler de /approvals/:id/reject: sem
# nenhuma chamada a heartbeat.wakeup). Por isso o comentário que abre o gate já pede
# pro humano também comentar no ticket original se for rejeitar — um comentário nesse
# ticket aciona o wake genérico "issue_commented" que o Head já trata em qualquer caso.
GOVERNANCA_APPROVAL_LABEL = "governanca-requer-aprovacao"
GOVERNANCA_GATE_MARKER = "governanca_sign_off"


def _tem_label_governanca(issue_data: dict[str, Any]) -> bool:
    return any(
        (label.get("name") or "").strip().lower() == GOVERNANCA_APPROVAL_LABEL
        for label in issue_data.get("labels") or []
    )


async def _obter_approval_governanca_mais_recente(
    client: PaperclipClient,
    issue_id: str,
) -> Optional[dict[str, Any]]:
    """A approval mais recente (por createdAt) ligada a este ticket que carrega o
    marcador do gate. Pode haver mais de uma no tempo — uma rejeitada, depois uma nova
    após o retrabalho — sempre considera só a última."""
    try:
        approvals = await client.list_issue_approvals(issue_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("governanca_gate.list_approvals.failed", issue=issue_id, err=str(exc))
        return None
    candidatas = [
        a for a in approvals
        if (a.get("payload") or {}).get("interestelarGate") == GOVERNANCA_GATE_MARKER
    ]
    if not candidatas:
        return None
    candidatas.sort(key=lambda a: a.get("createdAt") or "")
    return candidatas[-1]


async def _abrir_ou_verificar_gate_governanca(
    client: PaperclipClient,
    issue_id: str,
    issue_data: dict[str, Any],
    company_id: str,
) -> Literal["aprovado", "aguardando", "rejeitado"]:
    """Só é chamado quando o Head está pra fechar um ticket com a label
    `governanca-requer-aprovacao` (ou quando é acordado por um wake de approval nesse
    mesmo ticket). Devolve o que fazer a seguir — não fecha nada sozinho."""
    existente = await _obter_approval_governanca_mais_recente(client, issue_id)
    if existente:
        status = existente.get("status")
        if status == "approved":
            return "aprovado"
        if status == "rejected":
            return "rejeitado"
        log.info("governanca_gate.ainda_pendente", issue=issue_id, status=status)
        return "aguardando"  # pending / revision_requested — já existe, não duplica

    head_id = await _encontrar_agente_id_por_slug(client, company_id, "head")
    try:
        await client.create_approval(
            approval_type="request_board_approval",
            payload={
                "interestelarGate": GOVERNANCA_GATE_MARKER,
                "issueId": issue_id,
                "issueTitle": issue_data.get("title") or issue_id,
            },
            requested_by_agent_id=head_id,
            issue_ids=[issue_id],
        )
    except Exception as exc:  # noqa: BLE001
        log.error("governanca_gate.create_approval.failed", issue=issue_id, err=str(exc))
        # Sem a approval criada não temos como saber quando desbloquear — mais seguro
        # não fechar do que fechar sem o sign-off que a própria label pediu.
        return "aguardando"
    try:
        await client.update_issue(issue_id, status="blocked", clear_assignee_agent=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("governanca_gate.block_issue.failed", issue=issue_id, err=str(exc))
    try:
        await client.add_comment(
            issue_id,
            body=(
                "**Aguardando aprovação formal do Board.** Este ticket tem a label "
                f"`{GOVERNANCA_APPROVAL_LABEL}` — antes de fechar como `done` é preciso "
                "um humano aprovar pela aba **Approvals** do Paperclip.\n\n"
                "Se for rejeitado: comente também aqui no ticket explicando o motivo — "
                "hoje o Paperclip só acorda o Head automaticamente numa aprovação, não "
                "numa rejeição, então um comentário aqui é o que garante que o Head "
                "retome o ticket."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("comment.add.failed", issue=issue_id, err=str(exc))
    return "aguardando"


async def _rejeitar_gate_governanca(
    client: PaperclipClient,
    issue_id: str,
    company_id: str,
) -> None:
    aprovacao = await _obter_approval_governanca_mais_recente(client, issue_id)
    motivo = (aprovacao or {}).get("decisionNote") or "sem motivo detalhado na approval."
    governanca_id = await _encontrar_agente_id_por_slug(client, company_id, "governanca")
    try:
        await client.add_comment(
            issue_id,
            body=(
                f"**Aprovação do Board rejeitada.** Motivo: {motivo}\n\n"
                "Devolvendo para a Governança revisar antes de tentar fechar de novo."
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("comment.add.failed", issue=issue_id, err=str(exc))
    if not governanca_id:
        log.warning("governanca_gate.governanca_agent_not_found", issue=issue_id)
        return
    try:
        await client.assign_issue(issue_id, agent_id=governanca_id)
        await client.update_issue(issue_id, status="in_progress")
    except Exception as exc:  # noqa: BLE001
        log.error("governanca_gate.reassign_after_reject.failed", issue=issue_id, err=str(exc))


async def _finalizar_ou_abrir_gate_governanca(
    client: PaperclipClient,
    issue_id: str,
    issue_data: dict[str, Any],
    comments_history: list[dict[str, Any]],
    plan: list[str],
    company_id: str,
) -> None:
    """Chamado em todo ponto onde o Head fecharia a demanda — decide se fecha de vez ou
    se precisa abrir/checar o Approval Gate da Governança primeiro (ver bloco acima)."""
    if not _tem_label_governanca(issue_data):
        await _finalizar_como_head(client, issue_id, issue_data, comments_history, plan)
        return
    resultado = await _abrir_ou_verificar_gate_governanca(client, issue_id, issue_data, company_id)
    if resultado == "aprovado":
        await _finalizar_como_head(client, issue_id, issue_data, comments_history, plan)
    elif resultado == "rejeitado":
        await _rejeitar_gate_governanca(client, issue_id, company_id)
    # "aguardando": _abrir_ou_verificar_gate_governanca já bloqueou/comentou (ou já
    # tinha feito isso numa chamada anterior) — nada mais a fazer aqui.


async def _process_demanda_agent(
    agent_slug: str,
    payload: HeartbeatPayload,
    client: PaperclipClient,
) -> None:
    issue_id = payload.context.taskId
    company_id = await _resolve_company_id(payload)
    assert issue_id is not None

    issue_data = await client.get_issue(issue_id)

    # Idempotência contra heartbeats obsoletos: Paperclip reacorda o agente atribuído a
    # cada comentário novo no ticket, então é normal um heartbeat pro Head chegar DEPOIS
    # que o próprio Head (num heartbeat anterior, já processado graças ao lock em
    # _issue_locks) reatribuiu o ticket pra outro agente. Processar de novo aqui seria só
    # gastar uma chamada à Groq à toa — e, sem essa checagem, historicamente também
    # arriscava desfazer a reatribuição (confirmado num teste real). Se o assignee atual
    # já não é mais este agente, este heartbeat está obsoleto — encerra sem chamar o LLM.
    assignee_atual = issue_data.get("assigneeAgentId")
    if assignee_atual and assignee_atual != payload.agentId:
        log.info(
            "heartbeat.obsoleto.ignorado",
            issue=issue_id,
            agente=agent_slug,
            assignee_atual=assignee_atual,
            agent_id_do_heartbeat=payload.agentId,
        )
        return

    if agent_slug == "head":
        descricao_origem = _descricao_ticket_interno_paperclip(issue_data)
        if descricao_origem:
            log.info(
                "head.ticket_interno_paperclip.ignorado",
                issue=issue_id,
                origin_kind=issue_data.get("originKind"),
            )
            try:
                # Desatribui ANTES de comentar — mesmo cuidado da proteção de loop em
                # _process_agent_webhook: sem assignee, o comentário abaixo não reacorda
                # ninguém (Paperclip dispara "issue_commented" pro assignee ATUAL a cada
                # comentário novo, inclusive os que o próprio harness posta).
                await client.update_issue(issue_id, clear_assignee_agent=True)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "head.ticket_interno_paperclip.desatribuir_falhou",
                    issue=issue_id,
                    err=str(exc),
                )
            try:
                await client.add_comment(
                    issue_id,
                    body=(
                        f"Ticket gerado automaticamente pelo próprio Paperclip ({descricao_origem}) "
                        "— não é uma demanda de dados da DataCorp AI, então não foi roteado pelo "
                        "pipeline do Interestelar (PO/Arquiteto/Engenheiro/Governança/Analista). "
                        "Deixado sem responsável para um humano avaliar."
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("comment.add.failed", issue=issue_id, err=str(exc))
            return

    raw_comments = await client.list_comments(issue_id)
    history_tuples: list[tuple[str, str, str]] = []
    for c in reversed(raw_comments[-50:]):
        autor = c.get("authorName") or c.get("authorId") or "desconhecido"
        ts = c.get("createdAt") or ""
        body = c.get("body") or ""
        history_tuples.append((autor, ts, body))

    # Approval Gate da Governança (roadmap §5.2): Paperclip acorda automaticamente quem
    # pediu a approval (`requestedByAgentId` = Head, ver _abrir_ou_verificar_gate_governanca)
    # quando um humano aprova pela aba Approvals — `wakeReason=approval_approved`,
    # `context.taskId` = este ticket. Trata aqui, sem chamar o LLM (a decisão já foi
    # tomada por um humano, não há nada pro modelo "classificar" de novo).
    if agent_slug == "head" and payload.context.wakeReason in ("approval_approved", "approval_rejected"):
        log.info("head.approval_wake", issue=issue_id, wake_reason=payload.context.wakeReason)
        resultado = await _abrir_ou_verificar_gate_governanca(client, issue_id, issue_data, company_id)
        if resultado == "aprovado":
            plano_fechamento = _descobrir_plano_do_historico(history_tuples, issue_data)
            try:
                await _finalizar_como_head(client, issue_id, issue_data, raw_comments, plano_fechamento)
            except Exception as exc:  # noqa: BLE001
                log.error("head.fechamento.falhou", issue=issue_id, err=str(exc))
        elif resultado == "rejeitado":
            await _rejeitar_gate_governanca(client, issue_id, company_id)
        # "aguardando" não deveria acontecer aqui (só faria sentido se a approval ainda
        # estivesse pending mesmo depois de um wake de approval resolvida) — nada a fazer
        # além do log já emitido dentro de _abrir_ou_verificar_gate_governanca.
        return

    pattern_md = await _carregar_padrao_do_contexto(issue_data)
    state = await mem.obter_estado_revisoes(issue_id)
    metadata = issue_data.get("metadata") or {}

    inp = AgentInput(
        agent_slug=agent_slug,
        ticket_id=issue_id,
        # `.get(key, default)` só cai no default quando a CHAVE não existe — quando ela
        # existe com valor `null` (ex.: issue criada sem descrição, como confirmado num
        # ticket real), `.get()` ainda retorna None. Isso quebrava engine_prompt.py
        # (`inp.ticket_description[:15000]`) com "'NoneType' object is not subscriptable"
        # ANTES de qualquer chamada ao LLM — o agente "processava" em <1s sem fazer nada.
        ticket_title=issue_data.get("title") or "",
        ticket_description=issue_data.get("description") or "",
        ticket_status=issue_data.get("status") or "todo",
        ticket_priority=issue_data.get("priority") or "medium",
        comments_history=history_tuples,
        pattern_md=pattern_md,
        extra_context={
            "companyId": company_id,
            "runId": payload.runId,
            "wakeReason": payload.context.wakeReason,
            "metadata": str(metadata)[:2000],
        },
        previous_review_total=state.total_revisoes,
        previous_review_par=state.par_revisoes,
    )
    output: AgentOutput = await executar_agente(inp)

    try:
        obs.escrever_nota_agente(
            papel_agente=_agente_para_papel(agent_slug),
            ticket_id=issue_id,
            titulo_curto=issue_data.get("title", issue_id)[:60],
            resumo=_resumo_para_vault(agent_slug, output.raw_text),
            repo_empresa=metadata.get("repo_empresa") or None,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("vault.nota_agente.failed", issue=issue_id, err=str(exc))

    plan = output.plan or []
    if not plan:
        # NÃO filtra por nome de autor: comentários postados via Board API key (o único
        # tipo de chave que o harness usa hoje — nenhum agente tem key própria) sempre
        # chegam com authorName=None, então qualquer filtro por "head"/"plano" no nome
        # nunca bate e o plano do Head nunca é redescoberto (isso já causou fechamento
        # prematuro de demanda num teste real: Head reprocessado por um wake redundante
        # não viu seu próprio #PLANO: anterior e fechou o ticket sem rotear pra ninguém).
        # _extract_plan_from_text só "acerta" se o texto tiver uma linha #PLANO: válida
        # com slugs de agente reais — isso já é filtro suficiente contra falso positivo.
        plan = _descobrir_plano_do_historico(history_tuples, issue_data)

    state_fresh = await mem.obter_estado_revisoes(issue_id)
    comentario_contadores = await _montar_comentario_contadores(issue_id, state_fresh)
    # Um único comentário (resposta + contadores) em vez de dois: Paperclip reacorda o
    # agente atribuído a cada comentário novo em um issue ("issue_commented"), e como a
    # reatribuição só acontece MAIS ABAIXO nesta função, cada comentário extra enquanto
    # ainda somos os assignees é um heartbeat redundante a mais nos consumindo TPM da
    # Groq à toa (confirmado num teste real: Head recebeu 3 heartbeats concorrentes pelo
    # próprio comentário antes de conseguir se reatribuir).
    try:
        await client.add_comment(issue_id, body=f"{output.raw_text}\n\n---\n{comentario_contadores}")
    except Exception as exc:  # noqa: BLE001
        log.warning("comment.add.failed", issue=issue_id, err=str(exc))

    # LLM indisponível E o próprio Head é quem falhou: não há pra quem devolver (Head é o
    # topo da cadeia de revisão), e a lógica de roteamento normal abaixo não faria nada
    # com stage_complete=False/review=None — deixando o ticket assignado ao Head, cujo
    # próprio comentário de erro reacordaria ele de novo (loop até o hard-cap). Bloqueia
    # explicitamente pra decisão humana, mesmo padrão da proteção de loop em
    # _process_agent_webhook.
    if output.llm_failed and agent_slug == "head" and not output.review:
        try:
            await client.update_issue(issue_id, status="blocked", clear_assignee_agent=True)
        except Exception as exc:  # noqa: BLE001
            log.error("llm_failed.head.block.falhou", issue=issue_id, err=str(exc))
        return

    proximo_slug: Optional[str] = None
    if output.review:
        alvo, motivo = output.review
        try:
            tuning = await runtime_config.obter_tuning_resumo()
            total, par_cnt = await mem.incrementar_revisao(
                issue_id,
                agent_slug,
                alvo,
                max_review_total=tuning.max_review_total,
                max_review_per_pair=tuning.max_review_per_pair,
            )
            log.info(
                "review.aplicada",
                issue=issue_id,
                from_=agent_slug,
                to=alvo,
                total=total,
                par=par_cnt,
            )
            proximo_slug = alvo
            # Marca que, quando `alvo` concluir, o controle volta para `agent_slug` — não
            # para o próximo passo do #PLANO: (ver tools_memoria.definir_retorno_pendente).
            await mem.definir_retorno_pendente(issue_id, alvo, agent_slug)
        except mem.ReviewLimitError as exc:
            log.warning("review.limit.exceeded", issue=issue_id, err=str(exc))
            await client.add_comment(
                issue_id,
                body=(
                    "**Limite de revisões atingido** — retornando ao Head para decisão humana.\n\n"
                    f"Detalhe: {exc}\n"
                ),
            )
            proximo_slug = "head"
    elif output.stage_complete:
        if agent_slug == "head":
            if plan:
                proximo_slug = plan[0]
            else:
                await client.add_comment(
                    issue_id,
                    body="Head não detectou plano e não há próximo agente. Fechando como concluído (fim do ciclo).",
                )
                proximo_slug = None
        else:
            retorno_pendente = await mem.obter_e_limpar_retorno_pendente(issue_id, agent_slug)
            if retorno_pendente:
                # Esta ETAPA_CONCLUIDA está fechando uma REVISAO_NECESSARIA ad-hoc —
                # volta para quem pediu, ignorando a posição de `agent_slug` no #PLANO:.
                proximo_slug = retorno_pendente
            elif not plan:
                proximo_slug = "head"
            else:
                proximo = _proximo_agente_do_plano(plan, agent_slug)
                if proximo is None:
                    proximo_slug = "head"
                else:
                    proximo_slug = proximo

    if agent_slug == "head" and proximo_slug is None and (output.stage_complete or not plan):
        try:
            await _finalizar_ou_abrir_gate_governanca(
                client, issue_id, issue_data, raw_comments, plan or [], company_id
            )
        except Exception as exc:  # noqa: BLE001
            log.error("head.fechamento.falhou", issue=issue_id, err=str(exc))
        return

    if agent_slug == "head" and plan and output.stage_complete and proximo_slug and proximo_slug != "head":
        pass
    elif proximo_slug == "head" and agent_slug not in ("head",):
        if plan:
            ultimo_esperado = plan[-1]
            if agent_slug == ultimo_esperado:
                try:
                    await _finalizar_ou_abrir_gate_governanca(
                        client, issue_id, issue_data, raw_comments, plan, company_id
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error("head.fechamento.falhou", issue=issue_id, err=str(exc))
                return

    if proximo_slug:
        target_id = await _encontrar_agente_id_por_slug(client, company_id, proximo_slug)
        if not target_id:
            log.warning(
                "agent_id.nao_encontrado",
                issue=issue_id,
                proximo=proximo_slug,
                acao="reatribuindo_head_ou_pausa",
            )
            head_id = await _encontrar_agente_id_por_slug(client, company_id, "head")
            if head_id:
                target_id = head_id
                proximo_slug = "head"
        if target_id:
            try:
                await client.assign_issue(issue_id, agent_id=target_id)
                new_status: Any = issue_data.get("status")
                if new_status in ("backlog", "todo"):
                    new_status = "in_progress"
                else:
                    new_status = None
                if new_status:
                    try:
                        await client.update_issue(issue_id, status=new_status)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                log.error("issue.reatribuir.falhou", issue=issue_id, to=proximo_slug, err=str(exc))
        else:
            await client.add_comment(
                issue_id,
                body=(
                    "Não consegui localizar o agent_id do próximo agente "
                    f"(`{proximo_slug}`). Requer intervenção humana para reatribuir."
                ),
            )


async def _safe_callback_heartbeat(
    client: PaperclipClient,
    run_id: str,
    status_: Literal["completed", "failed", "cancelled"],
    result: str,
) -> None:
    """Best-effort: o core do Paperclip não expõe POST /heartbeat-runs/:runId/callback
    (confirmado — não há essa rota em server/src/routes/agents.ts). O adapter http marca
    o run como concluído assim que o POST inicial responde 2xx, então esta chamada é
    apenas informativa quando/se o endpoint existir em versões futuras. O verdadeiro
    resultado da demanda (comentários, reatribuição, status, vault) já foi persistido
    via API antes desta chamada — uma falha aqui nunca deve derrubar o processamento."""
    try:
        await client.callback_heartbeat_run(run_id, status_, result=result)
    except Exception as exc:  # noqa: BLE001
        log.debug("heartbeat.callback.unavailable", run_id=run_id, status=status_, err=str(exc)[:200])


async def _process_curador(
    payload: HeartbeatPayload,
    client: PaperclipClient,
) -> None:
    results = await curador.executar_ciclo_curadoria(client=client)
    await _safe_callback_heartbeat(
        client,
        payload.runId,
        "completed",
        result=f"Curadoria semanal finalizada: {results}",
    )


async def _process_agent_webhook(
    agent_slug: str,
    payload: HeartbeatPayload,
    client: PaperclipClient,
) -> None:
    issue_id = payload.context.taskId
    if not await _check_loop_protection(issue_id):
        await _safe_callback_heartbeat(
            client,
            payload.runId,
            "failed",
            result="Hard loop protection: demasiados heartbeats em pouco tempo. Requer intervenção humana.",
        )
        if issue_id:
            # CRÍTICO: precisa desatribuir o ticket ANTES de comentar. Paperclip reacorda
            # o assignee atual a cada comentário novo — se só comentarmos sem desatribuir,
            # o próprio aviso de "loop detectado" reacorda o agente, que bate no cap nesse
            # heartbeat de novo, comenta de novo, reacorda de novo... um loop infinito do
            # próprio aviso de loop (confirmado ao vivo: o mesmo aviso postado dezenas de
            # vezes seguidas). Desatribuir primeiro garante que não sobra ninguém pra
            # Paperclip acordar depois deste comentário.
            try:
                await client.update_issue(issue_id, status="blocked", clear_assignee_agent=True)
            except Exception as exc:  # noqa: BLE001
                log.error("loop.unassign.failed", issue=issue_id, err=str(exc))
            try:
                await client.add_comment(
                    issue_id,
                    "**Atenção:** loop de revisões detectado e interrompido automaticamente. "
                    "Ticket desatribuído e marcado como bloqueado — requer decisão humana "
                    "(reatribuir manualmente para um agente) para prosseguir.",
                )
            except Exception:  # noqa: BLE001
                pass
        return

    log.info(
        "heartbeat.received",
        agent=agent_slug,
        run_id=payload.runId,
        issue_id=issue_id,
        reason=payload.context.wakeReason,
    )

    try:
        if agent_slug == "curador-skills":
            await _process_curador(payload, client)
        else:
            assert issue_id is not None
            # Serializa heartbeats concorrentes do MESMO ticket (ver comentário em
            # _issue_locks) — sem isso, dois heartbeats disputando o mesmo issue_id
            # fazem leitura-e-escrita intercalada e um desfaz a reatribuição do outro.
            async with _issue_locks[issue_id]:
                await _process_demanda_agent(agent_slug, payload, client)
            await _safe_callback_heartbeat(
                client,
                payload.runId,
                "completed",
                result=f"Agent {agent_slug} processou tarefa {issue_id}",
            )
    except PaperclipHTTPError as exc:
        log.error(
            "paperclip.http.error",
            agent=agent_slug,
            run_id=payload.runId,
            url=exc.url,
            status=exc.status_code,
            body=exc.text[:500],
        )
        await _safe_callback_heartbeat(client, payload.runId, "failed", result=f"Paperclip HTTP {exc.status_code}")
    except Exception as exc:  # noqa: BLE001
        log.exception("agent.worker.fatal", agent=agent_slug, run_id=payload.runId, err=str(exc))
        await _safe_callback_heartbeat(client, payload.runId, "failed", result=f"Fatal: {exc}")


async def _accept_heartbeat(
    agent_slug: str,
    payload: HeartbeatPayload,
    background: BackgroundTasks,
) -> dict[str, Any]:
    client = PaperclipClient(run_id=payload.runId)
    background.add_task(_process_agent_webhook, agent_slug, payload, client)
    return {
        "status": "accepted",
        "runId": payload.runId,
        "agent": agent_slug,
        "queuedAt": time.time(),
    }


@app.get("/health", tags=["meta"])
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "interestelar-harness",
        "version": "0.2.0",
        "time": time.time(),
        "vaultReady": settings.vault_path.exists(),
        "reposReady": settings.repositorios_path.exists(),
    }


def _make_route(agent_slug: str):
    async def _handler(
        payload: HeartbeatPayload,
        background: BackgroundTasks,
        request: Request,
        x_webhook_signature: Optional[str] = Header(default=None),
    ) -> dict[str, Any]:
        raw = await request.body()
        if not await _verify_webhook_signature(raw, x_webhook_signature):
            raise HTTPException(status_code=401, detail="invalid webhook signature")
        return await _accept_heartbeat(agent_slug, payload, background)

    return _handler


app.router.add_api_route("/webhook/head", _make_route("head"), methods=["POST"], status_code=status.HTTP_202_ACCEPTED, tags=["agentes"])
app.router.add_api_route("/webhook/po", _make_route("po"), methods=["POST"], status_code=status.HTTP_202_ACCEPTED, tags=["agentes"])
app.router.add_api_route("/webhook/arquiteto", _make_route("arquiteto"), methods=["POST"], status_code=status.HTTP_202_ACCEPTED, tags=["agentes"])
app.router.add_api_route("/webhook/engenheiro", _make_route("engenheiro"), methods=["POST"], status_code=status.HTTP_202_ACCEPTED, tags=["agentes"])
app.router.add_api_route("/webhook/governanca", _make_route("governanca"), methods=["POST"], status_code=status.HTTP_202_ACCEPTED, tags=["agentes"])
app.router.add_api_route("/webhook/analista", _make_route("analista"), methods=["POST"], status_code=status.HTTP_202_ACCEPTED, tags=["agentes"])
app.router.add_api_route("/webhook/curador-skills", _make_route("curador-skills"), methods=["POST"], status_code=status.HTTP_202_ACCEPTED, tags=["agentes"])


@app.post("/aprovar-skill/{nome}", tags=["curadoria"], dependencies=[Depends(exigir_auth_ui)])
async def aprovar_skill(nome: str, aprovada_por: str = "board") -> dict[str, Any]:
    pendente = Path("./skills_pendentes") / nome / "SKILL.md"
    destino = Path("./skills") / nome / "SKILL.md"
    if not pendente.exists():
        raise HTTPException(status_code=404, detail=f"skill pendente não encontrada: {nome}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    conteudo = pendente.read_text(encoding="utf-8")
    destino.write_text(conteudo, encoding="utf-8")
    fonte_hash = mem.hash_conteudo(conteudo)
    await mem.marcar_skill_aprovada(nome, aprovada_por=aprovada_por)
    try:
        _ = await mem.obter_ultimo_hash_skill_aprovado(nome)
    except Exception:  # noqa: BLE001
        pass
    try:
        pendente.unlink()
    except OSError as exc:
        log.warning("skill_pendente.remove_failed", nome=nome, err=str(exc))
    log.info("skill.aprovada", nome=nome, por=aprovada_por, hash=fonte_hash[:12])
    return {"status": "approved", "skill": nome, "applied": True, "aprovedBy": aprovada_por}
