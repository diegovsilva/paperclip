"""Testes das rotas da página de configuração (/config, /api/config/llm, /api/status).
Usa o TestClient do FastAPI — dispara o lifespan real (mem.init_db) contra o SQLite
isolado da fixture, sem rede real."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


async def test_pagina_config_serve_html(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        r = client.get("/config")
    assert r.status_code == 200
    assert "Interestelar" in r.text
    assert "text/html" in r.headers["content-type"]


async def test_raiz_serve_a_mesma_pagina(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        r = client.get("/")
    assert r.status_code == 200
    assert "Interestelar" in r.text


async def test_obter_config_llm_traz_os_3_providers(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        r = client.get("/api/config/llm")
    assert r.status_code == 200
    data = r.json()
    assert data["providerAtivo"] == "groq"
    assert set(data["providers"].keys()) == {"groq", "openai", "anthropic"}
    # a chave setada pela fixture (test-key-not-real) tem que vir mascarada, nunca crua
    assert "test-key-not-real" not in r.text


async def test_salvar_e_trocar_provider_ativo(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        r = client.post(
            "/api/config/llm",
            json={
                "providerAtivo": "anthropic",
                "providers": {"anthropic": {"model": "claude-sonnet-5", "apiKey": "sk-ant-teste-123"}},
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["providerAtivo"] == "anthropic"
        assert data["providers"]["anthropic"]["temChave"] is True
        assert data["providers"]["anthropic"]["fonte"] == "banco"

        # confirma que persistiu de fato (nova chamada GET reflete o salvo)
        r2 = client.get("/api/config/llm")
        assert r2.json()["providerAtivo"] == "anthropic"


async def test_salvar_provider_invalido_400(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        r = client.post("/api/config/llm", json={"providerAtivo": "cohere"})
    assert r.status_code == 400


async def test_status_reflete_provider_ativo(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert data["providerAtivo"] == "groq"
    assert data["harnessOk"] is True
    # sem Paperclip real rodando no teste, a conexão deve falhar sem derrubar a rota
    assert data["paperclipOk"] is False
