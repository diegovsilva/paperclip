"""Cliente de LLM com provider configurável — ponto único de chamada ao modelo,
usado tanto por engine_prompt.py (agentes de demanda) quanto por
tools_skill_curator.py (curadoria de skills).

Provider ativo, modelo e chave são resolvidos em runtime via runtime_config.py — banco
de dados (editável pela página de configurações em /config) tem prioridade, `.env`
(Settings) é o fallback. Trocar o provider na página vale já no próximo heartbeat, sem
reiniciar o harness.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from . import runtime_config
from .config import get_settings
from .logging_setup import setup_logging

log = setup_logging()
settings = get_settings()

SUPPORTED_PROVIDERS = runtime_config.PROVIDERS


class LLMError(RuntimeError):
    """Erro de chamada ao LLM — provider não configurado, chave ausente, ou todas as
    tentativas de retry esgotadas."""


async def chat_completion(
    system: str,
    user: str,
    *,
    retries: int = 3,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> str:
    """Chama o provider de LLM ativo no momento (ver runtime_config) e retorna o texto
    da resposta.

    Todas as três implementações de provider compartilham a mesma assinatura e o mesmo
    padrão de retry com backoff exponencial (1.2s, 2.4s, 4.8s, ...) em erros
    transitórios (rate limit / 5xx) — erros de configuração (4xx que não seja rate
    limit, chave ausente) falham rápido sem retry.
    """
    cfg = await runtime_config.resolver_provider_ativo()
    default_temp, default_tokens = await runtime_config.resolver_temperature_max_tokens()
    temp = default_temp if temperature is None else temperature
    tokens = default_tokens if max_tokens is None else max_tokens

    if cfg.provider == "groq":
        return await _groq(system, user, cfg, retries=retries, max_tokens=tokens, temperature=temp)
    if cfg.provider == "openai":
        return await _openai(system, user, cfg, retries=retries, max_tokens=tokens, temperature=temp)
    if cfg.provider == "anthropic":
        return await _anthropic(system, user, cfg, retries=retries, max_tokens=tokens, temperature=temp)
    raise LLMError(
        f"LLM_PROVIDER '{cfg.provider}' desconhecido. Válidos: {', '.join(SUPPORTED_PROVIDERS)}."
    )


async def _retry_backoff(provider: str, tentativa: int, exc: Exception) -> None:
    espera = min(30, (2**tentativa) * 1.2)
    log.warning(
        "llm.retry",
        provider=provider,
        attempt=tentativa,
        type=exc.__class__.__name__,
        wait_sec=espera,
    )
    await asyncio.sleep(espera)


async def _groq(
    system: str,
    user: str,
    cfg: runtime_config.ProviderConfig,
    *,
    retries: int,
    max_tokens: int,
    temperature: float,
) -> str:
    from groq import AsyncGroq, InternalServerError, RateLimitError

    if not cfg.api_key:
        raise LLMError("Groq selecionado, mas nenhuma API key configurada (página /config ou GROQ_API_KEY no .env).")
    client = AsyncGroq(api_key=cfg.api_key)
    last_err: Optional[Exception] = None
    for tentativa in range(1, retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=settings.groq_timeout_sec,
            )
            return resp.choices[0].message.content or ""
        except (RateLimitError, InternalServerError) as exc:
            last_err = exc
            await _retry_backoff("groq", tentativa, exc)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.error("llm.error", provider="groq", type=exc.__class__.__name__, err=str(exc)[:400])
            break
    raise LLMError(f"Groq falhou após {retries} tentativas. Último erro: {last_err}")


async def _openai(
    system: str,
    user: str,
    cfg: runtime_config.ProviderConfig,
    *,
    retries: int,
    max_tokens: int,
    temperature: float,
) -> str:
    from openai import APIStatusError, AsyncOpenAI, RateLimitError

    if not cfg.api_key:
        raise LLMError("OpenAI selecionado, mas nenhuma API key configurada (página /config ou OPENAI_API_KEY no .env).")
    client = AsyncOpenAI(api_key=cfg.api_key, timeout=settings.openai_timeout_sec)
    last_err: Optional[Exception] = None
    for tentativa in range(1, retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        except RateLimitError as exc:
            last_err = exc
            await _retry_backoff("openai", tentativa, exc)
        except APIStatusError as exc:
            last_err = exc
            if exc.status_code >= 500:
                await _retry_backoff("openai", tentativa, exc)
                continue
            log.error("llm.error", provider="openai", type=exc.__class__.__name__, err=str(exc)[:400])
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.error("llm.error", provider="openai", type=exc.__class__.__name__, err=str(exc)[:400])
            break
    raise LLMError(f"OpenAI falhou após {retries} tentativas. Último erro: {last_err}")


async def _anthropic(
    system: str,
    user: str,
    cfg: runtime_config.ProviderConfig,
    *,
    retries: int,
    max_tokens: int,
    temperature: float,
) -> str:
    from anthropic import AsyncAnthropic, APIStatusError, RateLimitError

    if not cfg.api_key:
        raise LLMError("Anthropic selecionado, mas nenhuma API key configurada (página /config ou ANTHROPIC_API_KEY no .env).")
    client = AsyncAnthropic(api_key=cfg.api_key, timeout=settings.anthropic_timeout_sec)
    last_err: Optional[Exception] = None
    for tentativa in range(1, retries + 1):
        try:
            resp = await client.messages.create(
                model=cfg.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            # A Anthropic devolve uma lista de blocos de conteúdo (texto/tool_use/...) —
            # concatena só os blocos de texto.
            partes = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            return "\n".join(partes)
        except RateLimitError as exc:
            last_err = exc
            await _retry_backoff("anthropic", tentativa, exc)
        except APIStatusError as exc:
            last_err = exc
            if exc.status_code >= 500:
                await _retry_backoff("anthropic", tentativa, exc)
                continue
            log.error("llm.error", provider="anthropic", type=exc.__class__.__name__, err=str(exc)[:400])
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.error("llm.error", provider="anthropic", type=exc.__class__.__name__, err=str(exc)[:400])
            break
    raise LLMError(f"Anthropic falhou após {retries} tentativas. Último erro: {last_err}")


async def testar_provider(provider: str, model: str, api_key: str) -> tuple[bool, str]:
    """Testa uma combinação provider/modelo/chave SEM salvar nada — usado pelo botão
    "Testar conexão" da página de configurações antes do usuário confirmar a troca."""
    cfg = runtime_config.ProviderConfig(provider=provider, model=model, api_key=api_key)
    # max_tokens baixo (10) já causou resposta vazia em modelos que gastam tokens com
    # "raciocínio" antes do texto final (ex. openai/gpt-oss-*) — 64 dá folga suficiente
    # sem deixar o teste lento.
    sistema = "Você é um teste de conexão. Responda direto, sem explicação nem raciocínio."
    pergunta = "Responda com exatamente uma palavra: OK"
    try:
        if provider == "groq":
            texto = await _groq(sistema, pergunta, cfg, retries=1, max_tokens=64, temperature=0)
        elif provider == "openai":
            texto = await _openai(sistema, pergunta, cfg, retries=1, max_tokens=64, temperature=0)
        elif provider == "anthropic":
            texto = await _anthropic(sistema, pergunta, cfg, retries=1, max_tokens=64, temperature=0)
        else:
            return False, f"Provider desconhecido: {provider}"
        if not texto.strip():
            return False, "Conectou, mas o modelo devolveu resposta vazia (tente outro modelo)."
        return True, texto.strip()[:200]
    except LLMError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {str(exc)[:300]}"
