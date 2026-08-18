from __future__ import annotations

import os
import random
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import asyncio
import httpx
from git import InvalidGitRepositoryError, Repo
from github import Auth, Github, GithubException
from gitlab import Gitlab, GitlabGetError

from .config import get_settings
from .logging_setup import setup_logging
from . import runtime_config as rc
from . import tools_memoria as mem

log = setup_logging()
settings = get_settings()

RepoSource = Literal["github", "gitlab", "local"]
PatternSource = Literal["reversa", "github_api", "gitlab_api", "local_groq"]


@dataclass
class RepoAccess:
    slug_empresa: str
    repo_url: str
    source: RepoSource
    auth_token: Optional[str] = None


def _ensure_repos_dir() -> Path:
    p = settings.repositorios_path
    p.mkdir(parents=True, exist_ok=True)
    return p


def _repo_local_path(slug_empresa: str) -> Path:
    return _ensure_repos_dir() / slug_empresa


async def _github_token() -> Optional[str]:
    # Página /config (SQLite) tem prioridade sobre GITHUB_TOKEN do .env — ver
    # runtime_config.resolver_github_token.
    t = await rc.resolver_github_token()
    return t or None


async def _gitlab_token() -> Optional[str]:
    t = await rc.resolver_gitlab_token()
    return t or None


def _reversa_enabled() -> bool:
    return bool(settings.reversa_claude_code_auth.get_secret_value())


def garantir_repo_local(slug_empresa: str, repo_url: str, auth: Optional[str] = None) -> Path:
    path = _repo_local_path(slug_empresa)
    if path.exists() and (path / ".git").exists():
        try:
            repo = Repo(str(path))
            origin = repo.remote(name="origin")
            current = list(origin.urls)[0] if origin.urls else None
            if current and current.strip() != repo_url.strip():
                log.warning("repo.origin_mismatch", slug=slug_empresa, esperado=repo_url, atual=current)
            try:
                origin.pull()
                log.info("repo.updated", slug=slug_empresa)
            except Exception as exc:  # noqa: BLE001
                log.warning("repo.pull_failed", slug=slug_empresa, err=str(exc))
            return path
        except InvalidGitRepositoryError:
            pass
    path.mkdir(parents=True, exist_ok=True)
    if auth:
        if repo_url.startswith("https://"):
            prefix = "https://"
            rest = repo_url[len(prefix):]
            authenticated = f"https://oauth2:{auth}@{rest}"
        else:
            authenticated = repo_url
    else:
        authenticated = repo_url
    try:
        Repo.clone_from(authenticated, to_path=str(path))
        log.info("repo.cloned", slug=slug_empresa)
    except Exception as exc:
        log.error("repo.clone_failed", slug=slug_empresa, err=str(exc))
        raise
    return path


def garantir_repo_submodulo(slug_empresa: str, repo_url: str) -> Path:
    path = _repo_local_path(slug_empresa)
    if path.exists() and (path / ".git").exists():
        try:
            Repo(str(path)).remote().pull()
            return path
        except Exception as exc:
            log.warning("repo.submodule.pull_failed", slug=slug_empresa, err=str(exc))
    path.mkdir(parents=True, exist_ok=True)
    repo_root = _ensure_repos_dir()
    try:
        root_repo = Repo.init(str(repo_root)) if not (repo_root / ".git").exists() else Repo(str(repo_root))
    except Exception:
        return garantir_repo_local(slug_empresa, repo_url)
    try:
        root_repo.create_submodule(name=slug_empresa, path=str(path.relative_to(repo_root)), url=repo_url)
        log.info("repo.submodule.added", slug=slug_empresa)
    except Exception as exc:  # noqa: BLE001
        log.warning("repo.submodule.fallback_to_clone", slug=slug_empresa, err=str(exc))
        garantir_repo_local(slug_empresa, repo_url)
    return path


def _infer_github_owner_repo(repo_url: str) -> Optional[tuple[str, str]]:
    for prefix in ("https://github.com/", "git@github.com:"):
        if repo_url.startswith(prefix):
            rest = repo_url[len(prefix):].rstrip("/").rstrip(".git")
            parts = rest.split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]
    return None


def _infer_gitlab_project(repo_url: str) -> Optional[str]:
    if "gitlab" not in repo_url.lower():
        return None
    for prefix in ("https://", "git@"):
        if repo_url.startswith(prefix):
            rest = repo_url[len(prefix):]
            after_host = rest.split("/", 1)[1] if "/" in rest else rest
            return after_host.rstrip(".git")
    return None


async def _github_tree_snapshot(repo_url: str, token: Optional[str]) -> Optional[dict]:
    parsed = _infer_github_owner_repo(repo_url)
    if not parsed:
        return None
    owner, name = parsed
    auth_cls = Auth.Token(token) if token else None
    gh = Github(auth=auth_cls) if auth_cls else Github()
    try:
        repo = gh.get_repo(f"{owner}/{name}")
        branch = repo.default_branch
        tree = repo.get_git_tree(branch, recursive=True)
        files = []
        keymarkers = {
            ".github/workflows", "docker", "Dockerfile", "docker-compose.yml",
            "package.json", "pyproject.toml", "dbt_project.yml",
            "README.md", "docs/", "src/", "models/", "dags/",
        }
        for t in tree.tree:
            if t.type == "tree":
                continue
            path = t.path
            if any(key in path for key in keymarkers):
                try:
                    content_file = repo.get_contents(path, ref=branch)
                    body = content_file.decoded_content.decode("utf-8", errors="ignore") if content_file else ""
                    files.append({"path": path, "body": body[:8000]})
                except GithubException:
                    pass
        return {"files": files, "default_branch": branch, "repo": f"{owner}/{name}"}
    except GithubException as exc:
        log.warning("github.tree.failed", repo=repo_url, err=str(exc))
        return None
    finally:
        try:
            gh.close()
        except Exception:
            pass


async def _gitlab_tree_snapshot(repo_url: str, token: Optional[str]) -> Optional[dict]:
    project = _infer_gitlab_project(repo_url)
    if not project:
        return None
    try:
        gitlab_url = await rc.resolver_gitlab_url()
        gl = Gitlab(url=gitlab_url, private_token=token)
        proj = gl.projects.get(project)
        branch = proj.default_branch or "main"
        tree = proj.repository_tree(recursive=True, ref=branch, get_all=True)
        keymarkers = {
            ".github/workflows", "docker", "Dockerfile", "docker-compose.yml",
            "package.json", "pyproject.toml", "dbt_project.yml",
            "README.md", "docs/", "src/", "models/", "dags/",
        }
        files = []
        for item in tree:
            if item.get("type") == "tree":
                continue
            path = item.get("path", "")
            if any(key in path for key in keymarkers):
                try:
                    content_resp = proj.files.get(file_path=path, ref=branch)
                    body = content_resp.decode().decode("utf-8", errors="ignore") if content_resp else ""
                    files.append({"path": path, "body": body[:8000]})
                except GitlabGetError:
                    pass
        return {"files": files, "default_branch": branch, "project": project}
    except Exception as exc:  # noqa: BLE001
        log.warning("gitlab.tree.failed", repo=repo_url, err=str(exc))
        return None


def _local_repo_snapshot(path: Path) -> dict:
    files = []
    keymarkers = (
        "Dockerfile", "docker-compose.yml", "package.json", "pyproject.toml",
        "dbt_project.yml", "README.md",
    )
    key_prefixes = (".github/workflows", "docker/", "docs/", "src/", "models/", "dags/")
    all_files: list[Path] = []
    for p in path.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            all_files.append(p)
    selection: list[Path] = []
    for p in all_files:
        rel = str(p.relative_to(path)).replace("\\", "/")
        if p.name in keymarkers or rel.startswith(key_prefixes):
            selection.append(p)
    if not selection:
        sample = min(len(all_files), max(10, int(len(all_files) * 0.1)))
        selection = random.sample(all_files, sample) if all_files else []
    for p in selection[:60]:
        try:
            rel = str(p.relative_to(path)).replace("\\", "/")
            body = p.read_text(encoding="utf-8", errors="ignore")[:8000]
            files.append({"path": rel, "body": body})
        except OSError:
            pass
    return {"files": files}


def _build_pattern_prompt(snapshot: dict, source: str) -> str:
    parts = [
        f"Contexto: análise de repositório a partir de {source}.",
        "Produza o padrão do repositório em MARKDOWN, com exatamente estas 10 seções numeradas:",
        "1. Stack de dados",
        "2. Convenções de nomenclatura (tabelas, colunas, branches, arquivos)",
        "3. Estrutura de diretórios",
        "4. Controle de qualidade",
        "5. Versionamento / CI",
        "6. Deploy e ambientes",
        "7. Segurança e segredos",
        "8. Observabilidade",
        "9. Padrões de modelagem (star schema / data vault / wide table)",
        "10. Exemplos concretos (arquivos/locais de referência)",
        "",
        "Use apenas informação abaixo. Não invente. Se não souber de uma seção escreva 'Não identificado no snapshot'.",
        "",
        "SIDEARQUIVOS DO SNAPSHOT:",
    ]
    for f in snapshot.get("files", []):
        parts.append(f"\n--- arquivo: {f.get('path')} ---\n{f.get('body', '')[:4000]}")
    return "\n".join(parts)


def hash_conteudo_fonte(texto: str) -> str:
    return mem.hash_conteudo(texto)


def _run_groq_inference_sync(prompt: str) -> str:
    api_key = settings.groq_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada")
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": "Você é um analista de arquitetura de dados. Produza markdown objetivo."},
            {"role": "user", "content": prompt},
        ],
        "temperature": settings.groq_temperature,
        "max_tokens": settings.groq_max_tokens,
    }
    resp = httpx.post(url, headers=headers, json=payload, timeout=settings.groq_timeout_sec)
    if resp.status_code >= 400:
        raise RuntimeError(f"Groq HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _groq_pattern_from_snapshot(snapshot: dict, source: PatternSource) -> tuple[str, str]:
    prompt = _build_pattern_prompt(snapshot, source)
    loop = asyncio.get_event_loop()
    md = await loop.run_in_executor(None, _run_groq_inference_sync, prompt)
    return md.strip(), hash_conteudo_fonte(md)


def _run_reversa_analyze(slug_empresa: str, repo_path: Path) -> Optional[str]:
    if not _reversa_enabled():
        return None
    auth = settings.reversa_claude_code_auth.get_secret_value()
    env = os.environ.copy()
    env["REVERSA_AUTH"] = auth
    with tempfile.TemporaryDirectory(prefix=f"reversa-{slug_empresa}-") as tmpdir:
        try:
            proc = subprocess.run(
                ["npx", "reversa@latest", "analyze", str(repo_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
                check=False,
            )
            if proc.returncode != 0:
                log.warning("reversa.analyze.failed", slug=slug_empresa, stderr=proc.stderr[:500])
                return None
            return proc.stdout or None
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.warning("reversa.unavailable", slug=slug_empresa, err=str(exc))
            return None


async def obter_ou_gerar_padrao(
    slug_empresa: str,
    repo_url: str,
    strategy_priority: Optional[list[PatternSource]] = None,
) -> str:
    cached = await mem.obter_padrao_repo(slug_empresa)
    if cached and not cached.is_expired():
        log.info("repo_pattern.cache_hit", slug=slug_empresa)
        return cached.pattern_md
    ttl_dias = (await rc.obter_tuning_resumo()).repo_pattern_ttl_days
    strategies = strategy_priority or [
        "github_api",
        "gitlab_api",
        "local_groq",
    ]
    if _reversa_enabled():
        strategies.insert(0, "reversa")
    last_error: Optional[Exception] = None
    for strategy in strategies:
        try:
            if strategy == "reversa":
                repo_path = garantir_repo_local(slug_empresa, repo_url)
                md = _run_reversa_analyze(slug_empresa, repo_path)
                if not md:
                    continue
                md_text = md.strip()
                hash_c = hash_conteudo_fonte(md_text)
                await mem.salvar_padrao_repo(slug_empresa, md_text, "reversa", hash_c, ttl_dias=ttl_dias)
                return md_text
            if strategy == "github_api":
                snap = await _github_tree_snapshot(repo_url, await _github_token())
                if not snap:
                    continue
                md_text, hash_c = await _groq_pattern_from_snapshot(snap, "github_api")
                await mem.salvar_padrao_repo(slug_empresa, md_text, "github_api", hash_c, ttl_dias=ttl_dias)
                return md_text
            if strategy == "gitlab_api":
                snap = await _gitlab_tree_snapshot(repo_url, await _gitlab_token())
                if not snap:
                    continue
                md_text, hash_c = await _groq_pattern_from_snapshot(snap, "gitlab_api")
                await mem.salvar_padrao_repo(slug_empresa, md_text, "gitlab_api", hash_c, ttl_dias=ttl_dias)
                return md_text
            if strategy == "local_groq":
                repo_path = garantir_repo_local(slug_empresa, repo_url)
                snap = _local_repo_snapshot(repo_path)
                md_text, hash_c = await _groq_pattern_from_snapshot(snap, "local_groq")
                await mem.salvar_padrao_repo(slug_empresa, md_text, "local_groq", hash_c, ttl_dias=ttl_dias)
                return md_text
        except Exception as exc:  # noqa: BLE001
            log.warning("repo_pattern.strategy_failed", strategy=strategy, err=str(exc))
            last_error = exc
    raise RuntimeError(
        f"Não foi possível obter padrão do repo {slug_empresa} com nenhuma estratégia. "
        f"Último erro: {last_error}"
    )


async def obter_ou_gerar_padrao_e_escrever_vault(
    slug_empresa: str,
    repo_url: str,
    strategy_priority: Optional[list[PatternSource]] = None,
) -> tuple[str, Path]:
    from . import tools_obsidian as obs

    md = await obter_ou_gerar_padrao(slug_empresa, repo_url, strategy_priority)
    path = obs.escrever_padrao_repo(slug_empresa, md)
    return md, path
