"""Rotas da interface web do harness: painel de status (/) e configuração do
provider de LLM (/config). Página única, estática, sem build step — client-side só
chama os endpoints JSON abaixo via fetch.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import llm_client
from . import runtime_config as rc
from .config import get_settings
from .logging_setup import setup_logging
from .paperclip_client import PaperclipClient

log = setup_logging()
settings = get_settings()

router = APIRouter(include_in_schema=False)

_STATIC_DIR = Path(__file__).parent / "static"


def _read_page(nome: str) -> str:
    caminho = _STATIC_DIR / nome
    if not caminho.exists():
        raise HTTPException(status_code=404, detail=f"página {nome} não encontrada")
    return caminho.read_text(encoding="utf-8")


@router.get("/", response_class=None)
async def pagina_inicial():
    from fastapi.responses import HTMLResponse

    return HTMLResponse(_read_page("config.html"))


@router.get("/config", response_class=None)
async def pagina_config():
    from fastapi.responses import HTMLResponse

    return HTMLResponse(_read_page("config.html"))


class ProviderResumoOut(BaseModel):
    provider: str
    label: str
    model: str
    chaveMascarada: str
    temChave: bool
    fonte: str
    modelosSugeridos: list[str]
    ondeGerarChave: str


class LLMConfigOut(BaseModel):
    providerAtivo: str
    temperature: float
    maxTokens: int
    providers: dict[str, ProviderResumoOut]


@router.get("/api/config/llm", response_model=LLMConfigOut)
async def obter_config_llm() -> LLMConfigOut:
    resumo = await rc.obter_resumo()
    providers_out: dict[str, ProviderResumoOut] = {}
    for slug, info in resumo.providers.items():
        meta = rc.PROVIDER_INFO[slug]
        providers_out[slug] = ProviderResumoOut(
            provider=info.provider,
            label=info.label,
            model=info.model,
            chaveMascarada=info.chave_mascarada,
            temChave=info.tem_chave,
            fonte=info.fonte,
            modelosSugeridos=list(meta["modelos_sugeridos"]),  # type: ignore[arg-type]
            ondeGerarChave=str(meta["onde_gerar_chave"]),
        )
    return LLMConfigOut(
        providerAtivo=resumo.provider_ativo,
        temperature=resumo.temperature,
        maxTokens=resumo.max_tokens,
        providers=providers_out,
    )


class SalvarProviderIn(BaseModel):
    model: Optional[str] = None
    apiKey: Optional[str] = None


class SalvarConfigIn(BaseModel):
    providerAtivo: Optional[str] = None
    temperature: Optional[float] = None
    maxTokens: Optional[int] = None
    providers: dict[str, SalvarProviderIn] = {}


@router.post("/api/config/llm", response_model=LLMConfigOut)
async def salvar_config_llm(body: SalvarConfigIn) -> LLMConfigOut:
    for slug, dados in body.providers.items():
        if slug not in rc.PROVIDERS:
            raise HTTPException(status_code=400, detail=f"provider inválido: {slug}")
        await rc.salvar_provider_config(slug, model=dados.model, api_key=dados.apiKey)

    if body.providerAtivo is not None:
        try:
            await rc.salvar_provider_ativo(body.providerAtivo)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.temperature is not None or body.maxTokens is not None:
        await rc.salvar_temperature_max_tokens(body.temperature, body.maxTokens)

    log.info("ui.config_llm.salva", provider_ativo=body.providerAtivo)
    return await obter_config_llm()


class TestarProviderIn(BaseModel):
    provider: str
    model: str
    apiKey: str


class TestarProviderOut(BaseModel):
    ok: bool
    mensagem: str


@router.post("/api/config/llm/testar", response_model=TestarProviderOut)
async def testar_provider_llm(body: TestarProviderIn) -> TestarProviderOut:
    if body.provider not in rc.PROVIDERS:
        raise HTTPException(status_code=400, detail=f"provider inválido: {body.provider}")
    api_key = body.apiKey
    if not api_key or set(api_key.strip()) <= {"*"}:
        # Campo veio mascarado (usuário não digitou uma chave nova) — testa com a
        # chave real já salva/configurada pra esse provider.
        api_key = await rc.resolver_api_key_atual(body.provider)
        if not api_key:
            return TestarProviderOut(ok=False, mensagem="Nenhuma chave configurada para testar.")
    ok, mensagem = await llm_client.testar_provider(body.provider, body.model, api_key)
    return TestarProviderOut(ok=ok, mensagem=mensagem)


class ConnCampoOut(BaseModel):
    valor: str
    valorMascarado: str
    fonte: str
    segredo: bool


class ConnConfigOut(BaseModel):
    paperclipApiKey: ConnCampoOut
    paperclipCompanyId: ConnCampoOut
    githubToken: ConnCampoOut
    gitlabToken: ConnCampoOut
    gitlabUrl: ConnCampoOut
    harnessWebhookSecret: ConnCampoOut


def _campo_out(campo) -> ConnCampoOut:  # type: ignore[no-untyped-def]
    return ConnCampoOut(
        # Campo de segredo nunca devolve o valor puro pro cliente — só a versão
        # mascarada. Campos não-segredo (ex.: gitlabUrl, companyId) voltam completos
        # porque não há nada sensível ali e o formulário precisa do valor pra editar.
        valor="" if campo.segredo else campo.valor,
        valorMascarado=campo.valor_mascarado,
        fonte=campo.fonte,
        segredo=campo.segredo,
    )


@router.get("/api/config/conn", response_model=ConnConfigOut)
async def obter_config_conn() -> ConnConfigOut:
    resumo = await rc.obter_conn_resumo()
    return ConnConfigOut(
        paperclipApiKey=_campo_out(resumo.paperclip_api_key),
        paperclipCompanyId=_campo_out(resumo.paperclip_company_id),
        githubToken=_campo_out(resumo.github_token),
        gitlabToken=_campo_out(resumo.gitlab_token),
        gitlabUrl=_campo_out(resumo.gitlab_url),
        harnessWebhookSecret=_campo_out(resumo.harness_webhook_secret),
    )


class SalvarConnIn(BaseModel):
    paperclipApiKey: Optional[str] = None
    paperclipCompanyId: Optional[str] = None
    githubToken: Optional[str] = None
    gitlabToken: Optional[str] = None
    gitlabUrl: Optional[str] = None
    harnessWebhookSecret: Optional[str] = None


@router.post("/api/config/conn", response_model=ConnConfigOut)
async def salvar_config_conn(body: SalvarConnIn) -> ConnConfigOut:
    await rc.salvar_conn(body.model_dump())
    log.info("ui.config_conn.salva")
    return await obter_config_conn()


class TestarConnOut(BaseModel):
    ok: bool
    mensagem: str


@router.post("/api/config/conn/testar-paperclip", response_model=TestarConnOut)
async def testar_conn_paperclip() -> TestarConnOut:
    try:
        client = PaperclipClient()
        await client.health()
        cid = await rc.resolver_paperclip_company_id()
        if not cid:
            return TestarConnOut(ok=False, mensagem="Paperclip respondeu, mas nenhum company_id está configurado.")
        await client.get_company(cid)
        return TestarConnOut(ok=True, mensagem="Conectado ao Paperclip e company_id válido.")
    except Exception as exc:  # noqa: BLE001
        return TestarConnOut(ok=False, mensagem=f"Falha: {exc}"[:300])


class TuningConfigOut(BaseModel):
    maxReviewTotal: int
    maxReviewPerPair: int
    hardLoopHeartbeatCap: int
    hardLoopWindowMin: int
    repoPatternTtlDays: int


@router.get("/api/config/tuning", response_model=TuningConfigOut)
async def obter_config_tuning() -> TuningConfigOut:
    resumo = await rc.obter_tuning_resumo()
    return TuningConfigOut(
        maxReviewTotal=resumo.max_review_total,
        maxReviewPerPair=resumo.max_review_per_pair,
        hardLoopHeartbeatCap=resumo.hard_loop_heartbeat_cap,
        hardLoopWindowMin=resumo.hard_loop_window_min,
        repoPatternTtlDays=resumo.repo_pattern_ttl_days,
    )


class SalvarTuningIn(BaseModel):
    maxReviewTotal: Optional[int] = None
    maxReviewPerPair: Optional[int] = None
    hardLoopHeartbeatCap: Optional[int] = None
    hardLoopWindowMin: Optional[int] = None
    repoPatternTtlDays: Optional[int] = None


@router.post("/api/config/tuning", response_model=TuningConfigOut)
async def salvar_config_tuning(body: SalvarTuningIn) -> TuningConfigOut:
    valores = {k: v for k, v in body.model_dump().items() if v is not None}
    for campo, minimo in (
        ("maxReviewTotal", 1),
        ("maxReviewPerPair", 1),
        ("hardLoopHeartbeatCap", 1),
        ("hardLoopWindowMin", 1),
        ("repoPatternTtlDays", 1),
    ):
        if campo in valores and valores[campo] < minimo:
            raise HTTPException(status_code=400, detail=f"{campo} precisa ser >= {minimo}")
    await rc.salvar_tuning(valores)
    log.info("ui.config_tuning.salva", **valores)
    return await obter_config_tuning()


class StatusOut(BaseModel):
    harnessOk: bool
    paperclipOk: bool
    paperclipUrl: str
    vaultReady: bool
    reposReady: bool
    providerAtivo: str
    providerTemChave: bool


@router.get("/api/status", response_model=StatusOut)
async def status_geral() -> StatusOut:
    paperclip_ok = False
    try:
        client = PaperclipClient()
        await client.health()
        paperclip_ok = True
    except Exception as exc:  # noqa: BLE001
        log.debug("ui.status.paperclip_unreachable", err=str(exc)[:200])

    resumo = await rc.obter_resumo()
    ativo = resumo.providers.get(resumo.provider_ativo)

    return StatusOut(
        harnessOk=True,
        paperclipOk=paperclip_ok,
        paperclipUrl=settings.paperclip_api_url,
        vaultReady=settings.vault_path.exists(),
        reposReady=settings.repositorios_path.exists(),
        providerAtivo=resumo.provider_ativo,
        providerTemChave=bool(ativo and ativo.tem_chave),
    )
