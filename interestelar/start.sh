#!/usr/bin/env bash
# Sobe o Interestelar (Paperclip + harness) via docker compose.
#
# Uso:
#   ./start.sh                 build + sobe em background + espera health + mostra URLs
#   ./start.sh --logs          idem, e no final fica seguindo os logs (Ctrl+C só sai do tail)
#   ./start.sh --no-build      sobe sem rebuildar as imagens (mais rápido em iteração)
#   ./start.sh bootstrap       gera o link de convite pra criar a 1ª conta admin do Paperclip
#                               (precisa disso ANTES do resto — só na primeira vez)
#   ./start.sh chave-api       depois de criar a conta: gera e aprova a API key do harness
#   ./start.sh setup           roda scripts/setup_paperclip.py dentro do container harness
#                               (idempotente — cria/atualiza company, 7 agentes, skills, routine)
#   ./start.sh stop            docker compose down
#   ./start.sh restart         stop + start
#   ./start.sh logs            segue os logs dos dois serviços
#   ./start.sh status          docker compose ps
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

COMPOSE=(docker compose)
BUILD_ARGS=(--build)
FOLLOW_LOGS=0

# --- resolve docker compose (plugin novo `docker compose` vs binário antigo `docker-compose`) ---
if ! docker compose version >/dev/null 2>&1; then
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    echo "Erro: nem 'docker compose' nem 'docker-compose' foram encontrados no PATH." >&2
    echo "Instale o Docker Desktop (ou docker-compose-plugin) antes de continuar." >&2
    exit 1
  fi
fi

ensure_env() {
  if [ ! -f .env ]; then
    echo "==> .env não existe, copiando de .env.example"
    cp .env.example .env
  fi

  # BETTER_AUTH_SECRET é obrigatório no docker-compose.yml (${BETTER_AUTH_SECRET:?...}) —
  # se estiver vazio o `docker compose up` falha de cara. Gera um valor aleatório na
  # primeira vez pra não travar quem está só tentando subir o projeto.
  if ! grep -qE '^BETTER_AUTH_SECRET=.+' .env; then
    echo "==> BETTER_AUTH_SECRET vazio, gerando um valor aleatório em .env"
    secret="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))' 2>/dev/null || head -c32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    if grep -q '^BETTER_AUTH_SECRET=' .env; then
      # substitui a linha existente (mesmo que vazia)
      tmp="$(mktemp)"
      sed "s|^BETTER_AUTH_SECRET=.*|BETTER_AUTH_SECRET=${secret}|" .env > "$tmp" && mv "$tmp" .env
    else
      echo "BETTER_AUTH_SECRET=${secret}" >> .env
    fi
  fi

  if ! grep -qE '^GROQ_API_KEY=.+' .env; then
    echo "==> Aviso: GROQ_API_KEY está vazio em .env — o Paperclip sobe normalmente," \
         "mas os 7 agentes vão falhar ao processar tickets (sem LLM configurado)." >&2
  fi
}

wait_health() {
  echo "==> Esperando Paperclip (http://localhost:3100) e Harness (http://localhost:8000) ficarem saudáveis..."
  local tries=60
  local paperclip_ok=0
  local harness_ok=0
  for _ in $(seq 1 "$tries"); do
    if [ "$paperclip_ok" -eq 0 ] && curl -fsS "http://localhost:3100/api/health" >/dev/null 2>&1; then
      paperclip_ok=1
      echo "    - Paperclip OK"
    fi
    if [ "$harness_ok" -eq 0 ] && curl -fsS "http://localhost:8000/health" >/dev/null 2>&1; then
      harness_ok=1
      echo "    - Harness OK"
    fi
    if [ "$paperclip_ok" -eq 1 ] && [ "$harness_ok" -eq 1 ]; then
      return 0
    fi
    sleep 3
  done
  echo "Aviso: timeout esperando health check. Rode '$0 status' e '$0 logs' para investigar." >&2
  return 1
}

cmd_start() {
  ensure_env
  echo "==> Subindo serviços (${COMPOSE[*]} up -d ${BUILD_ARGS[*]:-})"
  "${COMPOSE[@]}" up -d "${BUILD_ARGS[@]}"
  wait_health || true
  echo
  echo "=== Interestelar no ar ==="
  echo "Paperclip UI      : http://localhost:3100"
  echo "Painel Interestelar: http://localhost:8000/config  (escolher LLM, ver status)"
  echo
  echo "Primeira vez? Rode:  ./start.sh setup"
  echo "Ver logs:            ./start.sh logs"
  if [ "$FOLLOW_LOGS" -eq 1 ]; then
    "${COMPOSE[@]}" logs -f
  fi
}

cmd_setup() {
  echo "==> Rodando setup_paperclip.py dentro do container harness..."
  "${COMPOSE[@]}" exec harness python scripts/setup_paperclip.py "$@"
}

cmd_bootstrap() {
  # A UI do Paperclip, quando não há admin ainda, manda rodar `pnpm paperclipai auth
  # bootstrap-ceo` — mas esse comando exige um config gerado por `paperclip onboard`
  # (assistente interativo), que não roda dentro de um container headless. Geramos o
  # convite direto no banco, com a mesma estrutura que aquele comando geraria.
  local existentes
  existentes="$("${COMPOSE[@]}" exec -T db psql -U paperclip -d paperclip -tA -c \
    "SELECT count(*) FROM instance_user_roles WHERE role='instance_admin';" 2>/dev/null | tr -d '[:space:]')"
  if [ "$existentes" != "0" ] && [ -n "$existentes" ]; then
    echo "Já existe um admin nesta instância — não é preciso bootstrap."
    echo "Esqueceu a senha? Gerencie contas direto no Postgres ou recrie o volume do banco."
    return 0
  fi

  local token hash
  token="pcp_bootstrap_$(openssl rand -hex 24 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(24))')"
  hash="$(printf '%s' "$token" | openssl dgst -sha256 -r | awk '{print $1}')"

  "${COMPOSE[@]}" exec -T db psql -U paperclip -d paperclip -v ON_ERROR_STOP=1 -c "
    UPDATE invites SET revoked_at = now(), updated_at = now()
      WHERE invite_type = 'bootstrap_ceo' AND revoked_at IS NULL AND accepted_at IS NULL AND expires_at > now();
    INSERT INTO invites (invite_type, token_hash, allowed_join_types, expires_at, invited_by_user_id)
    VALUES ('bootstrap_ceo', '${hash}', 'human', now() + interval '72 hours', 'system');
  " >/dev/null

  echo
  echo "=== Convite de bootstrap gerado (expira em 72h) ==="
  echo "Abra no navegador e crie a conta admin:"
  echo "  http://localhost:3100/invite/${token}"
  echo
  echo "Depois de criar a conta, rode:  ./start.sh chave-api"
}

_extrair_campo_json() {
  # _extrair_campo_json '<json>' campo -- só serve pra campos de string simples (sem
  # aspas escapadas dentro do valor), mas evita depender de python/jq no host.
  echo "$1" | grep -o "\"$2\":\"[^\"]*\"" | head -1 | sed -E "s/\"$2\":\"([^\"]*)\"/\1/"
}

cmd_chave_api() {
  # Não existe botão "gerar API key" nas configurações — o fluxo real (o mesmo que
  # `paperclip auth login` da CLI usa) é: criar um pedido de acesso (challenge),
  # aprovar logado no navegador, e então a chave pré-gerada no passo 1 vira válida.
  echo "==> Criando pedido de acesso pro harness..."
  local resp approval_url board_token challenge_id challenge_token
  resp="$(curl -sS -X POST http://localhost:3100/api/cli-auth/challenges \
    -H "Content-Type: application/json" \
    -d '{"command":"interestelar harness","clientName":"Interestelar Harness","requestedAccess":"instance_admin_required"}')"
  approval_url="$(_extrair_campo_json "$resp" approvalUrl)"
  board_token="$(_extrair_campo_json "$resp" boardApiToken)"
  challenge_id="$(_extrair_campo_json "$resp" id)"
  challenge_token="$(_extrair_campo_json "$resp" token)"

  if [ -z "$approval_url" ]; then
    echo "Erro: não consegui criar o pedido de acesso. O Paperclip está no ar? Resposta: $resp" >&2
    return 1
  fi

  echo
  echo "Abra esse link LOGADO no Paperclip e clique em aprovar (expira em ~10min):"
  echo "  $approval_url"
  echo
  echo "==> Aguardando aprovação (Ctrl+C cancela, você pode rodar de novo depois)..."

  local status=""
  for _ in $(seq 1 150); do
    status="$(_extrair_campo_json "$(curl -sS "http://localhost:3100/api/cli-auth/challenges/${challenge_id}?token=${challenge_token}")" status)"
    [ "$status" = "approved" ] && break
    if [ "$status" = "expired" ] || [ "$status" = "cancelled" ]; then
      echo "Pedido expirado/cancelado antes de aprovar." >&2
      return 1
    fi
    sleep 4
  done
  if [ "$status" != "approved" ]; then
    echo "Timeout esperando aprovação (12min). Rode './start.sh chave-api' de novo quando quiser." >&2
    return 1
  fi

  if grep -q '^PAPERCLIP_API_KEY=' .env; then
    tmp="$(mktemp)"
    sed "s|^PAPERCLIP_API_KEY=.*|PAPERCLIP_API_KEY=${board_token}|" .env > "$tmp" && mv "$tmp" .env
  else
    echo "PAPERCLIP_API_KEY=${board_token}" >> .env
  fi
  echo "==> Aprovado! Chave salva em .env — recriando o harness pra carregar..."
  "${COMPOSE[@]}" up -d --force-recreate --no-deps harness >/dev/null
  echo "Pronto. Rode './start.sh setup' agora (se ainda não rodou)."
}

cmd_stop() {
  "${COMPOSE[@]}" down
}

cmd_logs() {
  "${COMPOSE[@]}" logs -f
}

cmd_status() {
  "${COMPOSE[@]}" ps
}

case "${1:-start}" in
  start)
    shift || true
    for arg in "$@"; do
      case "$arg" in
        --logs) FOLLOW_LOGS=1 ;;
        --no-build) BUILD_ARGS=() ;;
        *) echo "Argumento desconhecido: $arg" >&2; exit 1 ;;
      esac
    done
    cmd_start
    ;;
  --logs)
    FOLLOW_LOGS=1
    cmd_start
    ;;
  --no-build)
    BUILD_ARGS=()
    cmd_start
    ;;
  bootstrap)
    cmd_bootstrap
    ;;
  chave-api)
    cmd_chave_api
    ;;
  setup)
    shift || true
    cmd_setup "$@"
    ;;
  stop|down)
    cmd_stop
    ;;
  restart)
    cmd_stop
    cmd_start
    ;;
  logs)
    cmd_logs
    ;;
  status|ps)
    cmd_status
    ;;
  -h|--help|help)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *)
    echo "Comando desconhecido: $1" >&2
    echo "Uso: $0 [start|--logs|--no-build|bootstrap|chave-api|setup|stop|restart|logs|status|help]" >&2
    exit 1
    ;;
esac
