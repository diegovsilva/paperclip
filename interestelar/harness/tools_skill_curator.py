from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from . import llm_client
from . import runtime_config as rc
from . import tools_memoria as mem
from .config import get_settings
from .logging_setup import setup_logging
from .paperclip_client import PaperclipClient

log = setup_logging()
settings = get_settings()

MANAGED_EXTERNAL_SKILLS = {
    "padrao-repositorio": [
        "https://raw.githubusercontent.com/sandeco/reversa/main/README.md",
    ],
    "modelagem-dados": [
        "https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview",
        "https://docs.getdbt.com/best-practices/materializations/5-snapshots",
    ],
    "checklist-lgpd": [
        "https://www.gov.br/anpd/pt-br/documentos-e-publicacoes/resolucao-cd-anpd-no-2-de-27-de-abril-de-2023",
    ],
}


async def _atualizar_skill_via_llm(prompt: str) -> str:
    # Usa o mesmo cliente de LLM (provider configurável) do resto do harness — antes
    # este módulo tinha sua própria chamada HTTP direta e hardcoded pra Groq, então
    # trocar LLM_PROVIDER não afetava a curadoria de skills.
    return await llm_client.chat_completion(
        "Você é um editor técnico de skills. Atualize SKILL.md preservando estrutura.",
        prompt,
        max_tokens=16384,
    )


async def _download_url(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=settings.http_request_timeout_sec) as client:
            r = await client.get(url, follow_redirects=True)
        if r.status_code >= 400:
            log.warning("curador.download.failed", url=url, status=r.status_code)
            return None
        return r.text[:200000]
    except Exception as exc:  # noqa: BLE001
        log.warning("curador.download.error", url=url, err=str(exc))
        return None


async def _baixar_fontes(urls: list[str]) -> str:
    parts: list[str] = []
    for url in urls:
        body = await _download_url(url)
        if body:
            parts.append(f"\n--- FONTE: {url} ---\n{body}\n")
    return "\n".join(parts)


def _skill_current_md(skill_nome: str) -> str:
    p = Path("./skills") / skill_nome / "SKILL.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _salvar_pendente(skill_nome: str, conteudo: str) -> Path:
    destino = Path("./skills_pendentes") / skill_nome / "SKILL.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(conteudo, encoding="utf-8")
    log.info("curador.skill_pendente.salva", skill=skill_nome, path=str(destino))
    return destino


def _diff_str(old: str, new: str) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, fromfile="atual.md", tofile="proposto.md", n=3)
    return "".join(list(diff))[:8000]


def _build_update_prompt(current_md: str, fonte_conteudo: str, skill_nome: str) -> str:
    return (
        f"Atualize esta skill '{skill_nome}' incorporando apenas o conteúdo das fontes abaixo.\n"
        "REGRAS OBRIGATÓRIAS:\n"
        "1. Preserve a estrutura original do SKILL.md (títulos, listas, tabelas, bloco de quando usar/não usar).\n"
        "2. NÃO adicione informação que não esteja presente nas fontes.\n"
        "3. NÃO remova informação ainda válida (a menos que a fonte deixe de listar).\n"
        "4. Output final é APENAS o novo SKILL.md completo. Não adicione comentários ou preâmbulos.\n\n"
        f"# SKILL.md ATUAL\n\n{current_md}\n\n"
        f"# CONTEÚDO DAS FONTES\n\n{fonte_conteudo}\n"
    )


async def _propor_atualizacao_skill(
    skill_nome: str,
    client: PaperclipClient,
) -> bool:
    urls = MANAGED_EXTERNAL_SKILLS.get(skill_nome)
    if not urls:
        return False
    current_md = _skill_current_md(skill_nome)
    fontes = await _baixar_fontes(urls)
    if not fontes:
        log.warning("curador.fontes_vazias", skill=skill_nome)
        return False
    novo_hash = mem.hash_conteudo(fontes)
    ultimo_aprovado = await mem.obter_ultimo_hash_skill_aprovado(skill_nome)
    if novo_hash == ultimo_aprovado:
        log.debug("curador.hash_igual", skill=skill_nome)
        return False
    prompt = _build_update_prompt(current_md, fontes, skill_nome)
    try:
        novo_md = await _atualizar_skill_via_llm(prompt)
    except Exception as exc:  # noqa: BLE001
        log.error("curador.llm.failed", skill=skill_nome, err=str(exc))
        return False
    _salvar_pendente(skill_nome, novo_md)
    await mem.registrar_proposta_skill(skill_nome, novo_hash)
    diff = _diff_str(current_md, novo_md)
    body = (
        f"**[Curadoria Automática]** Proposta de atualização para a skill `{skill_nome}`.\n\n"
        f"- Fonte(s): {', '.join(urls)}\n"
        f"- Hash da fonte: `{novo_hash[:12]}...`\n\n"
        "Para aplicar, execute:\n"
        f"```\nPOST {settings.paperclip_public_url.replace('http://paperclip:3100','http://localhost:8000')}/aprovar-skill/{skill_nome}\n```\n\n"
        "```diff\n"
        f"{diff}\n"
        "```\n"
    )
    cid = await rc.resolver_paperclip_company_id()
    title = f"[Curadoria Skill] {skill_nome} — atualização pendente"
    if cid:
        issue = await client.create_issue(
            title=title,
            description=body,
            company_id=cid,
            priority="low",
            status="todo",
        )
        log.info("curador.ticket_criado", skill=skill_nome, issue_id=issue.get("id"))
    else:
        log.warning("curador.company_id_missing", skill=skill_nome)
    return True


async def executar_ciclo_curadoria(
    client: Optional[PaperclipClient] = None,
    skills: Optional[list[str]] = None,
) -> dict[str, bool]:
    client = client or PaperclipClient()
    target = skills or list(MANAGED_EXTERNAL_SKILLS.keys())
    results: dict[str, bool] = {}
    for s in target:
        try:
            results[s] = await _propor_atualizacao_skill(s, client)
        except Exception as exc:  # noqa: BLE001
            log.error("curador.ciclo.erro", skill=s, err=str(exc))
            results[s] = False
    log.info("curador.ciclo.finalizado", results=results)
    return results
