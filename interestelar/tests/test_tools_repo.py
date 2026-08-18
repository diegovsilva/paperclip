"""Fase 7 — caso de teste que faltava: "Fallback GitHub API"
(`tools_repo.obter_ou_gerar_padrao`).

Cobre a cadeia de estratégias (github_api -> gitlab_api -> local_groq) e o cache —
sem chamar GitHub, GitLab, Groq nem git de verdade: `_github_tree_snapshot`,
`_gitlab_tree_snapshot` e `_groq_pattern_from_snapshot` são substituídos por dublês."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio

SLUG = "empresa-teste"
REPO_URL = "https://github.com/empresa-teste/data-platform"


async def test_estrategia_padrao_usa_github_api_primeiro(isolated_settings, monkeypatch):
    from harness import tools_memoria as mem
    from harness import tools_repo as repo

    chamadas: list[str] = []

    async def _fake_github_snapshot(url, token):
        chamadas.append("github")
        return {"files": [{"path": "README.md", "body": "stack fake"}], "repo": "empresa-teste/data-platform"}

    async def _fake_gitlab_snapshot(url, token):
        chamadas.append("gitlab")
        return None

    async def _fake_groq_pattern(snapshot, source):
        chamadas.append(f"groq:{source}")
        return f"# Padrão via {source}", "hash-fake-github"

    monkeypatch.setattr(repo, "_github_tree_snapshot", _fake_github_snapshot)
    monkeypatch.setattr(repo, "_gitlab_tree_snapshot", _fake_gitlab_snapshot)
    monkeypatch.setattr(repo, "_groq_pattern_from_snapshot", _fake_groq_pattern)

    resultado = await repo.obter_ou_gerar_padrao(SLUG, REPO_URL)

    assert resultado == "# Padrão via github_api"
    assert chamadas == ["github", "groq:github_api"], "não deveria nem tentar gitlab/local"

    cache = await mem.obter_padrao_repo(SLUG)
    assert cache is not None
    assert cache.source == "github_api"
    assert cache.pattern_md == resultado


async def test_fallback_pra_gitlab_quando_github_nao_resolve(isolated_settings, monkeypatch):
    """github_api não é um repo GitHub válido / API falhou (_github_tree_snapshot
    devolve None) -> cai pra gitlab_api sem levantar erro."""
    from harness import tools_repo as repo

    chamadas: list[str] = []

    async def _fake_github_snapshot(url, token):
        chamadas.append("github")
        return None  # ex.: repo não encontrado / rate limit / token inválido

    async def _fake_gitlab_snapshot(url, token):
        chamadas.append("gitlab")
        return {"files": [{"path": "README.md", "body": "stack fake gitlab"}], "project": "empresa-teste/data"}

    async def _fake_groq_pattern(snapshot, source):
        chamadas.append(f"groq:{source}")
        return f"# Padrão via {source}", "hash-fake-gitlab"

    monkeypatch.setattr(repo, "_github_tree_snapshot", _fake_github_snapshot)
    monkeypatch.setattr(repo, "_gitlab_tree_snapshot", _fake_gitlab_snapshot)
    monkeypatch.setattr(repo, "_groq_pattern_from_snapshot", _fake_groq_pattern)

    resultado = await repo.obter_ou_gerar_padrao(SLUG, REPO_URL)

    assert resultado == "# Padrão via gitlab_api"
    assert chamadas == ["github", "gitlab", "groq:gitlab_api"]


async def test_fallback_pra_local_quando_github_e_gitlab_falham(isolated_settings, monkeypatch, tmp_path):
    """Nem GitHub nem GitLab resolvem (rede fora, token inválido, repo privado sem
    acesso, ...) -> cai pra clone local + snapshot de arquivos + Groq."""
    from harness import tools_repo as repo

    repo_local = tmp_path / "clone"
    repo_local.mkdir()
    (repo_local / "README.md").write_text("# Projeto local fake", encoding="utf-8")

    chamadas: list[str] = []

    async def _fake_github_snapshot(url, token):
        chamadas.append("github")
        return None

    async def _fake_gitlab_snapshot(url, token):
        chamadas.append("gitlab")
        return None

    def _fake_garantir_repo_local(slug_empresa, repo_url, auth=None):
        chamadas.append("clone_local")
        return repo_local

    async def _fake_groq_pattern(snapshot, source):
        chamadas.append(f"groq:{source}")
        assert any(f["path"] == "README.md" for f in snapshot["files"]), "snapshot local devia achar o README"
        return f"# Padrão via {source}", "hash-fake-local"

    monkeypatch.setattr(repo, "_github_tree_snapshot", _fake_github_snapshot)
    monkeypatch.setattr(repo, "_gitlab_tree_snapshot", _fake_gitlab_snapshot)
    monkeypatch.setattr(repo, "garantir_repo_local", _fake_garantir_repo_local)
    monkeypatch.setattr(repo, "_groq_pattern_from_snapshot", _fake_groq_pattern)

    resultado = await repo.obter_ou_gerar_padrao(SLUG, REPO_URL)

    assert resultado == "# Padrão via local_groq"
    assert chamadas == ["github", "gitlab", "clone_local", "groq:local_groq"]


async def test_cache_hit_nao_chama_nenhuma_estrategia(isolated_settings, monkeypatch):
    """Padrão já em cache (e não expirado) -> nem GitHub, nem GitLab, nem Groq são
    tocados."""
    from harness import tools_memoria as mem
    from harness import tools_repo as repo

    await mem.salvar_padrao_repo(SLUG, "# Padrão já em cache", "github_api", "hash-cache", ttl_dias=7)

    async def _explode(*a, **kw):
        raise AssertionError("não deveria chamar nenhuma estratégia com cache válido")

    monkeypatch.setattr(repo, "_github_tree_snapshot", _explode)
    monkeypatch.setattr(repo, "_gitlab_tree_snapshot", _explode)
    monkeypatch.setattr(repo, "garantir_repo_local", _explode)
    monkeypatch.setattr(repo, "_groq_pattern_from_snapshot", _explode)

    resultado = await repo.obter_ou_gerar_padrao(SLUG, REPO_URL)

    assert resultado == "# Padrão já em cache"


async def test_todas_as_estrategias_falhando_levanta_erro_claro(isolated_settings, monkeypatch):
    from harness import tools_repo as repo

    async def _falha_github(url, token):
        return None

    async def _falha_gitlab(url, token):
        return None

    def _falha_local(slug_empresa, repo_url, auth=None):
        raise RuntimeError("clone falhou: repo privado sem token")

    monkeypatch.setattr(repo, "_github_tree_snapshot", _falha_github)
    monkeypatch.setattr(repo, "_gitlab_tree_snapshot", _falha_gitlab)
    monkeypatch.setattr(repo, "garantir_repo_local", _falha_local)

    with pytest.raises(RuntimeError, match="Não foi possível obter padrão"):
        await repo.obter_ou_gerar_padrao(SLUG, REPO_URL)
