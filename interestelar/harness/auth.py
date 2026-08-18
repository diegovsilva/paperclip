"""Autenticação HTTP Basic para a UI de configuração (`/`, `/config`, `/api/config/*`,
`/api/status`, `/aprovar-skill/*`).

Desativada por padrão — comportamento idêntico ao `HARNESS_WEBHOOK_SECRET` (ver
`webhook._verify_webhook_signature`): sem senha configurada, ninguém é bloqueado (bom
pra rodar local sem fricção). Assim que uma senha é definida (via `HARNESS_UI_PASSWORD`
no `.env` ou salva pela própria página, banco > env — mesma prioridade do resto do
`runtime_config`), toda rota protegida passa a exigir login. Sem conceito de usuário:
o navegador pede usuário+senha nativamente (diálogo do HTTP Basic), mas só a senha é
conferida.

NÃO protege `/health` (usado pelo healthcheck do Docker) nem `/webhook/*` (chamado pelo
Paperclip; já tem sua própria verificação por assinatura HMAC).
"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import runtime_config as rc

_security = HTTPBasic(auto_error=False)

_WWW_AUTHENTICATE = {"WWW-Authenticate": 'Basic realm="Interestelar"'}


async def exigir_auth_ui(
    credentials: Optional[HTTPBasicCredentials] = Depends(_security),
) -> None:
    senha_configurada = await rc.resolver_ui_password()
    if not senha_configurada:
        return
    senha_recebida = credentials.password if credentials else ""
    # compare_digest evita timing attack; ainda funciona com string vazia dos dois lados.
    if not secrets.compare_digest(senha_recebida, senha_configurada):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="senha inválida",
            headers=_WWW_AUTHENTICATE,
        )
