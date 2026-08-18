"""Configuração dinâmica editável pela página de configurações (`/config`) sem precisar
mexer no `.env` nem reiniciar o container: provider de LLM, tokens/segredos de conexão
(Paperclip, GitHub, GitLab, webhook) e parâmetros de comportamento (limites de revisão,
proteção de loop, TTL de cache).

Prioridade de resolução, igual em todas as categorias: valor salvo no SQLite (via página
de configurações) > valor do `.env` (Settings). Isso permite reconfigurar em produção
sem rebuild, mas o `.env` continua funcionando como default pra quem prefere configurar
por lá.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import tools_memoria as mem
from .config import get_settings

settings = get_settings()

PROVIDERS = ("groq", "openai", "anthropic")

# Nomes amigáveis + modelos sugeridos, usados pela página de configurações.
PROVIDER_INFO: dict[str, dict[str, object]] = {
    "groq": {
        "label": "Groq",
        "modelos_sugeridos": ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "groq/compound-mini"],
        "onde_gerar_chave": "https://console.groq.com/keys",
    },
    "openai": {
        "label": "OpenAI",
        "modelos_sugeridos": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
        "onde_gerar_chave": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "modelos_sugeridos": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"],
        "onde_gerar_chave": "https://console.anthropic.com/settings/keys",
    },
}

_CHAVE_PROVIDER = "llm_provider"
_CHAVE_TEMPERATURE = "llm_temperature"
_CHAVE_MAX_TOKENS = "llm_max_tokens"


def _chave_api_key(provider: str) -> str:
    return f"llm_{provider}_api_key"


def _chave_model(provider: str) -> str:
    return f"llm_{provider}_model"


def _mascarar(valor: str) -> str:
    # Usa "*" (ASCII puro) em vez de um caractere especial tipo bullet — já tivemos
    # mojibake de verdade num caractere não-ASCII neste ambiente Windows (ver histórico
    # do projeto), então evitamos a categoria inteira de problema aqui.
    if not valor:
        return ""
    if len(valor) <= 8:
        return "*" * len(valor)
    return f"{valor[:4]}{'*' * 8}{valor[-4:]}"


def _default_api_key(provider: str) -> str:
    if provider == "groq":
        return settings.groq_api_key.get_secret_value()
    if provider == "openai":
        return settings.openai_api_key.get_secret_value()
    if provider == "anthropic":
        return settings.anthropic_api_key.get_secret_value()
    return ""


def _default_model(provider: str) -> str:
    if provider == "groq":
        return settings.groq_model
    if provider == "openai":
        return settings.openai_model
    if provider == "anthropic":
        return settings.anthropic_model
    return ""


@dataclass
class ProviderConfig:
    provider: str
    model: str
    api_key: str

    @property
    def tem_chave(self) -> bool:
        return bool(self.api_key)


@dataclass
class LLMConfigResumo:
    provider_ativo: str
    temperature: float
    max_tokens: int
    providers: dict[str, "ProviderResumo"]


@dataclass
class ProviderResumo:
    provider: str
    label: str
    model: str
    chave_mascarada: str
    tem_chave: bool
    fonte: str  # "banco" | "env" | "nenhum"


async def resolver_provider_ativo() -> ProviderConfig:
    """Config efetiva usada pra chamar o LLM — chamado a cada `chat_completion`,
    então uma troca feita na página de configurações vale já no próximo heartbeat,
    sem precisar reiniciar o harness.

    NÃO cai pra "groq" silenciosamente se o valor configurado for inválido — isso
    esconderia um erro de configuração real (ex. LLM_PROVIDER com typo) atrás de uma
    mensagem enganosa ("GROQ_API_KEY não configurada" quando na verdade o usuário
    queria outro provider). `chat_completion` já trata provider desconhecido com um
    erro claro; deixa passar pra lá.
    """
    valores = await mem.obter_configs([_CHAVE_PROVIDER])
    provider = (valores.get(_CHAVE_PROVIDER) or settings.llm_provider or "groq").strip().lower()
    if provider not in PROVIDERS:
        return ProviderConfig(provider=provider, model="", api_key="")

    chaves = await mem.obter_configs([_chave_api_key(provider), _chave_model(provider)])
    api_key = chaves.get(_chave_api_key(provider)) or _default_api_key(provider)
    model = chaves.get(_chave_model(provider)) or _default_model(provider)
    return ProviderConfig(provider=provider, model=model, api_key=api_key)


async def resolver_api_key_atual(provider: str) -> str:
    """Chave efetiva de um provider específico (banco > .env), independente de ele ser
    o provider ATIVO no momento ou não — usado pelo botão "Testar conexão" quando o
    usuário testa um provider diferente do que está selecionado."""
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        return ""
    valores = await mem.obter_configs([_chave_api_key(provider)])
    return valores.get(_chave_api_key(provider)) or _default_api_key(provider)


async def resolver_temperature_max_tokens() -> tuple[float, int]:
    valores = await mem.obter_configs([_CHAVE_TEMPERATURE, _CHAVE_MAX_TOKENS])
    temp_raw = valores.get(_CHAVE_TEMPERATURE)
    tokens_raw = valores.get(_CHAVE_MAX_TOKENS)
    temperature = float(temp_raw) if temp_raw not in (None, "") else settings.llm_temperature
    max_tokens = int(tokens_raw) if tokens_raw not in (None, "") else settings.llm_max_tokens
    return temperature, max_tokens


async def obter_resumo() -> LLMConfigResumo:
    """Estado completo pra renderizar a página de configurações: provider ativo +
    status de cada provider suportado (tem chave? de onde veio? qual modelo?)."""
    chaves_provider = [_CHAVE_PROVIDER, _CHAVE_TEMPERATURE, _CHAVE_MAX_TOKENS]
    for p in PROVIDERS:
        chaves_provider.append(_chave_api_key(p))
        chaves_provider.append(_chave_model(p))
    valores = await mem.obter_configs(chaves_provider)

    provider_ativo = (valores.get(_CHAVE_PROVIDER) or settings.llm_provider or "groq").strip().lower()
    if provider_ativo not in PROVIDERS:
        provider_ativo = "groq"

    providers: dict[str, ProviderResumo] = {}
    for p in PROVIDERS:
        chave_db = valores.get(_chave_api_key(p))
        model_db = valores.get(_chave_model(p))
        if chave_db:
            api_key, fonte = chave_db, "banco"
        else:
            api_key, fonte = _default_api_key(p), ("env" if _default_api_key(p) else "nenhum")
        model = model_db or _default_model(p)
        providers[p] = ProviderResumo(
            provider=p,
            label=str(PROVIDER_INFO[p]["label"]),
            model=model,
            chave_mascarada=_mascarar(api_key),
            tem_chave=bool(api_key),
            fonte=fonte,
        )

    temperature, max_tokens = await resolver_temperature_max_tokens()
    return LLMConfigResumo(
        provider_ativo=provider_ativo,
        temperature=temperature,
        max_tokens=max_tokens,
        providers=providers,
    )


async def salvar_provider_ativo(provider: str) -> None:
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"provider inválido: {provider!r}. Válidos: {', '.join(PROVIDERS)}")
    await mem.salvar_config(_CHAVE_PROVIDER, provider)


async def salvar_provider_config(
    provider: str,
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> None:
    provider = provider.strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"provider inválido: {provider!r}. Válidos: {', '.join(PROVIDERS)}")
    pares: dict[str, Optional[str]] = {}
    if model is not None:
        pares[_chave_model(provider)] = model.strip() or None
    if api_key is not None and api_key != "":
        # Uma string de só asteriscos vem da UI quando o usuário não mexeu no campo
        # mascarado — não sobrescreve a chave real com isso.
        if not set(api_key.strip()) <= {"*"}:
            pares[_chave_api_key(provider)] = api_key.strip()
    if pares:
        await mem.salvar_configs(pares)


async def salvar_temperature_max_tokens(temperature: Optional[float], max_tokens: Optional[int]) -> None:
    pares: dict[str, Optional[str]] = {}
    if temperature is not None:
        pares[_CHAVE_TEMPERATURE] = str(temperature)
    if max_tokens is not None:
        pares[_CHAVE_MAX_TOKENS] = str(max_tokens)
    if pares:
        await mem.salvar_configs(pares)


# ─── Conexão: tokens/segredos usados pra falar com Paperclip, GitHub e GitLab ──────

_CHAVE_PAPERCLIP_API_KEY = "conn_paperclip_api_key"
_CHAVE_PAPERCLIP_COMPANY_ID = "conn_paperclip_company_id"
_CHAVE_GITHUB_TOKEN = "conn_github_token"
_CHAVE_GITLAB_TOKEN = "conn_gitlab_token"
_CHAVE_GITLAB_URL = "conn_gitlab_url"
_CHAVE_WEBHOOK_SECRET = "conn_harness_webhook_secret"

# Campos "segredo" (mascarados na UI, nunca sobrescritos por uma string de só
# asteriscos — mesma regra do salvar_provider_config) vs. campos de texto plano.
_CONN_SECRETOS = (
    _CHAVE_PAPERCLIP_API_KEY,
    _CHAVE_GITHUB_TOKEN,
    _CHAVE_GITLAB_TOKEN,
    _CHAVE_WEBHOOK_SECRET,
)


@dataclass
class ConnCampo:
    chave: str
    valor: str
    valor_mascarado: str
    fonte: str  # "banco" | "env" | "nenhum"
    segredo: bool


@dataclass
class ConnResumo:
    paperclip_api_key: ConnCampo
    paperclip_company_id: ConnCampo
    github_token: ConnCampo
    gitlab_token: ConnCampo
    gitlab_url: ConnCampo
    harness_webhook_secret: ConnCampo


def _conn_defaults() -> dict[str, str]:
    return {
        _CHAVE_PAPERCLIP_API_KEY: settings.paperclip_api_key.get_secret_value(),
        _CHAVE_PAPERCLIP_COMPANY_ID: settings.paperclip_company_id or "",
        _CHAVE_GITHUB_TOKEN: settings.github_token.get_secret_value(),
        _CHAVE_GITLAB_TOKEN: settings.gitlab_token.get_secret_value(),
        _CHAVE_GITLAB_URL: settings.gitlab_url,
        _CHAVE_WEBHOOK_SECRET: settings.harness_webhook_secret.get_secret_value(),
    }


async def obter_conn_resumo() -> ConnResumo:
    defaults = _conn_defaults()
    valores = await mem.obter_configs(list(defaults.keys()))
    campos: dict[str, ConnCampo] = {}
    for chave, default in defaults.items():
        db_val = valores.get(chave)
        if db_val:
            valor, fonte = db_val, "banco"
        else:
            valor, fonte = default, ("env" if default else "nenhum")
        segredo = chave in _CONN_SECRETOS
        campos[chave] = ConnCampo(
            chave=chave,
            valor=valor,
            valor_mascarado=_mascarar(valor) if segredo else valor,
            fonte=fonte,
            segredo=segredo,
        )
    return ConnResumo(
        paperclip_api_key=campos[_CHAVE_PAPERCLIP_API_KEY],
        paperclip_company_id=campos[_CHAVE_PAPERCLIP_COMPANY_ID],
        github_token=campos[_CHAVE_GITHUB_TOKEN],
        gitlab_token=campos[_CHAVE_GITLAB_TOKEN],
        gitlab_url=campos[_CHAVE_GITLAB_URL],
        harness_webhook_secret=campos[_CHAVE_WEBHOOK_SECRET],
    )


async def resolver_conn_valor(chave: str) -> str:
    """Valor efetivo (banco > env) de um único campo de conexão — usado pelos módulos
    que consomem essas credenciais (paperclip_client.py, tools_repo.py, webhook.py)."""
    defaults = _conn_defaults()
    if chave not in defaults:
        raise ValueError(f"chave de conexão desconhecida: {chave!r}")
    valores = await mem.obter_configs([chave])
    return valores.get(chave) or defaults[chave]


# Wrappers nomeados pros campos de conexão mais usados — evita call sites fora deste
# módulo dependendo das chaves internas (_CHAVE_*) do SQLite.
async def resolver_paperclip_api_key() -> str:
    return await resolver_conn_valor(_CHAVE_PAPERCLIP_API_KEY)


async def resolver_paperclip_company_id() -> str:
    return await resolver_conn_valor(_CHAVE_PAPERCLIP_COMPANY_ID)


async def resolver_github_token() -> str:
    return await resolver_conn_valor(_CHAVE_GITHUB_TOKEN)


async def resolver_gitlab_token() -> str:
    return await resolver_conn_valor(_CHAVE_GITLAB_TOKEN)


async def resolver_gitlab_url() -> str:
    return await resolver_conn_valor(_CHAVE_GITLAB_URL)


async def resolver_harness_webhook_secret() -> str:
    return await resolver_conn_valor(_CHAVE_WEBHOOK_SECRET)


async def salvar_conn(valores: dict[str, Optional[str]]) -> None:
    """`valores` usa as chaves de campo "amigáveis" (ex.: "paperclipApiKey"), não as
    chaves internas do SQLite — mapeadas aqui pra manter o payload da API isolado dos
    detalhes de armazenamento."""
    mapa = {
        "paperclipApiKey": _CHAVE_PAPERCLIP_API_KEY,
        "paperclipCompanyId": _CHAVE_PAPERCLIP_COMPANY_ID,
        "githubToken": _CHAVE_GITHUB_TOKEN,
        "gitlabToken": _CHAVE_GITLAB_TOKEN,
        "gitlabUrl": _CHAVE_GITLAB_URL,
        "harnessWebhookSecret": _CHAVE_WEBHOOK_SECRET,
    }
    pares: dict[str, Optional[str]] = {}
    for campo_api, chave_db in mapa.items():
        if campo_api not in valores or valores[campo_api] is None:
            continue
        novo_valor = valores[campo_api].strip()
        if chave_db in _CONN_SECRETOS and set(novo_valor) <= {"*"}:
            # Campo mascarado que o usuário não tocou — não sobrescreve o valor real.
            continue
        pares[chave_db] = novo_valor or None
    if pares:
        await mem.salvar_configs(pares)


# ─── Tuning: parâmetros de comportamento (limites de revisão, proteção de loop, TTL) ──

_CHAVE_MAX_REVIEW_TOTAL = "tune_max_review_total"
_CHAVE_MAX_REVIEW_PER_PAIR = "tune_max_review_per_pair"
_CHAVE_HARD_LOOP_CAP = "tune_hard_loop_heartbeat_cap"
_CHAVE_HARD_LOOP_WINDOW_MIN = "tune_hard_loop_window_min"
_CHAVE_REPO_PATTERN_TTL_DIAS = "tune_repo_pattern_ttl_days"

_TUNING_CHAVES = (
    _CHAVE_MAX_REVIEW_TOTAL,
    _CHAVE_MAX_REVIEW_PER_PAIR,
    _CHAVE_HARD_LOOP_CAP,
    _CHAVE_HARD_LOOP_WINDOW_MIN,
    _CHAVE_REPO_PATTERN_TTL_DIAS,
)


@dataclass
class TuningResumo:
    max_review_total: int
    max_review_per_pair: int
    hard_loop_heartbeat_cap: int
    hard_loop_window_min: int
    repo_pattern_ttl_days: int


def _tuning_defaults() -> dict[str, int]:
    return {
        _CHAVE_MAX_REVIEW_TOTAL: settings.max_review_total,
        _CHAVE_MAX_REVIEW_PER_PAIR: settings.max_review_per_pair,
        _CHAVE_HARD_LOOP_CAP: settings.hard_loop_heartbeat_cap,
        _CHAVE_HARD_LOOP_WINDOW_MIN: settings.hard_loop_window_min,
        _CHAVE_REPO_PATTERN_TTL_DIAS: settings.repo_pattern_ttl_days,
    }


async def obter_tuning_resumo() -> TuningResumo:
    defaults = _tuning_defaults()
    valores = await mem.obter_configs(list(_TUNING_CHAVES))

    def _int_ou_default(chave: str) -> int:
        raw = valores.get(chave)
        return int(raw) if raw not in (None, "") else defaults[chave]

    return TuningResumo(
        max_review_total=_int_ou_default(_CHAVE_MAX_REVIEW_TOTAL),
        max_review_per_pair=_int_ou_default(_CHAVE_MAX_REVIEW_PER_PAIR),
        hard_loop_heartbeat_cap=_int_ou_default(_CHAVE_HARD_LOOP_CAP),
        hard_loop_window_min=_int_ou_default(_CHAVE_HARD_LOOP_WINDOW_MIN),
        repo_pattern_ttl_days=_int_ou_default(_CHAVE_REPO_PATTERN_TTL_DIAS),
    )


async def salvar_tuning(valores: dict[str, Optional[int]]) -> None:
    mapa = {
        "maxReviewTotal": _CHAVE_MAX_REVIEW_TOTAL,
        "maxReviewPerPair": _CHAVE_MAX_REVIEW_PER_PAIR,
        "hardLoopHeartbeatCap": _CHAVE_HARD_LOOP_CAP,
        "hardLoopWindowMin": _CHAVE_HARD_LOOP_WINDOW_MIN,
        "repoPatternTtlDays": _CHAVE_REPO_PATTERN_TTL_DIAS,
    }
    pares: dict[str, Optional[str]] = {}
    for campo_api, chave_db in mapa.items():
        if campo_api not in valores or valores[campo_api] is None:
            continue
        pares[chave_db] = str(valores[campo_api])
    if pares:
        await mem.salvar_configs(pares)
