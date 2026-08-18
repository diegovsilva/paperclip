from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import llm_client
from .config import get_settings
from .logging_setup import setup_logging

log = setup_logging()
settings = get_settings()

SKILLS_POR_AGENTE: dict[str, list[str]] = {
    "head": ["revisao-cruzada", "registro-vault", "padrao-repositorio"],
    "po": ["criterios-aceite", "registro-vault", "revisao-cruzada"],
    "arquiteto": ["padrao-repositorio", "modelagem-dados", "registro-vault", "revisao-cruzada", "checklist-lgpd"],
    "engenheiro": ["padrao-repositorio", "registro-vault", "revisao-cruzada"],
    "governanca": ["checklist-lgpd", "padrao-repositorio", "registro-vault", "revisao-cruzada"],
    "analista": ["registro-vault", "revisao-cruzada"],
    "curador-skills": [],
}

AGENT_LABELS: dict[str, str] = {
    "head": "Head de Dados",
    "po": "PO de Dados",
    "arquiteto": "Arquiteto de Dados",
    "engenheiro": "Engenheiro de Dados",
    "governanca": "Engenheiro de Governança",
    "analista": "Analista de Dados",
    "curador-skills": "Curador de Skills",
}

REVIEW_RE = re.compile(r"^\s*REVISAO_NECESSARIA\s*:\s*(.+?)\s*\|\s*(.+)$", re.MULTILINE)
STAGE_COMPLETE_RE = re.compile(r"^\s*ETAPA_CONCLUIDA\s*$", re.MULTILINE)
PLAN_LINE_RE = re.compile(r"#PLANO:(.+)$", re.MULTILINE)


@dataclass
class AgentInput:
    agent_slug: str
    ticket_id: str
    ticket_title: str
    ticket_description: str = ""
    ticket_status: str = "todo"
    ticket_priority: str = "medium"
    comments_history: list[tuple[str, str, str]] = field(default_factory=list)
    pattern_md: str = ""
    extra_context: dict[str, str] = field(default_factory=dict)
    previous_review_total: int = 0
    previous_review_par: dict[str, int] = field(default_factory=dict)


@dataclass
class AgentOutput:
    raw_text: str
    review: Optional[tuple[str, str]] = None
    stage_complete: bool = False
    plan: Optional[list[str]] = None
    # True somente quando a resposta é o fallback sintético do except em executar_agente
    # (LLM indisponível) — nunca setado a partir de texto de modelo. webhook.py usa isso
    # para bloquear/escalar explicitamente em vez de rotear como se a etapa tivesse
    # legitimamente terminado (ver comentário no except abaixo).
    llm_failed: bool = False


def _read_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _carregar_identidade(agent_slug: str) -> dict[str, str]:
    base = Path("./agents") / agent_slug
    return {
        "soul": _read_text(base / "SOUL.md"),
        "agents": _read_text(base / "AGENTS.md"),
        "heartbeat": _read_text(base / "HEARTBEAT.md"),
    }


def _carregar_skills(skills_nomes: list[str]) -> str:
    blocos: list[str] = []
    for skill in skills_nomes:
        md = _read_text(Path("./skills") / skill / "SKILL.md")
        if md:
            blocos.append(f"\n\n========== SKILL: {skill} ==========\n{md}\n==============================\n")
    return "\n".join(blocos)


def _montar_prompt(inp: AgentInput) -> tuple[str, str]:
    ident = _carregar_identidade(inp.agent_slug)
    skills = _carregar_skills(SKILLS_POR_AGENTE.get(inp.agent_slug, []))
    label = AGENT_LABELS.get(inp.agent_slug, inp.agent_slug)

    system = (
        f"Você é {label} de uma empresa de dados — agente do time Interestelar sobre Paperclip.\n"
        "Siga rigorosamente a identidade, as regras e o checklist abaixo. Seja técnico, preciso, "
        "direto. Não invente informação que não está no contexto. Use markdown estruturado.\n\n"
        f"# SOUL (persona/voz)\n{ident['soul']}\n\n"
        f"# AGENTS (papel/segurança/skills)\n{ident['agents']}\n\n"
        f"# HEARTBEAT (checklist operacional)\n{ident['heartbeat']}\n\n"
        f"# SKILLS RELEVANTES (aplicáveis a você)\n{skills or '(nenhuma skill adicional)'}\n"
    )

    comments_md = "\n".join(
        f"- [{ts}] {autor}:\n{body[:4000]}\n" for autor, ts, body in inp.comments_history
    )

    pattern_block = (
        f"\n# PADRÃO DO REPOSITÓRIO DA EMPRESA\n{inp.pattern_md[:12000]}\n"
        if inp.pattern_md else "\n# PADRÃO DO REPOSITÓRIO DA EMPRESA\n(ainda não detectado — siga os defaults, se necessário peça ao Head para gerar)\n"
    )

    extra_block = ""
    if inp.extra_context:
        extra_block = "\n# CONTEXTO EXTRA\n" + "\n".join(
            f"- {k}: {v}" for k, v in inp.extra_context.items()
        ) + "\n"

    counter_block = (
        "\n# CONTADORES DE REVISÃO (harness Interestelar)\n"
        f"Revisões totais já consumidas: {inp.previous_review_total} / 3 (máximo)\n"
        "Contadores por par (A↔B, max 2 idas e voltas):\n"
        + "\n".join(f"- {k}: {v}" for k, v in inp.previous_review_par.items())
        + "\n"
    )

    user = (
        f"# TICKET #{inp.ticket_id}\n"
        f"Título: {inp.ticket_title}\n"
        f"Status: {inp.ticket_status}\nPrioridade: {inp.ticket_priority}\n\n"
        f"## Descrição\n{inp.ticket_description[:15000]}\n\n"
        f"## Histórico de comentários (últimos primeiros)\n{comments_md or '(nenhum comentário)'}\n"
        + pattern_block
        + extra_block
        + counter_block
        + (
            "\n# INSTRUÇÃO FINAL PARA SUA RESPOSTA\n"
            "Produza sua resposta seguindo o checklist do HEARTBEAT. Ao final:\n"
            "- Use **exatamente** a tag `ETAPA_CONCLUIDA` em linha própria para sinalizar que sua etapa acabou.\n"
            "- Se precisar devolver para outro agente, escreva **1 linha** com a sintaxe abaixo (fora de bloco de código):\n"
            "  `REVISAO_NECESSARIA: <agente-slug> | <motivo específico em uma linha>`\n"
            "  agente-slug válidos: head, po, arquiteto, engenheiro, governanca, analista.\n"
            "- Se você é o Head classificando a demanda, escreva no começo da resposta o #PLANO: com a ordem dos agentes.\n"
            "  NUNCA inclua 'head' na lista do #PLANO: — o plano é só dos agentes de demanda que vão EXECUTAR\n"
            "  (po, arquiteto, engenheiro, governanca, analista). Você (Head) não é uma etapa do próprio plano,\n"
            "  você é quem monta e fecha o ciclo.\n"
            "- Não esqueça de registrar em vault (escrever observações que vão p/ Obsidian caso já estivesse implementado no loop).\n"
        )
    )

    return system, user


def _normalizar_slug(token: str) -> str:
    """Remove acentos antes de comparar com os slugs válidos (ASCII) — ver mesma função
    em webhook.py._normalizar_slug. Sem isso, "GOVERNANÇA" (como o modelo costuma
    escrever, com ç/ã) nunca bate com o slug "governanca" e some do plano/da revisão."""
    normalizado = unicodedata.normalize("NFKD", token)
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def _parse_output(text: str) -> AgentOutput:
    review_match = REVIEW_RE.search(text)
    review: Optional[tuple[str, str]] = None
    if review_match:
        alvo = _normalizar_slug(review_match.group(1).strip().lower())
        motivo = review_match.group(2).strip()
        if alvo in AGENT_LABELS:
            review = (alvo, motivo)
    complete = bool(STAGE_COMPLETE_RE.search(text))
    plan_match = PLAN_LINE_RE.search(text)
    plan: Optional[list[str]] = None
    if plan_match:
        raw_plan = plan_match.group(1)
        # "head" nunca é um passo válido do plano — é quem MONTA o plano, não uma etapa
        # de trabalho nele. Confirmado num teste real: o modelo escreveu
        # "#PLANO: HEAD → PO → ENGENHEIRO → HEAD (final)", e como o código trata
        # plan[0]/próximo-passo literalmente, isso reatribuía o ticket pro próprio Head
        # em vez de pro PO. Instrução no prompt sozinha não é confiável o bastante com
        # LLM — filtra aqui também.
        tokens = [
            normalizado
            for t in re.split(r"[→→, ]", raw_plan)
            for normalizado in [_normalizar_slug(t.strip().lower())]
            if normalizado in AGENT_LABELS and normalizado != "head"
        ]
        if tokens:
            plan = tokens
    return AgentOutput(raw_text=text, review=review, stage_complete=complete, plan=plan)


async def executar_agente(inp: AgentInput) -> AgentOutput:
    system, user = _montar_prompt(inp)
    log.info(
        "agent.prompt.start",
        agent=inp.agent_slug,
        ticket=inp.ticket_id,
        provider=settings.llm_provider,
        sys_chars=len(system),
        usr_chars=len(user),
    )
    try:
        resposta = await llm_client.chat_completion(system, user)
    except Exception as exc:  # noqa: BLE001
        # NÃO usar _parse_output aqui: o texto abaixo tem "ETAPA_CONCLUIDA" no fim de uma
        # frase, não sozinho numa linha — STAGE_COMPLETE_RE nunca bateria nele, então
        # webhook.py achava que a etapa "não terminou nem pediu revisão" e não fazia
        # NADA (nem reatribuía, nem bloqueava). O próprio comentário de erro então
        # reacordava o mesmo agente ("issue_commented"), que tentava de nova, falhava de
        # novo, comentava de novo — loop autossustentado até o hard-cap de heartbeats
        # bloquear o ticket (confirmado em teste real: INT-11 martelou "arquiteto"
        # sozinho; INT-12, sem #PLANO ainda, foi fechado como "done" pelo Head sem ter
        # feito nada, porque `not plan` também satisfazia a condição de fechamento).
        # Construir o AgentOutput direto, sem depender de parsing de texto: agentes de
        # demanda devolvem explicitamente pro Head (mecanismo de revisão, que já tem
        # proteção de limite via mem.incrementar_revisao); o próprio Head, que não tem
        # pra quem devolver, fica com stage_complete=False e review=None — webhook.py
        # trata esse caso bloqueando o ticket pra decisão humana em vez de fechar.
        fallback = (
            f"**Erro do modelo LLM:** {exc}\n\n"
            "Este erro é transitório (ex.: rate limit) — a etapa NÃO foi concluída."
        )
        if inp.agent_slug == "head":
            return AgentOutput(raw_text=fallback, review=None, stage_complete=False, llm_failed=True)
        motivo = f"Falha do modelo LLM ao processar esta etapa: {exc}"[:400]
        return AgentOutput(raw_text=fallback, review=("head", motivo), stage_complete=False, llm_failed=True)
    parsed = _parse_output(resposta)
    log.info(
        "agent.prompt.done",
        agent=inp.agent_slug,
        ticket=inp.ticket_id,
        chars=len(resposta),
        stage_complete=parsed.stage_complete,
        review_target=parsed.review[0] if parsed.review else None,
        plan_len=len(parsed.plan) if parsed.plan else 0,
    )
    return parsed
