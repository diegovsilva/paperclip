"""Testes do cliente de LLM com provider configurável. Não faz chamada de rede real —
só valida o dispatch por provider e as mensagens de erro de configuração ausente."""
from __future__ import annotations

import pytest

from harness import llm_client
from harness import runtime_config as rc

pytestmark = pytest.mark.asyncio


def _refetch_settings(monkeypatch, **env):
    """Recarrega Settings() com env vars extras e reaponta todos os módulos que
    guardam `settings` em module-level (mesmo padrão da fixture isolated_settings,
    mas com overrides adicionais específicos do teste)."""
    from harness import config as config_mod

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config_mod.get_settings.cache_clear()
    settings = config_mod.get_settings()
    llm_client.settings = settings
    rc.settings = settings
    return settings


async def test_provider_desconhecido_falha_com_mensagem_clara(isolated_settings, monkeypatch):
    from harness import config as config_mod

    _refetch_settings(monkeypatch, LLM_PROVIDER="cohere")
    try:
        with pytest.raises(llm_client.LLMError, match="cohere"):
            await llm_client.chat_completion("sistema", "usuario")
    finally:
        config_mod.get_settings.cache_clear()


@pytest.mark.parametrize(
    "provider,env_key,expected_snippet",
    [
        ("groq", "GROQ_API_KEY", "GROQ_API_KEY"),
        ("openai", "OPENAI_API_KEY", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    ],
)
async def test_chave_ausente_falha_sem_chamar_rede(
    isolated_settings, monkeypatch, provider, env_key, expected_snippet
):
    from harness import config as config_mod

    _refetch_settings(monkeypatch, LLM_PROVIDER=provider, **{env_key: ""})
    try:
        with pytest.raises(llm_client.LLMError, match=expected_snippet):
            await llm_client.chat_completion("sistema", "usuario")
    finally:
        config_mod.get_settings.cache_clear()


async def test_default_provider_e_groq():
    from harness.config import Settings

    assert Settings().llm_provider == "groq"
