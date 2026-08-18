"""Testes de autenticação HTTP Basic da UI (/, /config, /api/config/*, /api/status,
/aprovar-skill/*). Ver harness/auth.py."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


def _basic(usuario: str, senha: str) -> dict[str, str]:
    token = base64.b64encode(f"{usuario}:{senha}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def test_sem_senha_configurada_nao_bloqueia(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        assert client.get("/config").status_code == 200
        r = client.get("/api/status")
        assert r.status_code == 200
        assert r.json()["authHabilitada"] is False


async def test_definir_senha_passa_a_exigir_login(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        # Bootstrap: a própria definição da primeira senha roda sem credenciais,
        # porque nenhuma senha existe ainda nesse momento (mesmo raciocínio do
        # HARNESS_WEBHOOK_SECRET: vazio = aberto).
        r = client.post("/api/config/ui-password", json={"novaSenha": "senha-de-teste-123"})
        assert r.status_code == 200
        assert r.json() == {"ok": True, "habilitada": True}

        r = client.get("/config")
        assert r.status_code == 401
        assert r.headers["www-authenticate"].startswith("Basic")

        r = client.get("/config", headers=_basic("qualquer", "errada"))
        assert r.status_code == 401

        # Usuário é ignorado — só a senha conta.
        r = client.get("/config", headers=_basic("nome-qualquer", "senha-de-teste-123"))
        assert r.status_code == 200

        r = client.get("/api/status", headers=_basic("x", "senha-de-teste-123"))
        assert r.status_code == 200
        assert r.json()["authHabilitada"] is True


async def test_senha_curta_e_rejeitada(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        r = client.post("/api/config/ui-password", json={"novaSenha": "curta"})
    assert r.status_code == 400


async def test_senha_em_branco_reabre_para_o_valor_do_env(isolated_settings, monkeypatch):
    from harness import config as config_mod
    from harness import runtime_config as rc
    from harness.webhook import app

    monkeypatch.setenv("HARNESS_UI_PASSWORD", "")
    config_mod.get_settings.cache_clear()
    rc.settings = config_mod.get_settings()

    with TestClient(app) as client:
        client.post("/api/config/ui-password", json={"novaSenha": "senha-de-teste-123"})
        assert client.get("/config").status_code == 401

        # Resetar a senha também é uma rota protegida agora que uma senha existe —
        # precisa da senha atual pra provar que "voltar a ficar aberto" foi intencional.
        r = client.post(
            "/api/config/ui-password",
            json={"novaSenha": ""},
            headers=_basic("x", "senha-de-teste-123"),
        )
        assert r.status_code == 200
        assert r.json()["habilitada"] is False
        assert client.get("/config").status_code == 200

    config_mod.get_settings.cache_clear()


async def test_health_e_webhook_nao_exigem_auth(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        client.post("/api/config/ui-password", json={"novaSenha": "senha-de-teste-123"})
        assert client.get("/health").status_code == 200


async def test_aprovar_skill_exige_auth(isolated_settings):
    from harness.webhook import app

    with TestClient(app) as client:
        client.post("/api/config/ui-password", json={"novaSenha": "senha-de-teste-123"})

        r = client.post("/aprovar-skill/skill-inexistente")
        assert r.status_code == 401

        # Com senha certa a auth passa e cai na lógica real da rota (404 porque a
        # skill não existe — não é mais 401).
        r = client.post(
            "/aprovar-skill/skill-inexistente",
            headers=_basic("x", "senha-de-teste-123"),
        )
        assert r.status_code == 404
