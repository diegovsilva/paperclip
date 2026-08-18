from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = ROOT / "harness"
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness.config import get_settings  # noqa: E402
from harness.logging_setup import setup_logging  # noqa: E402
from harness.paperclip_client import PaperclipClient  # noqa: E402

log = setup_logging()
settings = get_settings()


# role e icon precisam bater com os enums reais de packages/shared/src/constants.ts
# (AGENT_ROLES / AGENT_ICON_NAMES) — o server valida com Zod e rejeita (400) qualquer
# valor fora da lista. Não existem "coder"/"data_engineer"/"security_engineer"/
# "data_scientist" nem ícones em emoji — só os slugs nomeados abaixo.
AGENTES_META: list[dict] = [
    {
        "slug": "head",
        "name": "Head de Dados",
        "role": "cto",
        "title": "Head de Engenharia de Dados",
        "reports_to": None,
        "webhook_path": "/webhook/head",
        "icon": "radar",
    },
    {
        "slug": "po",
        "name": "PO de Dados",
        "role": "pm",
        "title": "Product Owner de Dados",
        "reports_to": "head",
        "webhook_path": "/webhook/po",
        "icon": "target",
    },
    {
        "slug": "arquiteto",
        "name": "Arquiteto de Dados",
        "role": "engineer",
        "title": "Arquiteto de Plataforma de Dados",
        "reports_to": "head",
        "webhook_path": "/webhook/arquiteto",
        "icon": "puzzle",
    },
    {
        "slug": "engenheiro",
        "name": "Engenheiro de Dados",
        "role": "engineer",
        "title": "Engenheiro de Dados Sênior",
        "reports_to": "head",
        "webhook_path": "/webhook/engenheiro",
        "icon": "wrench",
    },
    {
        "slug": "governanca",
        "name": "Engenheiro de Governança",
        "role": "security",
        "title": "Especialista LGPD & Governança de Dados",
        "reports_to": "head",
        "webhook_path": "/webhook/governanca",
        "icon": "shield",
    },
    {
        "slug": "analista",
        "name": "Analista de Dados",
        "role": "researcher",
        "title": "Analista de Dados / BI",
        "reports_to": "head",
        "webhook_path": "/webhook/analista",
        "icon": "telescope",
    },
    {
        "slug": "curador-skills",
        "name": "Curador de Skills",
        "role": "general",
        "title": "Curador Semanal de Skills do Interestelar",
        "reports_to": None,
        "webhook_path": "/webhook/curador-skills",
        "icon": "sparkles",
    },
]

SKILLS_META: list[dict] = [
    {
        "slug": "revisao-cruzada",
        "name": "Revisão Cruzada (Harness Interestelar)",
        "description": "Protocolo interno de devoluções entre agentes com limite de 3 revisões totais / 2 por par.",
    },
    {
        "slug": "criterios-aceite",
        "name": "Critérios de Aceite SMART",
        "description": "Converte pedido vago em critérios de aceite SMART. Usado pelo PO.",
    },
    {
        "slug": "registro-vault",
        "name": "Registro em Vault Obsidian",
        "description": "Escrita atômica em vault markdown com YAML frontmatter + wikilinks.",
    },
    {
        "slug": "padrao-repositorio",
        "name": "Padrão do Repositório (fonte: Reversa)",
        "description": "10 seções obrigatórias do padrão de desenvolvimento do repo da empresa. Monitorado pelo Curador.",
    },
    {
        "slug": "modelagem-dados",
        "name": "Modelagem de Dados (Kimball / Data Vault)",
        "description": "Star Schema, Data Vault 2.0 e Wide Tables. Monitorado pelo Curador (dbt docs + referências).",
    },
    {
        "slug": "checklist-lgpd",
        "name": "Checklist LGPD (ANPD)",
        "description": "Inventário + 10 itens da ANPD + matriz risco BAIXO/MÉDIO/ALTO. Monitorado pelo Curador.",
    },
]

PROJECTO_DEMANDAS = "Demandas de Dados — Interestelar"
LABEL_INTERESTELAR = ("Interestelar", "#7c3aed", "Projeto Interestelar (time 6 agentes + Curador)")
LABEL_LGPD = ("LGPD", "#2563eb", "Requer validação de Governança / LGPD")


@dataclass
class SetupResult:
    company_id: str
    agents: dict[str, dict]
    project_id: str
    labels: dict[str, str]
    routine_id: Optional[str]


def _ler_skill_md(slug: str) -> str:
    path = ROOT / "skills" / slug / "SKILL.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"# Skill {slug}\n\n(ainda não localizada durante setup)"


def _webhook_url(harness_public_base: str, webhook_path: str) -> str:
    base = harness_public_base.rstrip("/")
    return f"{base}{webhook_path}"


async def _setup(
    company_name: str,
    harness_public_base: str,
    skip_skills: bool = False,
    skip_routine: bool = False,
) -> SetupResult:
    client = PaperclipClient()

    existing = await client.list_companies()
    company = None
    for c in existing:
        if c.get("name", "").lower() == company_name.lower():
            company = c
            break
    if not company:
        company = await client.create_company(
            name=company_name,
            description="Empresa gerenciada pelo time Interestelar (Paperclip + harness multi-agente de dados).",
            budget_monthly_cents=0,
        )
        log.info("setup.company.criada", nome=company_name)
    else:
        log.info("setup.company.existente", nome=company_name, id=company.get("id"))
    company_id = company["id"]

    existing_agents_list = await client.list_agents(company_id=company_id)
    existing_by_name = {
        (a.get("name") or "").lower(): a for a in existing_agents_list
    }
    agent_ids: dict[str, dict] = {}
    for meta in AGENTES_META:
        reports_to_id = None
        if meta["reports_to"] is not None:
            dep = agent_ids.get(meta["reports_to"])
            if dep:
                reports_to_id = dep.get("id")
        webhook = _webhook_url(harness_public_base, meta["webhook_path"])
        existing = existing_by_name.get(meta["name"].lower())
        try:
            if existing:
                updated = await client.update_agent(
                    existing["id"],
                    reports_to=reports_to_id,
                    adapter_config={
                        "url": webhook,
                        "method": "POST",
                        "timeoutSec": settings.harness_agent_timeout_sec,
                        "timeoutMs": settings.harness_agent_timeout_sec * 1000,
                        "headers": {},
                        "payloadTemplate": {"companyId": company_id},
                    },
                    metadata={"interestelar_slug": meta["slug"]},
                )
                agent_ids[meta["slug"]] = updated or existing
                log.info("setup.agente.atualizado", nome=meta["name"])
            else:
                created = await client.create_agent_http(
                    name=meta["name"],
                    webhook_url=webhook,
                    role=meta["role"],
                    title=meta["title"],
                    reports_to=reports_to_id,
                    timeout_sec=settings.harness_agent_timeout_sec,
                    company_id=company_id,
                    metadata={"interestelar_slug": meta["slug"]},
                    icon=meta["icon"],
                )
                agent_ids[meta["slug"]] = created
                log.info("setup.agente.criado", nome=meta["name"])
        except Exception as exc:  # noqa: BLE001
            log.error("setup.agente.erro", nome=meta["name"], err=str(exc))
            raise

    projects = await client.list_projects(company_id=company_id)
    proj = next((p for p in projects if p.get("name") == PROJECTO_DEMANDAS), None)
    if not proj:
        proj = await client.create_project(
            name=PROJECTO_DEMANDAS,
            description="Projeto default do Interestelar. Todas as demandas de dados entram aqui.",
            company_id=company_id,
        )
        log.info("setup.projeto.criado")
    else:
        log.info("setup.projeto.existente")
    project_id = proj["id"]

    existing_labels = await client.list_labels(company_id=company_id)
    labels_map: dict[str, str] = {}
    for nome, cor, desc in (LABEL_INTERESTELAR, LABEL_LGPD):
        l = next((x for x in existing_labels if x.get("name") == nome), None)
        if not l:
            l = await client.create_label(nome, color=cor, description=desc, company_id=company_id)
            log.info("setup.label.criada", nome=nome)
        else:
            log.info("setup.label.existente", nome=nome)
        labels_map[nome] = l["id"]

    if not skip_skills:
        try:
            existing_skills = {
                s.get("key") or s.get("slug"): s
                for s in (await client.list_company_skills(company_id=company_id))
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("setup.skills.list.failed", err=str(exc))
            existing_skills = {}
        for meta in SKILLS_META:
            slug = meta["slug"]
            if slug in existing_skills:
                log.info("setup.skills.existente", slug=slug)
                continue
            skill_md = _ler_skill_md(slug)
            try:
                await client.import_company_skill_file(
                    slug=slug,
                    skill_md=skill_md,
                    name=meta["name"],
                    description=meta["description"],
                    company_id=company_id,
                )
                log.info("setup.skills.importada", slug=slug)
            except Exception as exc:  # noqa: BLE001
                log.warning("setup.skills.import_erro", slug=slug, err=str(exc))

    routine_id: Optional[str] = None
    curador_agent = agent_ids.get("curador-skills")
    ROUTINE_TITLE = "Curadoria semanal de skills — Interestelar"
    if not skip_routine and curador_agent:
        curador_id = curador_agent["id"]
        routines = await client.list_routines(company_id=company_id)
        existe = next((r for r in routines if r.get("title") == ROUTINE_TITLE), None)
        if existe:
            routine_id = existe["id"]
            log.info("setup.routine.existente")
        else:
            # createRoutineSchema não tem scheduleCron nem assignedTaskTemplate: title +
            # description da routine SÃO o template da tarefa disparada a cada execução.
            # O cron é um recurso à parte (trigger), criado depois via routines/:id/triggers.
            routine = await client.create_routine(
                title=ROUTINE_TITLE,
                assignee_agent_id=curador_id,
                description=(
                    "[Curadoria] Atualização semanal de skills externas\n\n"
                    "O Curador de Skills verificará os hashes das fontes externas e proporá atualizações\n"
                    "em skills_pendentes/. Ao final, um ticket por skill atualizada será aberto para aprovação humana."
                ),
                priority="low",
                company_id=company_id,
            )
            routine_id = routine["id"]
            log.info("setup.routine.criada")
            try:
                await client.create_routine_trigger(
                    routine_id=routine_id,
                    cron_expression="0 3 * * 1",
                    timezone="UTC",
                    label="Segunda-feira 03:00 UTC",
                )
                log.info("setup.routine.trigger.criado", cron="0 3 * * 1")
            except Exception as exc:  # noqa: BLE001
                log.error("setup.routine.trigger.erro", err=str(exc))

    return SetupResult(
        company_id=company_id,
        agents=agent_ids,
        project_id=project_id,
        labels=labels_map,
        routine_id=routine_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Setup inicial do Interestelar sobre Paperclip")
    parser.add_argument("--company-name", default="Interestelar", help="Nome da company a criar/reencontrar")
    parser.add_argument(
        "--harness-public-base",
        default=settings.harness_public_url,
        help=(
            "URL pela qual o container do Paperclip alcança o harness (não é "
            "'localhost' dentro da rede docker — default: HARNESS_PUBLIC_URL do .env, "
            "http://harness:8000)."
        ),
    )
    parser.add_argument("--skip-skills", action="store_true", help="Não importa Company Skills.")
    parser.add_argument("--skip-routine", action="store_true", help="Não cria a Routine semanal de curadoria.")
    parser.add_argument(
        "--company-id",
        default=None,
        help="Forçar PAPERCLIP_COMPANY_ID. Sobrescreve variável de ambiente durante o setup.",
    )
    args = parser.parse_args()

    if args.company_id:
        import os as _os
        _os.environ["PAPERCLIP_COMPANY_ID"] = args.company_id
        import importlib
        import harness.config as _cfg
        importlib.reload(_cfg)
        import harness.paperclip_client as _pc
        importlib.reload(_pc)
        get_settings.cache_clear()
        log.info("setup.company_id.override", valor=args.company_id)

    async def runner() -> SetupResult:
        return await _setup(
            company_name=args.company_name,
            harness_public_base=args.harness_public_base,
            skip_skills=args.skip_skills,
            skip_routine=args.skip_routine,
        )

    resultado = asyncio.run(runner())
    print("\n=== SETUP CONCLUÍDO ===")
    print(f"Company ID            : {resultado.company_id}")
    print(f"Projeto Demandas ID   : {resultado.project_id}")
    print(f"Routine Curadoria ID  : {resultado.routine_id}")
    print("Agentes (slug → id)   :")
    for slug, info in resultado.agents.items():
        print(f"  - {slug:<16} → {info.get('id')}")
    print("Labels                :")
    for nome, lid in resultado.labels.items():
        print(f"  - {nome:<16} → {lid}")


if __name__ == "__main__":
    main()
