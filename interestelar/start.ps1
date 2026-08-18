# Sobe o Interestelar (Paperclip + harness) via docker compose.
# (Sem acentos/travessoes de proposito -- evita mojibake dependendo do encoding
# que o PowerShell 5.1 usa pra ler o arquivo.)
#
# Uso:
#   .\start.ps1                    build + sobe em background + espera health + mostra URLs
#   .\start.ps1 -Logs               idem, e no final fica seguindo os logs (Ctrl+C so sai do tail)
#   .\start.ps1 -NoBuild            sobe sem rebuildar as imagens (mais rapido em iteracao)
#   .\start.ps1 bootstrap           gera o link de convite pra criar a 1a conta admin do Paperclip
#                                    (precisa disso ANTES do resto -- so na primeira vez)
#   .\start.ps1 chave-api           depois de criar a conta: gera e aprova a API key do harness
#   .\start.ps1 setup               roda scripts/setup_paperclip.py dentro do container harness
#                                    (idempotente -- cria/atualiza company, 7 agentes, skills, routine)
#   .\start.ps1 stop                docker compose down
#   .\start.ps1 restart             stop + start
#   .\start.ps1 logs                segue os logs dos dois servicos
#   .\start.ps1 status              docker compose ps
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "bootstrap", "chave-api", "setup", "stop", "down", "restart", "logs", "status", "ps", "help")]
    [string]$Command = "start",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs = @(),

    [switch]$Logs,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Resolve-Compose {
    $composeOk = $false
    try {
        docker compose version | Out-Null
        $composeOk = $?
    } catch {
        $composeOk = $false
    }
    if ($composeOk) { return @("docker", "compose") }

    $legacy = Get-Command docker-compose -ErrorAction SilentlyContinue
    if ($legacy) { return @("docker-compose") }

    Write-Error "Nem 'docker compose' nem 'docker-compose' foram encontrados no PATH. Instale o Docker Desktop antes de continuar."
    exit 1
}

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    $exe = $script:ComposeCmd[0]
    $baseArgs = @()
    if ($script:ComposeCmd.Count -gt 1) { $baseArgs = $script:ComposeCmd[1..($script:ComposeCmd.Count - 1)] }
    & $exe @baseArgs @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') falhou (exit $LASTEXITCODE)"
    }
}

function Ensure-Env {
    if (-not (Test-Path ".env")) {
        Write-Host "==> .env nao existe, copiando de .env.example"
        Copy-Item ".env.example" ".env"
    }

    $envLines = Get-Content ".env"
    $hasSecret = $envLines | Where-Object { $_ -match '^BETTER_AUTH_SECRET=.+' }
    if (-not $hasSecret) {
        Write-Host "==> BETTER_AUTH_SECRET vazio, gerando um valor aleatorio em .env"
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        $secret = -join ($bytes | ForEach-Object { $_.ToString("x2") })

        if ($envLines | Where-Object { $_ -match '^BETTER_AUTH_SECRET=' }) {
            $envLines = $envLines | ForEach-Object {
                if ($_ -match '^BETTER_AUTH_SECRET=') { "BETTER_AUTH_SECRET=$secret" } else { $_ }
            }
        } else {
            $envLines += "BETTER_AUTH_SECRET=$secret"
        }
        Set-Content -Path ".env" -Value $envLines -Encoding utf8
    }

    $hasGroq = (Get-Content ".env") | Where-Object { $_ -match '^GROQ_API_KEY=.+' }
    if (-not $hasGroq) {
        Write-Warning "GROQ_API_KEY esta vazio em .env -- o Paperclip sobe normalmente, mas os 7 agentes vao falhar ao processar tickets (sem LLM configurado)."
    }
}

function Wait-Health {
    Write-Host "==> Esperando Paperclip (http://localhost:3100) e Harness (http://localhost:8000) ficarem saudaveis..."
    $paperclipOk = $false
    $harnessOk = $false
    for ($i = 0; $i -lt 60; $i++) {
        if (-not $paperclipOk) {
            try {
                $r = Invoke-WebRequest -Uri "http://localhost:3100/api/health" -UseBasicParsing -TimeoutSec 3
                if ($r.StatusCode -eq 200) { $paperclipOk = $true; Write-Host "    - Paperclip OK" }
            } catch {}
        }
        if (-not $harnessOk) {
            try {
                $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3
                if ($r.StatusCode -eq 200) { $harnessOk = $true; Write-Host "    - Harness OK" }
            } catch {}
        }
        if ($paperclipOk -and $harnessOk) { return $true }
        Start-Sleep -Seconds 3
    }
    Write-Warning "Timeout esperando health check. Rode '.\start.ps1 status' e '.\start.ps1 logs' para investigar."
    return $false
}

function Cmd-Start {
    Ensure-Env
    $upArgs = @("up", "-d")
    if (-not $NoBuild) { $upArgs += "--build" }
    Write-Host "==> Subindo servicos ($($script:ComposeCmd -join ' ') $($upArgs -join ' '))"
    Invoke-Compose -ComposeArgs $upArgs
    Wait-Health | Out-Null
    Write-Host ""
    Write-Host "=== Interestelar no ar ==="
    Write-Host "Paperclip UI       : http://localhost:3100"
    Write-Host "Painel Interestelar: http://localhost:8000/config  (escolher LLM, ver status)"
    Write-Host ""
    Write-Host "Primeira vez? Rode:  .\start.ps1 setup"
    Write-Host "Ver logs:            .\start.ps1 logs"
    if ($Logs) {
        Invoke-Compose -ComposeArgs @("logs", "-f")
    }
}

function Cmd-Setup {
    Write-Host "==> Rodando setup_paperclip.py dentro do container harness..."
    Invoke-Compose -ComposeArgs (@("exec", "harness", "python", "scripts/setup_paperclip.py") + $ExtraArgs)
}

function Cmd-Bootstrap {
    # A UI do Paperclip, quando nao ha admin ainda, manda rodar "pnpm paperclipai auth
    # bootstrap-ceo" -- mas esse comando exige um config gerado por "paperclip onboard"
    # (assistente interativo), que nao roda dentro de um container headless. Geramos o
    # convite direto no banco, com a mesma estrutura que aquele comando geraria.
    $existentes = (Invoke-Compose -ComposeArgs @("exec", "-T", "db", "psql", "-U", "paperclip", "-d", "paperclip", "-tA", "-c",
        "SELECT count(*) FROM instance_user_roles WHERE role='instance_admin';") 2>&1 | Out-String).Trim()
    if ($existentes -ne "0" -and $existentes -ne "") {
        Write-Host "Ja existe um admin nesta instancia -- nao e preciso bootstrap."
        return
    }

    $tokenBytes = New-Object byte[] 24
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($tokenBytes)
    $token = "pcp_bootstrap_" + (-join ($tokenBytes | ForEach-Object { $_.ToString("x2") }))
    $hashBytes = [System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($token))
    $hash = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })

    $sql = @"
UPDATE invites SET revoked_at = now(), updated_at = now()
  WHERE invite_type = 'bootstrap_ceo' AND revoked_at IS NULL AND accepted_at IS NULL AND expires_at > now();
INSERT INTO invites (invite_type, token_hash, allowed_join_types, expires_at, invited_by_user_id)
VALUES ('bootstrap_ceo', '$hash', 'human', now() + interval '72 hours', 'system');
"@
    Invoke-Compose -ComposeArgs @("exec", "-T", "db", "psql", "-U", "paperclip", "-d", "paperclip", "-v", "ON_ERROR_STOP=1", "-c", $sql) | Out-Null

    Write-Host ""
    Write-Host "=== Convite de bootstrap gerado (expira em 72h) ==="
    Write-Host "Abra no navegador e crie a conta admin:"
    Write-Host "  http://localhost:3100/invite/$token"
    Write-Host ""
    Write-Host "Depois de criar a conta, rode:  .\start.ps1 chave-api"
}

function Cmd-ChaveApi {
    Write-Host "==> Criando pedido de acesso pro harness..."
    $resp = Invoke-RestMethod -Method Post -Uri "http://localhost:3100/api/cli-auth/challenges" `
        -ContentType "application/json" `
        -Body (@{ command = "interestelar harness"; clientName = "Interestelar Harness"; requestedAccess = "instance_admin_required" } | ConvertTo-Json)

    if (-not $resp.approvalUrl) {
        Write-Error "Nao consegui criar o pedido de acesso. O Paperclip esta no ar?"
        return
    }

    Write-Host ""
    Write-Host "Abra esse link LOGADO no Paperclip e clique em aprovar (expira em ~10min):"
    Write-Host "  $($resp.approvalUrl)"
    Write-Host ""
    Write-Host "==> Aguardando aprovacao (Ctrl+C cancela, voce pode rodar de novo depois)..."

    $status = ""
    for ($i = 0; $i -lt 150; $i++) {
        try {
            $poll = Invoke-RestMethod -Uri "http://localhost:3100/api/cli-auth/challenges/$($resp.id)?token=$($resp.token)"
            $status = $poll.status
        } catch { $status = "" }
        if ($status -eq "approved") { break }
        if ($status -eq "expired" -or $status -eq "cancelled") {
            Write-Error "Pedido expirado/cancelado antes de aprovar."
            return
        }
        Start-Sleep -Seconds 4
    }
    if ($status -ne "approved") {
        Write-Error "Timeout esperando aprovacao (12min). Rode '.\start.ps1 chave-api' de novo quando quiser."
        return
    }

    $envLines = Get-Content ".env"
    if ($envLines | Where-Object { $_ -match '^PAPERCLIP_API_KEY=' }) {
        $envLines = $envLines | ForEach-Object {
            if ($_ -match '^PAPERCLIP_API_KEY=') { "PAPERCLIP_API_KEY=$($resp.boardApiToken)" } else { $_ }
        }
    } else {
        $envLines += "PAPERCLIP_API_KEY=$($resp.boardApiToken)"
    }
    Set-Content -Path ".env" -Value $envLines -Encoding utf8

    Write-Host "==> Aprovado! Chave salva em .env -- recriando o harness pra carregar..."
    Invoke-Compose -ComposeArgs @("up", "-d", "--force-recreate", "--no-deps", "harness") | Out-Null
    Write-Host "Pronto. Rode '.\start.ps1 setup' agora (se ainda nao rodou)."
}

function Cmd-Stop { Invoke-Compose -ComposeArgs @("down") }
function Cmd-Logs { Invoke-Compose -ComposeArgs @("logs", "-f") }
function Cmd-Status { Invoke-Compose -ComposeArgs @("ps") }

$script:ComposeCmd = Resolve-Compose

switch ($Command) {
    "start"     { Cmd-Start }
    "bootstrap" { Cmd-Bootstrap }
    "chave-api" { Cmd-ChaveApi }
    "setup"   { Cmd-Setup }
    "stop"    { Cmd-Stop }
    "down"    { Cmd-Stop }
    "restart" { Cmd-Stop; Cmd-Start }
    "logs"    { Cmd-Logs }
    "status"  { Cmd-Status }
    "ps"      { Cmd-Status }
    "help"    {
        Get-Content $PSCommandPath | Select-Object -First 17 | ForEach-Object { $_ -replace '^# ?', '' }
    }
}
