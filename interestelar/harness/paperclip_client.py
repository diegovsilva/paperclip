from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

import httpx

from .config import Settings, get_settings
from .logging_setup import setup_logging

log = setup_logging()

IssueStatus = Literal[
    "backlog", "todo", "in_progress", "in_review", "blocked", "done", "cancelled"
]
IssuePriority = Literal["low", "medium", "high", "urgent"]
# Precisa bater exatamente com AGENT_ROLES em packages/shared/src/constants.ts —
# o Zod schema (createAgentSchema) rejeita (400) qualquer valor fora desta lista.
AgentRole = Literal[
    "ceo", "cto", "cmo", "cfo", "security", "engineer", "designer",
    "pm", "qa", "devops", "researcher", "general",
]


class PaperclipError(Exception):
    pass


class PaperclipHTTPError(PaperclipError):
    def __init__(self, status_code: int, text: str, url: str):
        self.status_code = status_code
        self.text = text
        self.url = url
        super().__init__(f"Paperclip HTTP {status_code} on {url}: {text[:300]}")


@dataclass
class AgentRef:
    id: str
    name: str
    company_id: str


@dataclass
class IssueRef:
    id: str
    title: str
    status: IssueStatus
    identifier: Optional[str] = None


class PaperclipClient:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        timeout: Optional[float] = None,
        run_id: Optional[str] = None,
    ):
        self.settings = settings or get_settings()
        self.timeout = timeout or float(self.settings.http_request_timeout_sec)
        self.base_url = self.settings.paperclip_api_url.rstrip("/")
        self.api_key = self.settings.paperclip_api_key.get_secret_value()
        self.company_id = self.settings.paperclip_company_id
        # Sem isso, o core não tem como associar as chamadas desta run (em especial o
        # comentário que add_comment posta) ao heartbeat run que a originou — a chave de
        # board usada aqui não carrega runId sozinha. server/src/services/heartbeat.ts só
        # pula o comentário de fallback automático ("HTTP POST <url>", o resumo cru do
        # adapter http) quando encontra um comentário já registrado com
        # createdByRunId=runId (findRunIssueComment); sem o header, ele nunca encontra e
        # posta o fallback redundante a cada heartbeat (confirmado num teste real: toda
        # chamada ao webhook virava um comentário extra "HTTP POST http://harness:8000/
        # webhook/head" na timeline, sobrepondo o comentário de verdade que a gente já
        # tinha postado pra mesma run).
        self.run_id = run_id
        # api_key/company_id acima são só o default do .env — _ensure_dynamic_config
        # (chamado no início de _request/_require_company_id) sobrescreve com o valor
        # da página /config se um estiver salvo lá, sem precisar reiniciar o harness.
        # Resolvido no máximo uma vez por instância (self._dynamic_resolvido).
        self._dynamic_resolvido = False
        if not self.api_key:
            log.warning("paperclip.api_key.empty")

    async def _ensure_dynamic_config(self) -> None:
        if self._dynamic_resolvido:
            return
        self._dynamic_resolvido = True
        from . import runtime_config as rc

        api_key = await rc.resolver_paperclip_api_key()
        company_id = await rc.resolver_paperclip_company_id()
        if api_key:
            self.api_key = api_key
        if company_id:
            self.company_id = company_id

    def _headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        h: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        # Sem isso, api_key="" gera "Authorization: Bearer " (espaço sobrando no final) —
        # httpx/httpcore rejeita como header ilegal (LocalProtocolError) ANTES de sequer
        # tentar a requisição, mascarando o erro real (que seria um 401 do servidor,
        # avisando pra configurar PAPERCLIP_API_KEY).
        if self.run_id:
            h["X-Paperclip-Run-Id"] = self.run_id
        if extra:
            h.update(extra)
        return h

    async def _require_company_id(self, override: Optional[str]) -> str:
        await self._ensure_dynamic_config()
        cid = override or self.company_id
        if not cid:
            raise PaperclipError("paperclip.company_id.missing: configure PAPERCLIP_COMPANY_ID")
        return cid

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
        content: Optional[bytes] = None,
        files: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        await self._ensure_dynamic_config()
        url = f"{self.base_url}/{path.lstrip('/')}"
        hdrs = self._headers(headers)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.request(
                method,
                url,
                json=json,
                params=params,
                content=content,
                files=files,
                headers=hdrs,
            )
            if r.status_code >= 400:
                log.error(
                    "paperclip.http.error",
                    status=r.status_code,
                    method=method,
                    url=url,
                    body=r.text[:500],
                )
                raise PaperclipHTTPError(r.status_code, r.text, url)
            if r.status_code == 204 or not r.content:
                return None
            return r.json()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def list_companies(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/companies") or []

    async def create_company(
        self,
        name: str,
        description: Optional[str] = None,
        budget_monthly_cents: int = 0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "budgetMonthlyCents": budget_monthly_cents}
        if description is not None:
            payload["description"] = description
        return await self._request("POST", "/companies", json=payload)

    async def get_company(self, company_id: Optional[str] = None) -> dict[str, Any]:
        cid = await self._require_company_id(company_id)
        return await self._request("GET", f"/companies/{cid}")

    async def list_agents(self, company_id: Optional[str] = None) -> list[dict[str, Any]]:
        cid = await self._require_company_id(company_id)
        return await self._request("GET", f"/companies/{cid}/agents") or []

    async def create_agent_http(
        self,
        name: str,
        webhook_url: str,
        role: AgentRole = "general",
        title: Optional[str] = None,
        reports_to: Optional[str] = None,
        timeout_sec: int = 300,
        company_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        icon: Optional[str] = None,
    ) -> dict[str, Any]:
        cid = await self._require_company_id(company_id)
        payload: dict[str, Any] = {
            "name": name,
            "role": role,
            "adapterType": "http",
            "adapterConfig": {
                "url": webhook_url,
                "method": "POST",
                # O core do Paperclip documenta `timeoutSec` mas o adapter http
                # (server/src/adapters/http/execute.ts) só lê `timeoutMs`. Mandamos os
                # dois para não depender de qual dos dois a versão instalada honra.
                "timeoutSec": timeout_sec,
                "timeoutMs": timeout_sec * 1000,
                "headers": {},
                # O adapter monta o body como {...payloadTemplate, agentId, runId, context} —
                # `companyId` NÃO vem no corpo por padrão (só company_id do agente fica
                # server-side). Injetamos aqui via payloadTemplate para o harness receber
                # companyId em todo heartbeat sem depender de fallback de config.
                "payloadTemplate": {"companyId": cid},
            },
        }
        if title is not None:
            payload["title"] = title
        if reports_to is not None:
            payload["reportsTo"] = reports_to
        if metadata is not None:
            payload["metadata"] = metadata
        if icon is not None:
            payload["icon"] = icon
        return await self._request("POST", f"/companies/{cid}/agents", json=payload)

    async def update_agent(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        reports_to: Optional[str] = None,
        adapter_config: Optional[dict[str, Any]] = None,
        status: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if reports_to is not None:
            payload["reportsTo"] = reports_to
        if adapter_config is not None:
            payload["adapterConfig"] = adapter_config
        if status is not None:
            payload["status"] = status
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._request("PATCH", f"/agents/{agent_id}", json=payload)

    async def create_agent_api_key(self, agent_id: str, name: str = "default") -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/agents/{agent_id}/keys",
            json={"name": name},
        )

    async def wakeup_agent(self, agent_id: str, reason: str = "manual") -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/agents/{agent_id}/wakeup",
            json={"reason": reason},
        )

    async def list_issues(
        self,
        statuses: Optional[list[IssueStatus]] = None,
        assignee_agent_id: Optional[str] = None,
        company_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        cid = await self._require_company_id(company_id)
        params: dict[str, Any] = {"limit": limit}
        if statuses:
            params["status"] = statuses
        if assignee_agent_id:
            params["assigneeAgentId"] = assignee_agent_id
        return await self._request("GET", f"/companies/{cid}/issues", params=params) or []

    async def create_issue(
        self,
        title: str,
        description: Optional[str] = None,
        assignee_agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
        status: IssueStatus = "backlog",
        priority: IssuePriority = "medium",
        company_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        label_ids: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        cid = await self._require_company_id(company_id)
        payload: dict[str, Any] = {
            "title": title,
            "status": status,
            "priority": priority,
        }
        if description is not None:
            payload["description"] = description
        if assignee_agent_id is not None:
            payload["assigneeAgentId"] = assignee_agent_id
        if project_id is not None:
            payload["projectId"] = project_id
        if goal_id is not None:
            payload["goalId"] = goal_id
        if parent_id is not None:
            payload["parentId"] = parent_id
        if label_ids is not None:
            payload["labelIds"] = label_ids
        return await self._request("POST", f"/companies/{cid}/issues", json=payload)

    async def get_issue(self, issue_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/issues/{issue_id}")

    async def get_issue_heartbeat_context(self, issue_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/issues/{issue_id}/heartbeat-context")

    async def update_issue(
        self,
        issue_id: str,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[IssueStatus] = None,
        priority: Optional[IssuePriority] = None,
        assignee_agent_id: Optional[str] = None,
        assignee_user_id: Optional[str] = None,
        project_id: Optional[str] = None,
        clear_assignee_agent: bool = False,
    ) -> dict[str, Any]:
        # `assignee_agent_id=None` por padrão significa "não mexe nesse campo" (comportamento
        # histórico) — não dá pra usar None também pra "desatribuir de propósito", porque aí
        # updates parciais (ex. só mudar status) acabariam sempre pulando esse campo mesmo.
        # `clear_assignee_agent=True` é o jeito explícito de mandar assigneeAgentId=null.
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if status is not None:
            payload["status"] = status
        if priority is not None:
            payload["priority"] = priority
        if clear_assignee_agent:
            payload["assigneeAgentId"] = None
        elif assignee_agent_id is not None:
            payload["assigneeAgentId"] = assignee_agent_id
        if assignee_user_id is not None:
            payload["assigneeUserId"] = assignee_user_id
        if project_id is not None:
            payload["projectId"] = project_id
        return await self._request("PATCH", f"/issues/{issue_id}", json=payload)

    async def assign_issue(self, issue_id: str, agent_id: str) -> dict[str, Any]:
        return await self.update_issue(issue_id, assignee_agent_id=agent_id)

    async def unassign_issue(self, issue_id: str) -> dict[str, Any]:
        return await self.update_issue(issue_id, clear_assignee_agent=True)

    async def add_comment(
        self,
        issue_id: str,
        body: str,
        reopen: bool = False,
        resume: bool = False,
        interrupt: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"body": body}
        if reopen:
            payload["reopen"] = True
        if resume:
            payload["resume"] = True
        if interrupt:
            payload["interrupt"] = True
        return await self._request("POST", f"/issues/{issue_id}/comments", json=payload)

    async def list_comments(self, issue_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await self._request(
            "GET",
            f"/issues/{issue_id}/comments",
            params={"limit": limit},
        ) or []

    async def create_work_product(
        self,
        issue_id: str,
        title: str,
        summary: Optional[str] = None,
        wp_type: Literal[
            "preview_url", "runtime_service", "pull_request", "branch",
            "commit", "artifact", "document",
        ] = "document",
        provider: str = "interestelar-harness",
        source_url: Optional[str] = None,
    ) -> dict[str, Any]:
        # createIssueWorkProductSchema exige `type` (enum) e `provider` (string) — não tem
        # `body`/`kind`. O conteúdo textual vai em `summary` (opcional).
        payload: dict[str, Any] = {
            "title": title,
            "type": wp_type,
            "provider": provider,
        }
        if summary is not None:
            payload["summary"] = summary
        if source_url is not None:
            payload["url"] = source_url
        return await self._request("POST", f"/issues/{issue_id}/work-products", json=payload)

    async def list_work_products(self, issue_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/issues/{issue_id}/work-products") or []

    async def callback_heartbeat_run(
        self,
        run_id: str,
        status: Literal["completed", "failed", "cancelled"],
        result: Optional[str] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if result is not None:
            payload["result"] = result
        return await self._request(
            "POST",
            f"/heartbeat-runs/{run_id}/callback",
            json=payload,
        )

    async def list_projects(self, company_id: Optional[str] = None) -> list[dict[str, Any]]:
        cid = await self._require_company_id(company_id)
        return await self._request("GET", f"/companies/{cid}/projects") or []

    async def create_project(
        self,
        name: str,
        description: Optional[str] = None,
        goal_id: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        cid = await self._require_company_id(company_id)
        payload: dict[str, Any] = {"name": name}
        if description is not None:
            payload["description"] = description
        if goal_id is not None:
            payload["goalId"] = goal_id
        return await self._request("POST", f"/companies/{cid}/projects", json=payload)

    async def list_routines(self, company_id: Optional[str] = None) -> list[dict[str, Any]]:
        cid = await self._require_company_id(company_id)
        return await self._request("GET", f"/companies/{cid}/routines") or []

    async def create_routine(
        self,
        title: str,
        assignee_agent_id: str,
        description: Optional[str] = None,
        priority: IssuePriority = "medium",
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        # createRoutineSchema usa `title` (não `name`), não tem `scheduleCron` nem
        # `assignedTaskTemplate` — title/description da routine SÃO o template da tarefa
        # gerada a cada disparo. O agendamento cron é um recurso à parte, criado via
        # create_routine_trigger() depois que a routine existe (precisa do routine id).
        cid = await self._require_company_id(company_id)
        payload: dict[str, Any] = {
            "title": title,
            "assigneeAgentId": assignee_agent_id,
            "priority": priority,
        }
        if description is not None:
            payload["description"] = description
        return await self._request("POST", f"/companies/{cid}/routines", json=payload)

    async def create_routine_trigger(
        self,
        routine_id: str,
        cron_expression: str,
        timezone: str = "UTC",
        label: Optional[str] = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "schedule",
            "cronExpression": cron_expression,
            "timezone": timezone,
            "enabled": enabled,
        }
        if label is not None:
            payload["label"] = label
        return await self._request("POST", f"/routines/{routine_id}/triggers", json=payload)

    async def list_labels(self, company_id: Optional[str] = None) -> list[dict[str, Any]]:
        cid = await self._require_company_id(company_id)
        return await self._request("GET", f"/companies/{cid}/labels") or []

    async def create_label(
        self,
        name: str,
        color: str = "#6366f1",
        description: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        cid = await self._require_company_id(company_id)
        payload: dict[str, Any] = {"name": name, "color": color}
        if description is not None:
            payload["description"] = description
        return await self._request("POST", f"/companies/{cid}/labels", json=payload)

    async def upload_attachment(
        self,
        issue_id: str,
        file_path: Path,
        mime: str,
        filename: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        cid = await self._require_company_id(company_id)
        name = filename or file_path.name
        data = file_path.read_bytes()
        headers = {"Content-Type": mime}
        params = {"filename": name}
        return await self._request(
            "POST",
            f"/companies/{cid}/issues/{issue_id}/attachments",
            content=data,
            params=params,
            headers=headers,
        )

    async def create_approval(
        self,
        approval_type: str,
        payload: dict[str, Any],
        requested_by_agent_id: Optional[str] = None,
        issue_ids: Optional[list[str]] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """`type` é um enum FECHADO no core (`APPROVAL_TYPES` em
        packages/shared/src/constants.ts): só `hire_agent`, `approve_ceo_strategy`,
        `budget_override_required`, `request_board_approval` — não dá pra inventar um
        tipo customizado (ex.: "governanca_sign_off"), o Zod rejeita com 400. Pro
        Approval Gate da Governança usamos `request_board_approval`, que é o único
        genérico o bastante pra "isto precisa de sign-off humano".

        Resolver (`/approvals/:id/approve|reject`) exige `assertBoard` — só um humano
        autenticado como board resolve, nunca um agente sozinho. `requested_by_agent_id`
        só define quem é acordado automaticamente quando alguém aprova (ver
        `list_issue_approvals` e o heartbeat `wakeReason=approval_approved`)."""
        cid = await self._require_company_id(company_id)
        body: dict[str, Any] = {"type": approval_type, "payload": payload}
        if requested_by_agent_id is not None:
            body["requestedByAgentId"] = requested_by_agent_id
        if issue_ids is not None:
            body["issueIds"] = issue_ids
        return await self._request("POST", f"/companies/{cid}/approvals", json=body)

    async def list_issue_approvals(self, issue_id: str) -> list[dict[str, Any]]:
        return await self._request("GET", f"/issues/{issue_id}/approvals") or []

    async def list_company_skills(self, company_id: Optional[str] = None) -> list[dict[str, Any]]:
        cid = await self._require_company_id(company_id)
        return await self._request("GET", f"/companies/{cid}/skills") or []

    async def import_company_skill_file(
        self,
        slug: str,
        skill_md: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        company_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Cria uma Company Skill local a partir de markdown inline.

        NOTA: `POST /companies/:companyId/skills/import` (companySkillImportSchema)
        aceita só `{source: string}` — é para importar de uma fonte externa (URL/github),
        não para conteúdo markdown que já temos em mãos. O endpoint certo para isso é
        `POST /companies/:companyId/skills` (companySkillCreateSchema), que aceita
        `{name, slug, description, markdown}` e cria via `svc.createLocalSkill`.
        """
        cid = await self._require_company_id(company_id)
        payload: dict[str, Any] = {
            "name": name or slug,
            "slug": slug,
            "markdown": skill_md,
        }
        if description is not None:
            payload["description"] = description
        return await self._request("POST", f"/companies/{cid}/skills", json=payload)
