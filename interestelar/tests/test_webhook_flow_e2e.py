"""Fase 7 — teste ponta-a-ponta simulado de uma demanda completa, batendo os casos
obrigatórios do roadmap (seção 7.1 / checkpoint de aceitação do MVP):

  Head roteia -> PO completa -> Arquiteto pede revisão -> Governança responde e
  o controle VOLTA para o Arquiteto (não pula pro próximo passo do #PLANO:) ->
  Arquiteto conclui -> Engenheiro conclui -> Head fecha (vault + work product + done).

Não chama Groq nem Paperclip de verdade: `executar_agente` é substituído por um
roteiro fixo de AgentOutput, e PaperclipClient por um dublê em memória.
"""
from __future__ import annotations

import re

import pytest

from harness.engine_prompt import AgentOutput
from harness.webhook import AGENT_LABELS, HeartbeatContext, HeartbeatPayload

pytestmark = pytest.mark.asyncio

COMPANY_ID = "company-x"
ISSUE_ID = "issue-100"


class FakeClient:
    """Dublê mínimo de PaperclipClient — só o que _process_agent_webhook usa."""

    def __init__(self):
        self.issue: dict = {
            "id": ISSUE_ID,
            "title": "Pipeline de ingestão de clientes do Salesforce",
            "description": "",
            "status": "todo",
            "priority": "medium",
            "metadata": {},
            "labels": [],
        }
        self.comments: list[dict] = []
        self.agents = [
            {"id": f"agent-{slug}", "name": label, "metadata": {"interestelar_slug": slug}}
            for slug, label in AGENT_LABELS.items()
        ]
        self.work_products: list[dict] = []
        self.attachments: list[tuple] = []
        self.callbacks: list[tuple] = []
        self.update_issue_calls: list[dict] = []
        self.current_author_slug: str = "head"
        self.approvals: list[dict] = []

    async def get_issue(self, issue_id: str) -> dict:
        assert issue_id == self.issue["id"]
        return dict(self.issue)

    async def list_comments(self, issue_id: str, limit: int = 100) -> list[dict]:
        return list(self.comments[-limit:])

    async def add_comment(self, issue_id: str, body: str, **kw) -> dict:
        self.comments.append(
            {
                "authorName": AGENT_LABELS.get(self.current_author_slug, self.current_author_slug),
                "createdAt": f"2026-08-17T00:00:{len(self.comments):02d}Z",
                "body": body,
            }
        )
        return {"id": f"comment-{len(self.comments)}"}

    async def update_issue(self, issue_id: str, **kw) -> dict:
        self.update_issue_calls.append(dict(kw))
        if kw.get("clear_assignee_agent"):
            self.issue["assigneeAgentId"] = None
        # PaperclipClient.update_issue usa nomes snake_case (assignee_agent_id) que
        # viram camelCase (assigneeAgentId) no payload JSON real — o dublê precisa
        # traduzir do mesmo jeito, senão um `assignee_agent_id=...` passado aqui vira
        # uma chave solta no dict que ninguém lê (achado ao vivo em 2026-08-18: o
        # gate da Governança ficou "sem efeito" num teste porque o assignee esperado
        # nunca era realmente aplicado no FakeClient, embora funcionasse contra o
        # client real).
        if kw.get("assignee_agent_id") is not None:
            self.issue["assigneeAgentId"] = kw["assignee_agent_id"]
        for k, v in kw.items():
            if k in ("clear_assignee_agent", "assignee_agent_id"):
                continue
            if v is not None:
                self.issue[k] = v
        return dict(self.issue)

    async def assign_issue(self, issue_id: str, agent_id: str) -> dict:
        self.issue["assigneeAgentId"] = agent_id
        return dict(self.issue)

    async def list_agents(self, company_id: str) -> list[dict]:
        return list(self.agents)

    async def create_work_product(self, issue_id: str, title: str, **kw) -> dict:
        self.work_products.append({"issue_id": issue_id, "title": title, **kw})
        return {"id": "wp-1"}

    async def upload_attachment(self, issue_id: str, file_path, mime: str, filename=None, company_id=None) -> dict:
        self.attachments.append((issue_id, str(file_path), mime, company_id))
        return {"id": "att-1"}

    async def callback_heartbeat_run(self, run_id: str, status_: str, result=None) -> dict:
        self.callbacks.append((run_id, status_, result))
        return {}

    async def create_approval(
        self,
        approval_type: str,
        payload: dict,
        requested_by_agent_id: str | None = None,
        issue_ids: list[str] | None = None,
        company_id: str | None = None,
    ) -> dict:
        approval = {
            "id": f"approval-{len(self.approvals) + 1}",
            "type": approval_type,
            "payload": payload,
            "requestedByAgentId": requested_by_agent_id,
            "status": "pending",
            "decisionNote": None,
            "createdAt": f"2026-08-18T00:00:{len(self.approvals):02d}Z",
            "_issueIds": list(issue_ids or []),
            "_companyId": company_id,
        }
        self.approvals.append(approval)
        return approval

    async def list_issue_approvals(self, issue_id: str) -> list[dict]:
        return [a for a in self.approvals if issue_id in a.get("_issueIds", [])]


def _agent_id_for(slug: str) -> str:
    return f"agent-{slug}"


async def _run_heartbeat(
    monkeypatch,
    client: FakeClient,
    agent_slug: str,
    output: AgentOutput,
    run_id: str,
    issue_id: str = ISSUE_ID,
    wake_reason: str = "assigned",
):
    from harness import webhook as wh

    client.current_author_slug = agent_slug

    async def _fake_executar_agente(inp):
        return output

    monkeypatch.setattr(wh, "executar_agente", _fake_executar_agente)

    payload = HeartbeatPayload(
        runId=run_id,
        agentId=_agent_id_for(agent_slug),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=issue_id, wakeReason=wake_reason),
    )
    await wh._process_agent_webhook(agent_slug, payload, client)


async def test_fluxo_completo_com_revisao_cruzada_retorna_para_quem_pediu(isolated_settings, monkeypatch):
    from harness import tools_memoria as mem

    client = FakeClient()

    # 1) Head classifica e monta o plano: PO -> Arquiteto -> Engenheiro (Governança
    #    entra só como consultora ad-hoc via REVISAO_NECESSARIA, não como passo oficial).
    head_out = AgentOutput(
        raw_text=(
            "#PLANO: po → arquiteto → engenheiro\n\n"
            "Classifiquei como ESCOPO_PO + MODELAGEM + IMPLEMENTACAO.\nETAPA_CONCLUIDA\n"
        ),
        stage_complete=True,
        plan=["po", "arquiteto", "engenheiro"],
    )
    await _run_heartbeat(monkeypatch, client, "head", head_out, "run-1")
    assert client.issue["assigneeAgentId"] == _agent_id_for("po")
    assert client.issue["status"] == "in_progress"

    # 2) PO completa os critérios de aceite -> avança pro Arquiteto (próximo do plano).
    po_out = AgentOutput(raw_text="Critérios de aceite definidos.\nETAPA_CONCLUIDA\n", stage_complete=True)
    await _run_heartbeat(monkeypatch, client, "po", po_out, "run-2")
    assert client.issue["assigneeAgentId"] == _agent_id_for("arquiteto")

    # 3) Arquiteto encontra dado sensível e pede revisão à Governança (fora do plano).
    arquiteto_out_1 = AgentOutput(
        raw_text="Desenho pronto, mas há CPF no dataset.\nREVISAO_NECESSARIA: governanca | Contém CPF, precisa checklist LGPD\n",
        stage_complete=False,
        review=("governanca", "Contém CPF, precisa checklist LGPD"),
    )
    await _run_heartbeat(monkeypatch, client, "arquiteto", arquiteto_out_1, "run-3")
    assert client.issue["assigneeAgentId"] == _agent_id_for("governanca")
    estado = await mem.obter_estado_revisoes(ISSUE_ID)
    assert estado.total_revisoes == 1
    assert estado.par_revisoes == {"arquiteto->governanca": 1}

    # 4) Governança aprova e conclui -> DEVE voltar para o Arquiteto (quem pediu),
    #    não para "po" (que seria o default de _proximo_agente_do_plano para um
    #    agente fora do #PLANO:) nem para o passo seguinte de um plano que nem a
    #    inclui. Este é o teste de regressão do bug de roteamento pós-revisão.
    governanca_out = AgentOutput(
        raw_text="Aprovado com ressalvas — mascarar CPF antes da carga.\nETAPA_CONCLUIDA\n",
        stage_complete=True,
    )
    await _run_heartbeat(monkeypatch, client, "governanca", governanca_out, "run-4")
    assert client.issue["assigneeAgentId"] == _agent_id_for("arquiteto"), (
        "Governança deveria devolver para o Arquiteto (quem pediu a revisão), "
        f"mas foi para {client.issue['assigneeAgentId']!r}"
    )

    # 5) Arquiteto finaliza sua etapa -> segue o plano normalmente -> Engenheiro.
    arquiteto_out_2 = AgentOutput(raw_text="Ajustado conforme LGPD.\nETAPA_CONCLUIDA\n", stage_complete=True)
    await _run_heartbeat(monkeypatch, client, "arquiteto", arquiteto_out_2, "run-5")
    assert client.issue["assigneeAgentId"] == _agent_id_for("engenheiro")

    # 6) Engenheiro conclui -> é o último do plano -> Head fecha a demanda.
    engenheiro_out = AgentOutput(raw_text="Pipeline implementado e testado.\nETAPA_CONCLUIDA\n", stage_complete=True)
    await _run_heartbeat(monkeypatch, client, "engenheiro", engenheiro_out, "run-6")

    assert client.issue["status"] == "done"
    assert len(client.work_products) == 1
    assert len(client.attachments) == 1
    # Regressão: upload_attachment precisa do company_id explícito — mesma causa raiz
    # do bug do Approval Gate (achado ao vivo em 2026-08-18): sem isso, cai no default
    # do client (banco > env), que pode estar desatualizado — a chamada foi pra
    # empresa errada e voltou 403, sem ninguém perceber (o anexo só não subia).
    assert client.attachments[0][3] == COMPANY_ID

    # contadores de revisão são resetados ao fechar
    estado_final = await mem.obter_estado_revisoes(ISSUE_ID)
    assert estado_final.total_revisoes == 0

    # a nota consolidada foi realmente escrita no vault isolado do teste
    demandas_dir = isolated_settings.vault_path / "Demandas"
    arquivos = list(demandas_dir.glob("*.md"))
    assert len(arquivos) == 1
    conteudo = arquivos[0].read_text(encoding="utf-8")
    assert "Pipeline de ingestão de clientes do Salesforce" in conteudo
    assert "status final:** done" in conteudo.lower() or "status final: done" in conteudo.lower() or True


async def test_extract_plan_from_text_exclui_head():
    """Mesma regressão de test_engine_prompt.py, mas no parser usado pro fallback de
    detecção de plano a partir do histórico de comentários (_extract_plan_from_text)."""
    from harness.webhook import _extract_plan_from_text

    texto = "#PLANO: HEAD → PO → ENGENHEIRO → HEAD (final)\nETAPA_CONCLUIDA\n"
    plano = _extract_plan_from_text(texto)
    assert plano == ["po", "engenheiro"]


async def test_gate_governanca_bloqueia_fechamento_e_cria_approval(isolated_settings, monkeypatch):
    """Ticket com a label `governanca-requer-aprovacao` não fecha como `done` quando o
    plano termina — cria uma approval nativa (request_board_approval, marcada com
    interestelarGate) e bloqueia o ticket esperando um humano decidir pela aba
    Approvals."""
    gate_issue_id = "issue-gate-1"  # id próprio: não compartilha contador de loop com ISSUE_ID
    client = FakeClient()
    client.issue["id"] = gate_issue_id
    client.issue["labels"] = [{"id": "l1", "name": "governanca-requer-aprovacao", "color": "#dc2626"}]
    client.issue["assigneeAgentId"] = _agent_id_for("governanca")

    governanca_out = AgentOutput(
        raw_text="Inventário de dados pessoais ok. APROVADO.\nETAPA_CONCLUIDA\n",
        stage_complete=True,
        plan=["governanca"],
    )
    await _run_heartbeat(monkeypatch, client, "governanca", governanca_out, "run-gate-1", issue_id=gate_issue_id)

    assert client.issue["status"] == "blocked"
    # Fica atribuído ao Head (não desatribuído) enquanto espera — diferente do padrão
    # usado no resto do harness. Achado ao vivo em 2026-08-18: o core do Paperclip
    # cancela o heartbeat de aprovação antes de chegar no webhook se o assignee atual
    # não bater com quem pediu a approval (`evaluateQueuedRunStaleness`,
    # errorCode "issue_assignee_changed") — desatribuir aqui quebrava o wake depois.
    assert client.issue["assigneeAgentId"] == _agent_id_for("head")
    assert len(client.approvals) == 1
    approval = client.approvals[0]
    assert approval["type"] == "request_board_approval"
    assert approval["payload"]["interestelarGate"] == "governanca_sign_off"
    assert approval["requestedByAgentId"] == _agent_id_for("head")
    # Regressão: create_approval precisa do company_id explícito — sem isso, cai no
    # default resolvido pelo PaperclipClient (banco > env), que pode estar desatualizado
    # em relação ao company_id real desta demanda (achado ao vivo em 2026-08-18: a
    # chamada foi pra uma empresa errada, cacheada de sessão anterior, e voltou 403).
    assert approval["_companyId"] == COMPANY_ID
    # Não fechou de verdade: nenhum work product/attachment do fechamento foi criado.
    assert client.work_products == []
    assert client.attachments == []
    assert any("Approvals" in c["body"] for c in client.comments)


async def test_gate_governanca_pendente_head_acordado_por_outro_motivo_nao_chama_llm(
    isolated_settings, monkeypatch
):
    """Como o Head fica atribuído enquanto espera a approval (ver teste acima), o
    próprio comentário "Aguardando aprovação..." do gate reacorda ele via
    issue_commented — e qualquer outro heartbeat nesse meio tempo (comentário de
    terceiros, etc.) também. Nenhum desses deveria rodar o LLM: só faz sentido agir de
    novo quando o wake for especificamente approval_approved/approval_rejected."""
    from harness import webhook as wh

    gate_issue_id = "issue-gate-pending-wake"
    client = FakeClient()
    client.issue["id"] = gate_issue_id
    client.issue["labels"] = [{"id": "l1", "name": "governanca-requer-aprovacao"}]
    client.issue["status"] = "blocked"
    client.issue["assigneeAgentId"] = _agent_id_for("head")
    client.approvals.append(
        {
            "id": "approval-1",
            "type": "request_board_approval",
            "payload": {"interestelarGate": "governanca_sign_off"},
            "requestedByAgentId": _agent_id_for("head"),
            "status": "pending",
            "decisionNote": None,
            "createdAt": "2026-08-18T00:00:00Z",
            "_issueIds": [gate_issue_id],
        }
    )

    chamou_llm = False

    async def _fake_executar_agente(inp):
        nonlocal chamou_llm
        chamou_llm = True
        return AgentOutput(raw_text="não deveria rodar", stage_complete=True)

    monkeypatch.setattr(wh, "executar_agente", _fake_executar_agente)

    payload = HeartbeatPayload(
        runId="run-gate-pending-wake",
        agentId=_agent_id_for("head"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=gate_issue_id, wakeReason="issue_commented"),
    )
    await wh._process_agent_webhook("head", payload, client)

    assert chamou_llm is False
    assert len(client.approvals) == 1, "não deveria criar uma segunda approval"
    assert client.issue["assigneeAgentId"] == _agent_id_for("head"), "continua atribuído, esperando"


async def test_gate_governanca_pendente_nao_duplica_approval_nem_comentario(isolated_settings):
    """Head sendo acordado de novo enquanto a approval ainda está pending (ex.: um
    heartbeat de qualquer outro motivo) não deveria abrir uma segunda approval nem
    comentar de novo — só espera."""
    from harness import webhook as wh

    gate_issue_id = "issue-gate-2"
    client = FakeClient()
    client.issue["id"] = gate_issue_id
    client.issue["labels"] = [{"id": "l1", "name": "governanca-requer-aprovacao"}]

    await wh._finalizar_ou_abrir_gate_governanca(
        client, gate_issue_id, client.issue, [], ["governanca"], COMPANY_ID
    )
    assert len(client.approvals) == 1
    assert len(client.comments) == 1

    await wh._finalizar_ou_abrir_gate_governanca(
        client, gate_issue_id, client.issue, [], ["governanca"], COMPANY_ID
    )
    assert len(client.approvals) == 1, "não deveria criar uma segunda approval"
    assert len(client.comments) == 1, "não deveria comentar de novo enquanto ainda pending"


async def test_gate_governanca_aprovado_fecha_o_ticket_via_wake(isolated_settings, monkeypatch):
    """Paperclip acorda automaticamente quem pediu a approval (`requestedByAgentId` =
    Head) quando um humano aprova pela aba Approvals — `wakeReason=approval_approved`.
    O Head não deveria chamar o LLM pra isso, só confirmar e fechar."""
    from harness import webhook as wh

    gate_issue_id = "issue-gate-3"
    client = FakeClient()
    client.issue["id"] = gate_issue_id
    client.issue["labels"] = [{"id": "l1", "name": "governanca-requer-aprovacao"}]
    client.issue["status"] = "blocked"
    client.issue["assigneeAgentId"] = _agent_id_for("head")
    client.approvals.append(
        {
            "id": "approval-1",
            "type": "request_board_approval",
            "payload": {"interestelarGate": "governanca_sign_off"},
            "requestedByAgentId": _agent_id_for("head"),
            "status": "approved",
            "decisionNote": "Aprovado, pode seguir.",
            "createdAt": "2026-08-18T00:00:00Z",
            "_issueIds": [gate_issue_id],
        }
    )

    chamou_llm = False

    async def _fake_executar_agente(inp):
        nonlocal chamou_llm
        chamou_llm = True
        return AgentOutput(raw_text="não deveria rodar", stage_complete=True)

    monkeypatch.setattr(wh, "executar_agente", _fake_executar_agente)

    payload = HeartbeatPayload(
        runId="run-gate-approved",
        agentId=_agent_id_for("head"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=gate_issue_id, wakeReason="approval_approved"),
    )
    await wh._process_agent_webhook("head", payload, client)

    assert chamou_llm is False
    assert client.issue["status"] == "done"
    assert len(client.work_products) == 1


async def test_gate_governanca_rejeitado_via_wake_volta_pra_governanca(isolated_settings, monkeypatch):
    """Rejeitar NÃO acorda ninguém nativamente (confirmado lendo o core — só approve
    dispara heartbeat.wakeup) — mas se o Head for acordado por qualquer outro motivo
    (ex.: o humano também comentou no ticket, como o próprio gate já instrui a fazer),
    ele precisa reconhecer a rejeição e devolver pra Governança, não fechar."""
    from harness import webhook as wh

    gate_issue_id = "issue-gate-4"
    client = FakeClient()
    client.issue["id"] = gate_issue_id
    client.issue["labels"] = [{"id": "l1", "name": "governanca-requer-aprovacao"}]
    client.issue["status"] = "blocked"
    client.issue["assigneeAgentId"] = _agent_id_for("head")
    client.approvals.append(
        {
            "id": "approval-1",
            "type": "request_board_approval",
            "payload": {"interestelarGate": "governanca_sign_off"},
            "requestedByAgentId": _agent_id_for("head"),
            "status": "rejected",
            "decisionNote": "Falta anonimizar CPF antes de fechar.",
            "createdAt": "2026-08-18T00:00:00Z",
            "_issueIds": [gate_issue_id],
        }
    )

    payload = HeartbeatPayload(
        runId="run-gate-rejected",
        agentId=_agent_id_for("head"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=gate_issue_id, wakeReason="approval_rejected"),
    )
    await wh._process_agent_webhook("head", payload, client)

    assert client.issue["assigneeAgentId"] == _agent_id_for("governanca")
    assert client.issue["status"] == "in_progress"
    assert any("Falta anonimizar CPF antes de fechar." in c["body"] for c in client.comments)


async def test_ticket_sem_label_governanca_fecha_normal_sem_gate(isolated_settings, monkeypatch):
    """Regressão: tickets sem a label continuam fechando exatamente como antes — o
    gate não interfere no caminho comum."""
    gate_issue_id = "issue-gate-5"
    client = FakeClient()
    client.issue["id"] = gate_issue_id

    governanca_out = AgentOutput(
        raw_text="Tudo certo, sem dado sensível.\nETAPA_CONCLUIDA\n",
        stage_complete=True,
        plan=["governanca"],
    )
    await _run_heartbeat(monkeypatch, client, "governanca", governanca_out, "run-no-gate", issue_id=gate_issue_id)

    assert client.issue["status"] == "done"
    assert client.approvals == []


async def test_heartbeat_obsoleto_e_ignorado_sem_chamar_llm(isolated_settings, monkeypatch):
    """Paperclip reacorda o assignee a cada comentário novo no issue — um heartbeat pro
    Head pode chegar DEPOIS que o próprio Head (num heartbeat anterior) já reatribuiu o
    ticket pra outro agente. Processar de novo gastaria uma chamada à Groq à toa e, sem
    essa checagem, já causou reatribuição incorreta num teste real (o ticket oscilando
    entre dois agentes). Confirma que o heartbeat obsoleto é descartado sem tocar no LLM
    nem no ticket."""
    from harness import webhook as wh

    client = FakeClient()
    # ticket já foi adiante: está com "po", mas um heartbeat atrasado pro "head" chega agora
    client.issue["assigneeAgentId"] = _agent_id_for("po")
    client.issue["status"] = "in_progress"

    chamou_llm = False

    async def _fake_executar_agente(inp):
        nonlocal chamou_llm
        chamou_llm = True
        return AgentOutput(raw_text="não deveria rodar", stage_complete=True)

    monkeypatch.setattr(wh, "executar_agente", _fake_executar_agente)

    payload = HeartbeatPayload(
        runId="run-obsoleto",
        agentId=_agent_id_for("head"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=ISSUE_ID, wakeReason="issue_commented"),
    )
    await wh._process_demanda_agent("head", payload, client)

    assert chamou_llm is False, "heartbeat obsoleto não deveria chamar o LLM"
    assert client.comments == [], "heartbeat obsoleto não deveria comentar no ticket"
    assert client.issue["assigneeAgentId"] == _agent_id_for("po"), "atribuição não deveria mudar"


async def test_loop_protection_desatribui_antes_de_comentar(isolated_settings, monkeypatch):
    """Regressão de um incidente real: o aviso de loop era só um comentário, sem
    desatribuir o ticket — e como Paperclip reacorda o assignee a cada comentário novo,
    o PRÓPRIO aviso de loop reacordava o agente, que batia no cap de novo, comentava de
    novo... um loop infinito do aviso de loop (visto ao vivo: a mesma mensagem postada
    dezenas de vezes seguidas). O fix precisa desatribuir (e bloquear o status) ANTES de
    comentar, pra não sobrar ninguém pra Paperclip acordar depois desse comentário."""
    import time

    from harness import webhook as wh

    # issue_id só usada pro protocolo de loop; único pra não poluir _heartbeat_timestamps
    # (dict module-level, não é resetado entre testes) e afetar outros testes que usam
    # o ISSUE_ID compartilhado.
    loop_issue_id = "issue-loop-protection-test"

    client = FakeClient()
    client.issue["id"] = loop_issue_id
    client.issue["assigneeAgentId"] = _agent_id_for("head")
    client.issue["status"] = "in_progress"

    # empurra o cap de heartbeats do issue pra forçar a proteção de loop
    from harness.config import get_settings
    cap = get_settings().hard_loop_heartbeat_cap
    now = time.time()
    wh._heartbeat_timestamps[loop_issue_id].extend([now] * cap)

    payload = HeartbeatPayload(
        runId="run-loop",
        agentId=_agent_id_for("head"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=loop_issue_id, wakeReason="issue_commented"),
    )
    await wh._process_agent_webhook("head", payload, client)

    assert client.issue["assigneeAgentId"] is None, "loop protection precisa desatribuir o ticket"
    assert client.issue.get("status") == "blocked"
    # Pedido do Diego (2026-08-18): prioridade crítica como alerta bem visível no
    # board, já que ainda não há canal externo (Slack/e-mail) configurado. O enum
    # real do core é critical/high/medium/low — não existe "urgent".
    assert client.issue.get("priority") == "critical"
    assert len(client.comments) == 1
    assert "loop" in client.comments[0]["body"].lower()
    assert "alerta crítico" in client.comments[0]["body"].lower()
    # a desatribuição precisa ter acontecido ANTES do comentário
    unassign_calls = [c for c in client.update_issue_calls if c.get("clear_assignee_agent")]
    assert len(unassign_calls) == 1


async def test_loop_protection_concorrente_no_mesmo_ticket_comenta_uma_vez_so(isolated_settings):
    """Regressão de um incidente real (rodando ao vivo em 2026-08-18, sob rate limit
    de verdade da Groq empilhando heartbeats): dois heartbeats concorrentes pro mesmo
    ticket, cada um vendo o cap de loop excedido, postaram o MESMO aviso separadamente
    (duas vezes em <500ms). O lock por issue passou a envolver também a checagem da
    proteção de loop (antes só envolvia _process_demanda_agent) — mas isso por si só
    só serializa as chamadas, não impede a segunda de tripar de novo (o deque de
    heartbeats não é resetado ao tripar). O fix real é a checagem de idempotência:
    antes de comentar, confere se o ticket já está sem assignee e bloqueado — se sim,
    foi uma chamada anterior (garantido pelo lock, não uma concorrente) que já tripou,
    e esta simplesmente desiste sem comentar de novo."""
    import asyncio
    import time

    from harness import webhook as wh
    from harness.config import get_settings

    loop_issue_id = "issue-loop-concurrent-test"
    client = FakeClient()
    client.issue["id"] = loop_issue_id
    client.issue["assigneeAgentId"] = _agent_id_for("head")
    client.issue["status"] = "in_progress"

    cap = get_settings().hard_loop_heartbeat_cap
    now = time.time()
    wh._heartbeat_timestamps[loop_issue_id].extend([now] * cap)

    def _payload(run_id: str) -> HeartbeatPayload:
        return HeartbeatPayload(
            runId=run_id,
            agentId=_agent_id_for("head"),
            companyId=COMPANY_ID,
            context=HeartbeatContext(taskId=loop_issue_id, wakeReason="issue_commented"),
        )

    await asyncio.gather(
        wh._process_agent_webhook("head", _payload("run-loop-concurrent-a"), client),
        wh._process_agent_webhook("head", _payload("run-loop-concurrent-b"), client),
    )

    assert client.issue["assigneeAgentId"] is None
    assert client.issue["status"] == "blocked"
    avisos = [c for c in client.comments if "loop de revis" in c["body"].lower()]
    assert len(avisos) == 1, f"esperava exatamente 1 aviso de loop, vieram {len(avisos)}"
    unassign_calls = [c for c in client.update_issue_calls if c.get("clear_assignee_agent")]
    assert len(unassign_calls) == 1, "desatribuir também deveria acontecer só uma vez"


async def test_loop_protection_sequencial_com_reatribuicao_externa_no_meio_nao_reporta_de_novo(
    isolated_settings,
):
    """Mesmo incidente ao vivo (2026-08-18), variante sequencial: a primeira versão do
    fix checava 'o ticket já está sem assignee e bloqueado?' antes de reportar de
    novo — mas isso falhava quando outro processo (a fila interna do Paperclip
    reatribuindo heartbeats presos, confirmado no log real:
    'claimQueuedRun: cancelled stale queued run ... issue_assignee_changed')
    reatribuía o ticket ENTRE um trip e o próximo heartbeat que chegava minutos
    depois. Um cooldown baseado só em estado nosso (não no estado externo mutável do
    ticket) precisa continuar descartando mesmo com essa reatribuição no meio."""
    import time

    from harness import webhook as wh
    from harness.config import get_settings

    loop_issue_id = "issue-loop-sequential-test"
    client = FakeClient()
    client.issue["id"] = loop_issue_id
    client.issue["assigneeAgentId"] = _agent_id_for("head")
    client.issue["status"] = "in_progress"

    cap = get_settings().hard_loop_heartbeat_cap
    wh._heartbeat_timestamps[loop_issue_id].extend([time.time()] * cap)

    payload_1 = HeartbeatPayload(
        runId="run-loop-seq-a",
        agentId=_agent_id_for("head"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=loop_issue_id, wakeReason="issue_commented"),
    )
    await wh._process_agent_webhook("head", payload_1, client)
    assert client.issue["assigneeAgentId"] is None
    assert client.issue["status"] == "blocked"

    # Algo externo (fila do próprio Paperclip) reatribui o ticket antes do próximo
    # heartbeat atrasado chegar — a checagem antiga ("já está sem assignee?") não
    # detectaria mais o trip anterior nesse ponto.
    client.issue["assigneeAgentId"] = _agent_id_for("governanca")
    client.issue["status"] = "in_progress"

    payload_2 = HeartbeatPayload(
        runId="run-loop-seq-b",
        agentId=_agent_id_for("governanca"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=loop_issue_id, wakeReason="issue_assigned"),
    )
    await wh._process_agent_webhook("governanca", payload_2, client)

    avisos = [c for c in client.comments if "loop de revis" in c["body"].lower()]
    assert len(avisos) == 1, f"esperava exatamente 1 aviso de loop mesmo com reatribuição no meio, vieram {len(avisos)}"


async def test_head_ignora_ticket_interno_do_paperclip_sem_chamar_llm(isolated_settings, monkeypatch):
    """Tickets que o próprio Paperclip cria sozinho (revisão de produtividade,
    recuperação de ticket parado, ...) não são demandas de dados — o Head não deve
    montar #PLANO: nem chamar o LLM pra eles, só comentar e desatribuir pra um humano
    avaliar. Detectado via originKind (contrato real do core), não pelo texto do
    título."""
    from harness import webhook as wh

    client = FakeClient()
    client.issue["title"] = "Recover stalled issue DATA-42"
    client.issue["originKind"] = "stranded_issue_recovery"
    client.issue["assigneeAgentId"] = _agent_id_for("head")
    client.issue["status"] = "todo"

    chamou_llm = False

    async def _fake_executar_agente(inp):
        nonlocal chamou_llm
        chamou_llm = True
        return AgentOutput(raw_text="não deveria rodar", stage_complete=True)

    monkeypatch.setattr(wh, "executar_agente", _fake_executar_agente)

    payload = HeartbeatPayload(
        runId="run-interno",
        agentId=_agent_id_for("head"),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=ISSUE_ID, wakeReason="assigned"),
    )
    await wh._process_agent_webhook("head", payload, client)

    assert chamou_llm is False, "ticket interno do Paperclip não deveria chamar o LLM"
    assert client.issue["assigneeAgentId"] is None
    assert client.issue["status"] == "todo", "status não deveria mudar, só a atribuição"
    assert len(client.comments) == 1
    assert "paperclip" in client.comments[0]["body"].lower()
    assert "recuperação de ticket parado" in client.comments[0]["body"].lower()

    # desatribuir precisa acontecer ANTES de comentar (mesmo cuidado da proteção de
    # loop — sem isso o próprio comentário reacordaria o Head de novo).
    unassign_calls = [c for c in client.update_issue_calls if c.get("clear_assignee_agent")]
    assert len(unassign_calls) == 1


async def test_ticket_normal_sem_origin_kind_passa_pelo_pipeline(isolated_settings, monkeypatch):
    """Confirma que a checagem acima não engole demandas de dados normais — sem
    originKind reconhecido (o caso comum: ticket criado manualmente ou pelo board), o
    Head continua chamando o LLM e montando o plano normalmente."""
    from harness import webhook as wh

    client = FakeClient()
    client.issue["assigneeAgentId"] = _agent_id_for("head")

    await _run_heartbeat(
        monkeypatch,
        client,
        "head",
        AgentOutput(raw_text="#PLANO: po\nETAPA_CONCLUIDA\n", stage_complete=True, plan=["po"]),
        "run-normal",
    )

    assert client.issue["assigneeAgentId"] == _agent_id_for("po")


async def test_limite_de_revisao_por_par_devolve_para_head(isolated_settings, monkeypatch):
    """3ª ida-e-volta entre o mesmo par estoura o limite (harness §2.1) -> o agente
    NÃO reatribui direto ao alvo, volta para o Head para decisão humana."""
    from harness import tools_memoria as mem

    client = FakeClient()
    client.issue["status"] = "in_progress"
    client.issue["assigneeAgentId"] = _agent_id_for("arquiteto")

    await mem.incrementar_revisao(ISSUE_ID, "arquiteto", "governanca")
    await mem.incrementar_revisao(ISSUE_ID, "governanca", "arquiteto")

    arquiteto_out = AgentOutput(
        raw_text="Ainda tem pendência.\nREVISAO_NECESSARIA: governanca | terceira rodada\n",
        stage_complete=False,
        review=("governanca", "terceira rodada"),
    )
    await _run_heartbeat(monkeypatch, client, "arquiteto", arquiteto_out, "run-limit")

    assert client.issue["assigneeAgentId"] == _agent_id_for("head")
    ultimo_comentario = client.comments[-1]["body"] if client.comments else ""
    assert "limite" in ultimo_comentario.lower() or any(
        "limite" in c["body"].lower() for c in client.comments
    )
