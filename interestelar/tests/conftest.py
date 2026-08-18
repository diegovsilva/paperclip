from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Cada teste ganha um SQLite + vault + repositorios isolados em tmp_path,
    e o cache de get_settings() é limpo antes/depois para não vazar entre testes."""
    from harness import config as config_mod

    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "interestelar.db"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("REPOSITORIOS_PATH", str(tmp_path / "repositorios"))
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    monkeypatch.setenv("PAPERCLIP_COMPANY_ID", "test-company-id")
    config_mod.get_settings.cache_clear()
    settings = config_mod.get_settings()

    # Módulos que fizeram `settings = get_settings()` no import time precisam
    # do objeto re-apontado manualmente (padrão usado em todo o harness).
    from harness import tools_memoria as mem
    from harness import tools_obsidian as obs
    from harness import webhook as wh
    from harness import runtime_config as rc
    from harness import llm_client
    from harness import ui_routes
    mem.settings = settings
    obs.settings = settings
    wh.settings = settings
    rc.settings = settings
    llm_client.settings = settings
    ui_routes.settings = settings

    yield settings

    config_mod.get_settings.cache_clear()
