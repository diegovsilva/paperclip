from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import aiosqlite

from .config import get_settings
from .logging_setup import setup_logging

log = setup_logging()
settings = get_settings()

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS repo_pattern_cache (
        slug_empresa TEXT PRIMARY KEY,
        pattern_md TEXT NOT NULL,
        source TEXT NOT NULL,
        hash_content TEXT NOT NULL,
        obtido_em TEXT NOT NULL,
        expira_em TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ticket_revisoes (
        ticket_id TEXT PRIMARY KEY,
        total_revisoes INTEGER NOT NULL DEFAULT 0,
        par_revisoes_json TEXT NOT NULL DEFAULT '{}',
        retorno_pendente_pilha_json TEXT NOT NULL DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_curadoria_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_nome TEXT NOT NULL UNIQUE,
        fonte_hash TEXT NOT NULL,
        proposta_em TEXT NOT NULL,
        aprovada_em TEXT,
        aprovada_por TEXT
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ticket_revisoes_total ON ticket_revisoes(total_revisoes)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_skill_curadoria_nome ON skill_curadoria_log(skill_nome)
    """,
    # Configuração dinâmica (ex.: provider de LLM ativo + chaves), editável pela página
    # de configurações do harness sem precisar mexer no .env / reiniciar o container.
    # Chave/valor genérico — quem interpreta o significado é harness/runtime_config.py.
    """
    CREATE TABLE IF NOT EXISTS runtime_settings (
        chave TEXT PRIMARY KEY,
        valor TEXT,
        atualizado_em TEXT NOT NULL
    )
    """,
]


class ReviewLimitError(Exception):
    pass


@dataclass
class PatternCache:
    slug_empresa: str
    pattern_md: str
    source: str
    hash_content: str
    obtido_em: datetime
    expira_em: datetime

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.utcnow()
        return now >= self.expira_em


@dataclass
class ReviewState:
    ticket_id: str
    total_revisoes: int
    par_revisoes: dict[str, int]


def _db_path() -> Path:
    p = settings.sqlite_path
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _par_key(from_agent: str, to_agent: str) -> str:
    a = from_agent.strip().lower()
    b = to_agent.strip().lower()
    return f"{min(a, b)}->{max(a, b)}"


async def init_db() -> None:
    async with aiosqlite.connect(_db_path()) as db:
        for stmt in SCHEMA_STATEMENTS:
            await db.execute(stmt)
        await db.commit()
    log.debug("sqlite.schema_ready", path=str(_db_path()))


@asynccontextmanager
async def _conn():
    await init_db()
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def obter_padrao_repo(slug_empresa: str) -> Optional[PatternCache]:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT * FROM repo_pattern_cache WHERE slug_empresa = ?",
            (slug_empresa,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return PatternCache(
        slug_empresa=row["slug_empresa"],
        pattern_md=row["pattern_md"],
        source=row["source"],
        hash_content=row["hash_content"],
        obtido_em=datetime.fromisoformat(row["obtido_em"]),
        expira_em=datetime.fromisoformat(row["expira_em"]),
    )


async def salvar_padrao_repo(
    slug_empresa: str,
    pattern_md: str,
    source: str,
    hash_content: Optional[str] = None,
    ttl_dias: Optional[int] = None,
) -> PatternCache:
    ttl = ttl_dias or settings.repo_pattern_ttl_days
    agora = datetime.utcnow()
    expira = agora + timedelta(days=ttl)
    h = hash_content or hashlib.sha256(pattern_md.encode("utf-8")).hexdigest()
    async with _conn() as db:
        await db.execute(
            """
            INSERT INTO repo_pattern_cache(slug_empresa, pattern_md, source, hash_content, obtido_em, expira_em)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug_empresa) DO UPDATE SET
                pattern_md=excluded.pattern_md,
                source=excluded.source,
                hash_content=excluded.hash_content,
                obtido_em=excluded.obtido_em,
                expira_em=excluded.expira_em
            """,
            (slug_empresa, pattern_md, source, h, agora.isoformat(), expira.isoformat()),
        )
    log.info(
        "repo_pattern.saved",
        slug=slug_empresa,
        source=source,
        expires_at=expira.isoformat(),
    )
    return PatternCache(
        slug_empresa=slug_empresa,
        pattern_md=pattern_md,
        source=source,
        hash_content=h,
        obtido_em=agora,
        expira_em=expira,
    )


async def invalidar_padrao_repo(slug_empresa: str) -> None:
    async with _conn() as db:
        await db.execute("DELETE FROM repo_pattern_cache WHERE slug_empresa = ?", (slug_empresa,))
    log.info("repo_pattern.invalidado", slug=slug_empresa)


async def _get_or_create_review_row(conn: aiosqlite.Connection, ticket_id: str) -> ReviewState:
    cur = await conn.execute("SELECT * FROM ticket_revisoes WHERE ticket_id = ?", (ticket_id,))
    row = await cur.fetchone()
    if row:
        return ReviewState(
            ticket_id=ticket_id,
            total_revisoes=row["total_revisoes"],
            par_revisoes=json.loads(row["par_revisoes_json"] or "{}"),
        )
    return ReviewState(ticket_id=ticket_id, total_revisoes=0, par_revisoes={})


async def obter_estado_revisoes(ticket_id: str) -> ReviewState:
    async with _conn() as db:
        return await _get_or_create_review_row(db, ticket_id)


async def incrementar_revisao(
    ticket_id: str,
    de_agente: str,
    para_agente: str,
    max_review_total: Optional[int] = None,
    max_review_per_pair: Optional[int] = None,
) -> tuple[int, int]:
    # Os limites vêm por parâmetro (não settings.xxx direto) pra chamador poder passar o
    # valor efetivo já resolvido via runtime_config (SQLite > .env, página /config) —
    # tools_memoria.py é a camada de baixo nível e não pode importar runtime_config.py
    # (que importa este módulo), então não resolve isso sozinho. None cai pro .env,
    # mantendo o comportamento de sempre pra quem chama sem passar nada (ex.: testes).
    limite_total = max_review_total if max_review_total is not None else settings.max_review_total
    limite_par = max_review_per_pair if max_review_per_pair is not None else settings.max_review_per_pair
    if de_agente == "head" or para_agente == "head":
        log.debug(
            "review.head_bypass",
            ticket=ticket_id,
            from_=de_agente,
            to=para_agente,
        )
    key = _par_key(de_agente, para_agente)
    async with _conn() as db:
        state = await _get_or_create_review_row(db, ticket_id)
        novo_total = state.total_revisoes + 1
        state.par_revisoes[key] = state.par_revisoes.get(key, 0) + 1
        par_count = state.par_revisoes[key]
        if novo_total > limite_total:
            raise ReviewLimitError(
                f"Limite de revisoes TOTAIS excedido para ticket {ticket_id}: "
                f"{novo_total} > {limite_total}. Requer Head decisão humana."
            )
        if par_count > limite_par:
            raise ReviewLimitError(
                f"Limite idas/voltas entre '{key}' excedido: {par_count} > {limite_par}. "
                "Requer Head decisão humana."
            )
        await db.execute(
            """
            INSERT INTO ticket_revisoes(ticket_id, total_revisoes, par_revisoes_json)
            VALUES(?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                total_revisoes=excluded.total_revisoes,
                par_revisoes_json=excluded.par_revisoes_json
            """,
            (ticket_id, novo_total, json.dumps(state.par_revisoes, ensure_ascii=False)),
        )
    log.info(
        "review.incrementado",
        ticket=ticket_id,
        from_=de_agente,
        to=para_agente,
        total=novo_total,
        pair=key,
        pair_count=par_count,
    )
    return novo_total, par_count


async def _get_pilha(conn: aiosqlite.Connection, ticket_id: str) -> list[dict[str, str]]:
    cur = await conn.execute(
        "SELECT retorno_pendente_pilha_json FROM ticket_revisoes WHERE ticket_id = ?",
        (ticket_id,),
    )
    row = await cur.fetchone()
    if not row:
        return []
    return json.loads(row["retorno_pendente_pilha_json"] or "[]")


async def definir_retorno_pendente(ticket_id: str, alvo: str, retornar_para: str) -> None:
    """Empilha que, quando `alvo` concluir a etapa (ETAPA_CONCLUIDA), o controle deve
    voltar para `retornar_para` — quem pediu a REVISAO_NECESSARIA — em vez de seguir o
    #PLANO: normal. Sem isso, um agente respondendo a uma revisão ad-hoc (que também
    aparece no plano principal, ex. Governança) seria roteado para o PRÓXIMO passo do
    plano, pulando quem pediu a revisão (ver harness §4.2 / skill revisao-cruzada).
    É uma PILHA (não um slot único) para aguentar revisão-dentro-de-revisão: se
    Governança, ao responder o Arquiteto, pedir revisão à Analista, a Analista deve
    voltar para Governança, e só depois Governança volta para o Arquiteto."""
    async with _conn() as db:
        state = await _get_or_create_review_row(db, ticket_id)
        pilha = await _get_pilha(db, ticket_id)
        pilha.append({"alvo": alvo, "retornar_para": retornar_para})
        await db.execute(
            """
            INSERT INTO ticket_revisoes(ticket_id, total_revisoes, par_revisoes_json,
                                         retorno_pendente_pilha_json)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                retorno_pendente_pilha_json=excluded.retorno_pendente_pilha_json
            """,
            (
                ticket_id,
                state.total_revisoes,
                json.dumps(state.par_revisoes, ensure_ascii=False),
                json.dumps(pilha, ensure_ascii=False),
            ),
        )
    log.debug("review.retorno_pendente.empilhado", ticket=ticket_id, alvo=alvo, retornar_para=retornar_para, profundidade=len(pilha))


async def obter_e_limpar_retorno_pendente(ticket_id: str, agente_atual: str) -> Optional[str]:
    """Se `agente_atual` é exatamente quem foi convocado pela REVISAO_NECESSARIA no topo
    da pilha deste ticket, desempilha e retorna o slug de quem pediu. Caso contrário
    (topo vazio ou aponta para outro agente) retorna None — o roteamento normal por
    #PLANO: segue valendo."""
    async with _conn() as db:
        pilha = await _get_pilha(db, ticket_id)
        if not pilha or pilha[-1]["alvo"] != agente_atual:
            return None
        topo = pilha.pop()
        await db.execute(
            "UPDATE ticket_revisoes SET retorno_pendente_pilha_json = ? WHERE ticket_id = ?",
            (json.dumps(pilha, ensure_ascii=False), ticket_id),
        )
    retornar_para = topo["retornar_para"]
    log.debug("review.retorno_pendente.desempilhado", ticket=ticket_id, agente=agente_atual, retornar_para=retornar_para)
    return retornar_para


async def resetar_revisoes(ticket_id: str) -> None:
    async with _conn() as db:
        await db.execute(
            "DELETE FROM ticket_revisoes WHERE ticket_id = ?",
            (ticket_id,),
        )
    log.info("review.resetado", ticket=ticket_id)


async def registrar_proposta_skill(skill_nome: str, fonte_hash: str) -> int:
    agora = datetime.utcnow().isoformat()
    async with _conn() as db:
        cur = await db.execute(
            """
            INSERT INTO skill_curadoria_log(skill_nome, fonte_hash, proposta_em)
            VALUES(?, ?, ?)
            ON CONFLICT(skill_nome) DO UPDATE SET
                fonte_hash=excluded.fonte_hash,
                proposta_em=excluded.proposta_em,
                aprovada_em=NULL,
                aprovada_por=NULL
            RETURNING id
            """,
            (skill_nome, fonte_hash, agora),
        )
        row = await cur.fetchone()
    return row[0] if row else -1


async def obter_ultimo_hash_skill_aprovado(skill_nome: str) -> Optional[str]:
    async with _conn() as db:
        cur = await db.execute(
            "SELECT fonte_hash FROM skill_curadoria_log WHERE skill_nome = ? AND aprovada_em IS NOT NULL ORDER BY id DESC LIMIT 1",
            (skill_nome,),
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def marcar_skill_aprovada(skill_nome: str, aprovada_por: str = "board") -> None:
    agora = datetime.utcnow().isoformat()
    async with _conn() as db:
        await db.execute(
            "UPDATE skill_curadoria_log SET aprovada_em = ?, aprovada_por = ? WHERE skill_nome = ?",
            (agora, aprovada_por, skill_nome),
        )
    log.info("skill.aprovada", skill=skill_nome, por=aprovada_por)


def hash_conteudo(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


async def obter_config(chave: str) -> Optional[str]:
    async with _conn() as db:
        cur = await db.execute("SELECT valor FROM runtime_settings WHERE chave = ?", (chave,))
        row = await cur.fetchone()
    return row["valor"] if row else None


async def obter_configs(chaves: list[str]) -> dict[str, Optional[str]]:
    if not chaves:
        return {}
    placeholders = ",".join("?" for _ in chaves)
    async with _conn() as db:
        cur = await db.execute(
            f"SELECT chave, valor FROM runtime_settings WHERE chave IN ({placeholders})",
            chaves,
        )
        rows = await cur.fetchall()
    encontrados = {row["chave"]: row["valor"] for row in rows}
    return {chave: encontrados.get(chave) for chave in chaves}


async def salvar_config(chave: str, valor: Optional[str]) -> None:
    agora = datetime.utcnow().isoformat()
    async with _conn() as db:
        await db.execute(
            """
            INSERT INTO runtime_settings(chave, valor, atualizado_em)
            VALUES(?, ?, ?)
            ON CONFLICT(chave) DO UPDATE SET
                valor=excluded.valor,
                atualizado_em=excluded.atualizado_em
            """,
            (chave, valor, agora),
        )
    log.info("runtime_config.salva", chave=chave)


async def salvar_configs(pares: dict[str, Optional[str]]) -> None:
    agora = datetime.utcnow().isoformat()
    async with _conn() as db:
        for chave, valor in pares.items():
            await db.execute(
                """
                INSERT INTO runtime_settings(chave, valor, atualizado_em)
                VALUES(?, ?, ?)
                ON CONFLICT(chave) DO UPDATE SET
                    valor=excluded.valor,
                    atualizado_em=excluded.atualizado_em
                """,
                (chave, valor, agora),
            )
    log.info("runtime_config.salva_lote", chaves=list(pares.keys()))
