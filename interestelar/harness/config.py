from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Provider de LLM ativo — "groq" | "openai" | "anthropic". Troca o provider inteiro
    # sem mexer em código (ver harness/llm_client.py). Cada provider só é usado se sua
    # respectiva *_API_KEY estiver preenchida; a chamada falha com erro claro se não.
    llm_provider: str = Field(default="groq")
    llm_temperature: float = Field(default=0.2)
    # Free tiers costumam ter TPM baixo e max_tokens conta no orçamento do request mesmo
    # que a resposta real seja bem menor — mantenha conservador por padrão.
    llm_max_tokens: int = Field(default=2048)

    groq_api_key: SecretStr = Field(default=SecretStr(""))
    # O catálogo da Groq muda com frequência — confirmado em 2026-08-17 via
    # GET https://api.groq.com/openai/v1/models que os antigos "llama-3.x-70b-versatile"
    # não existem mais. openai/gpt-oss-120b existe mas estourou o limite de TPM do free
    # tier (8000 TPM) com um prompt de teste pequeno — openai/gpt-oss-20b responde bem,
    # segue instrução ("ETAPA_CONCLUIDA" sem enrolação, diferente do qwen que vaza
    # raciocínio no output) e sobra folga de TPM. Se voltar a quebrar, rode o GET acima.
    groq_model: str = Field(default="openai/gpt-oss-20b")
    groq_timeout_sec: int = Field(default=180)

    openai_api_key: SecretStr = Field(default=SecretStr(""))
    openai_model: str = Field(default="gpt-4o-mini")
    openai_timeout_sec: int = Field(default=180)

    anthropic_api_key: SecretStr = Field(default=SecretStr(""))
    anthropic_model: str = Field(default="claude-sonnet-5")
    anthropic_timeout_sec: int = Field(default=180)

    paperclip_api_url: str = Field(default="http://localhost:3100/api")
    paperclip_api_key: SecretStr = Field(default=SecretStr(""))
    paperclip_company_id: Optional[str] = Field(default=None)
    paperclip_public_url: str = Field(default="http://localhost:3100")
    better_auth_secret: SecretStr = Field(default=SecretStr(""))

    # URL pela qual o container `paperclip` alcança o `harness` para entregar
    # heartbeats (webhook). Dentro do docker-compose isso é o hostname do serviço
    # ("http://harness:8000"), NÃO "http://localhost:8000" — localhost de dentro do
    # container paperclip aponta pra ele mesmo. Usado por scripts/setup_paperclip.py
    # ao registrar as URLs de webhook dos 7 agentes.
    harness_public_url: str = Field(default="http://harness:8000")

    github_token: SecretStr = Field(default=SecretStr(""))
    gitlab_token: SecretStr = Field(default=SecretStr(""))
    gitlab_url: str = Field(default="https://gitlab.com")

    reversa_claude_code_auth: SecretStr = Field(default=SecretStr(""))

    harness_webhook_secret: SecretStr = Field(default=SecretStr(""))
    # Senha do HTTP Basic exigido em /, /config e /api/config/* — vazia por padrão
    # (auth desligada, mesmo comportamento de sempre). Definir aqui ou pela própria
    # página passa a exigir login; banco de dados (runtime_config) tem prioridade
    # sobre este valor, igual às outras configs editáveis pela UI.
    harness_ui_password: SecretStr = Field(default=SecretStr(""))
    harness_host: str = Field(default="0.0.0.0")
    harness_port: int = Field(default=8000)
    harness_rate_limit_per_min: int = Field(default=120)
    harness_agent_timeout_sec: int = Field(default=300)

    vault_path: Path = Field(default_factory=lambda: Path("./vault"))
    repositorios_path: Path = Field(default_factory=lambda: Path("./repositorios"))
    sqlite_path: Path = Field(default_factory=lambda: Path("./db/interestelar.db"))

    log_level: str = Field(default="INFO")

    http_request_timeout_sec: int = Field(default=30)
    max_review_total: int = Field(default=3)
    max_review_per_pair: int = Field(default=2)
    repo_pattern_ttl_days: int = Field(default=7)
    hard_loop_heartbeat_cap: int = Field(default=10)
    hard_loop_window_min: int = Field(default=5)


@lru_cache
def get_settings() -> Settings:
    return Settings()
