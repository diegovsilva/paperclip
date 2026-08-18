from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import get_settings
from .logging_setup import setup_logging

log = setup_logging()
settings = get_settings()

_SLUG_INVALID = re.compile(r"[^a-z0-9\-]+")


def _slugify(text: str, maxlen: int = 60) -> str:
    s = text.strip().lower().replace("á", "a").replace("â", "a").replace("ã", "a")
    s = s.replace("é", "e").replace("ê", "e")
    s = s.replace("í", "i").replace("ó", "o").replace("ô", "o").replace("õ", "o")
    s = s.replace("ú", "u").replace("ç", "c")
    s = _SLUG_INVALID.sub("-", s)
    s = s.strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:maxlen].strip("-") or "sem-titulo"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _yaml_frontmatter(metadata: dict[str, Any], body: str) -> str:
    if metadata:
        fm = yaml.safe_dump(
            metadata,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).strip()
        return f"---\n{fm}\n---\n\n{body}\n"
    return f"{body}\n"


def append_section_existing(path: Path, data: str, section_header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        _atomic_write(path, data)
        return
    existing = path.read_text(encoding="utf-8")
    separator = f"\n\n## {section_header}\n\n"
    new_content = existing.rstrip() + separator + data.strip() + "\n"
    _atomic_write(path, new_content)


@dataclass
class DemandaMeta:
    ticket_id: str
    repo_empresa: Optional[str] = None
    agentes_envolvidos: Optional[list[str]] = None
    tags: Optional[list[str]] = None
    status: str = "done"
    links: Optional[list[str]] = None


def escrever_padrao_repo(slug_empresa: str, conteudo_md: str) -> Path:
    vault = settings.vault_path
    vault.mkdir(parents=True, exist_ok=True)
    target = vault / "Padrão do Repositório.md"
    header = f"## Empresa: {slug_empresa} — atualizado em {datetime.utcnow().isoformat(timespec='seconds')}Z"
    body = f"{header}\n\n{conteudo_md.strip()}\n"
    append_section_existing(target, body, f"Empresa {slug_empresa}")
    log.info("vault.padrao_repo.escrito", slug=slug_empresa, path=str(target))
    return target


def escrever_demanda(
    ticket_id: str,
    titulo: str,
    conteudo_md: str,
    meta: Optional[DemandaMeta] = None,
) -> Path:
    hoje = datetime.utcnow().date().isoformat()
    filename = f"{hoje}-{_slugify(titulo)}.md"
    target = settings.vault_path / "Demandas" / filename
    meta = meta or DemandaMeta(ticket_id=ticket_id)
    front: dict[str, Any] = {
        "ticket_id": ticket_id,
        "tipo": "demanda-consolidada",
        "pessoa": "Head",
        "data_criacao": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "agentes_envolvidos": meta.agentes_envolvidos or [],
        "status": meta.status,
        "repo_empresa": meta.repo_empresa or "",
        "tags": meta.tags or [],
        "links": meta.links or [f"[[Padrão do Repositório#{meta.repo_empresa}]]"] if meta.repo_empresa else [],
    }
    body = f"# {titulo}\n\n{conteudo_md.strip()}\n"
    full = _yaml_frontmatter(front, body)
    _atomic_write(target, full)
    log.info("vault.demanda.escrita", ticket=ticket_id, path=str(target))
    return target


def escrever_nota_agente(
    papel_agente: str,
    ticket_id: str,
    titulo_curto: str,
    resumo: str,
    repo_empresa: Optional[str] = None,
) -> Path:
    target_dir = settings.vault_path / "Agentes" / papel_agente
    filename = f"{ticket_id}-{_slugify(titulo_curto)}.md"
    target = target_dir / filename
    front = {
        "ticket_id": ticket_id,
        "tipo": "etapa-agente",
        "pessoa": papel_agente,
        "data_criacao": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "done",
        "repo_empresa": repo_empresa or "",
        "tags": [papel_agente.lower()],
        "links": [f"[[Padrão do Repositório]]"],
    }
    body = f"# {papel_agente} — etapa #{ticket_id}\n\n{resumo.strip()}\n"
    _atomic_write(target, _yaml_frontmatter(front, body))
    log.info(
        "vault.nota_agente.escrita",
        papel=papel_agente,
        ticket=ticket_id,
        path=str(target),
    )
    return target


def listar_demandas(limite: int = 20) -> list[dict[str, Any]]:
    demandas_dir = settings.vault_path / "Demandas"
    if not demandas_dir.exists():
        return []
    files = sorted(demandas_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for p in files[:limite]:
        text = p.read_text(encoding="utf-8")
        primeira_linha = next(
            (ln.strip() for ln in text.splitlines() if ln.strip().startswith("# ")),
            p.stem,
        )
        out.append({"path": str(p), "titulo": primeira_linha.lstrip("# ").strip(), "mtime": p.stat().st_mtime})
    return out
