"""Testes da configuração dinâmica de provider de LLM (runtime_config.py) — a base da
página /config: banco de dados tem prioridade sobre o .env, mascaramento de chave nunca
vaza o valor real, e string de só bullets (campo mascarado não editado) não sobrescreve
a chave já salva."""
from __future__ import annotations

import pytest

from harness import runtime_config as rc

pytestmark = pytest.mark.asyncio


async def test_sem_config_salva_usa_default_do_env(isolated_settings):
    cfg = await rc.resolver_provider_ativo()
    assert cfg.provider == "groq"
    assert cfg.api_key == "test-key-not-real"  # setado pela fixture isolated_settings


async def test_salvar_provider_ativo_troca_o_resolvido(isolated_settings):
    await rc.salvar_provider_config("anthropic", api_key="sk-ant-real-key-123")
    await rc.salvar_provider_ativo("anthropic")

    cfg = await rc.resolver_provider_ativo()
    assert cfg.provider == "anthropic"
    assert cfg.api_key == "sk-ant-real-key-123"


async def test_provider_invalido_rejeitado(isolated_settings):
    with pytest.raises(ValueError):
        await rc.salvar_provider_ativo("cohere")


async def test_string_de_bullets_nao_sobrescreve_chave_existente(isolated_settings):
    await rc.salvar_provider_config("openai", api_key="sk-original-123456")
    # simula o campo mascarado voltando sem edição (só bullets, como a UI mostra)
    await rc.salvar_provider_config("openai", api_key="********")

    valores = await rc.mem.obter_configs([rc._chave_api_key("openai")])
    assert valores[rc._chave_api_key("openai")] == "sk-original-123456"


async def test_resumo_mascara_a_chave(isolated_settings):
    await rc.salvar_provider_config("groq", api_key="gsk_abcdefghijklmnopqrstuvwxyz")
    resumo = await rc.obter_resumo()
    mascarada = resumo.providers["groq"].chave_mascarada
    assert "abcdefghijklmnopqrstuvwxyz" not in mascarada
    assert mascarada.startswith("gsk_")
    assert resumo.providers["groq"].fonte == "banco"


async def test_provider_sem_chave_nenhuma_fonte(isolated_settings):
    resumo = await rc.obter_resumo()
    assert resumo.providers["anthropic"].fonte == "nenhum"
    assert resumo.providers["anthropic"].tem_chave is False


async def test_temperature_max_tokens_default_e_override(isolated_settings):
    temp, tokens = await rc.resolver_temperature_max_tokens()
    assert temp == 0.2
    assert tokens == 2048

    await rc.salvar_temperature_max_tokens(0.7, 4096)
    temp, tokens = await rc.resolver_temperature_max_tokens()
    assert temp == 0.7
    assert tokens == 4096


async def test_resolver_api_key_atual_de_provider_nao_ativo(isolated_settings):
    # provider ativo continua groq, mas testamos a chave de outro provider
    await rc.salvar_provider_config("openai", api_key="sk-outro-provider")
    chave = await rc.resolver_api_key_atual("openai")
    assert chave == "sk-outro-provider"
