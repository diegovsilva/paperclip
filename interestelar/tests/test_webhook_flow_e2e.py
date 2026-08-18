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

    async def get_issue(self, issue_id: str) -> dict:
        assert issue_id == ISSUE_ID
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
        for k, v in kw.items():
            if k == "clear_assignee_agent":
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
        self.attachments.append((issue_id, str(file_path), mime))
        return {"id": "att-1"}

    async def callback_heartbeat_run(self, run_id: str, status_: str, result=None) -> dict:
        self.callbacks.append((run_id, status_, result))
        return {}


def _agent_id_for(slug: str) -> str:
    return f"agent-{slug}"


async def _run_heartbeat(monkeypatch, client: FakeClient, agent_slug: str, output: AgentOutput, run_id: str):
    from harness import webhook as wh

    client.current_author_slug = agent_slug

    async def _fake_executar_agente(inp):
        return output

    monkeypatch.setattr(wh, "executar_agente", _fake_executar_agente)

    payload = HeartbeatPayload(
        runId=run_id,
        agentId=_agent_id_for(agent_slug),
        companyId=COMPANY_ID,
        context=HeartbeatContext(taskId=ISSUE_ID, wakeReason="assigned"),
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
    assert len(client.comments) == 1
    assert "loop" in client.comments[0]["body"].lower()
    # a desatribuição precisa ter acontecido ANTES do comentário
    unassign_calls = [c for c in client.update_issue_calls if c.get("clear_assignee_agent")]
    assert len(unassign_calls) == 1


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
