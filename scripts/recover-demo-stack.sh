#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$repo_root/.runtime"
mkdir -p "$runtime_dir"

log() {
    printf '[recover-demo] %s\n' "$1"
}

warn() {
    printf '[recover-demo] WARN: %s\n' "$1" >&2
}

read_env_value() {
    local key="$1"
    local env_file="$repo_root/.env"

    if [[ ! -f "$env_file" ]]; then
        return 0
    fi

    awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, "", $0); print $0; exit }' "$env_file"
}

http_ok() {
    local url="$1"
    curl -fsS --max-time 5 "$url" >/dev/null 2>&1
}

wait_for_http_ok() {
    local url="$1"
    local label="$2"
    local attempts="${3:-45}"
    local attempt

    for ((attempt = 1; attempt <= attempts; attempt += 1)); do
        if http_ok "$url"; then
            return 0
        fi
        sleep 1
    done

    warn "$label did not become healthy at $url"
    return 1
}

port_in_use() {
    local port="$1"

    if ! command -v ss >/dev/null 2>&1; then
        return 1
    fi

    ss -ltn "sport = :$port" 2>/dev/null | awk 'NR > 1 { found = 1 } END { exit found ? 0 : 1 }'
}

start_detached() {
    local name="$1"
    local log_file="$2"
    shift 2

    : >"$log_file"
    nohup "$@" >>"$log_file" 2>&1 < /dev/null &
    local pid=$!
    echo "$pid" >"$runtime_dir/$name.pid"
    printf '%s' "$pid"
}

require_command() {
    local name="$1"

    if ! command -v "$name" >/dev/null 2>&1; then
        warn "Missing required command: $name"
        exit 1
    fi
}

parse_url_host_port() {
    python3 - "$1" <<'PY'
from urllib.parse import urlparse
import sys

url = urlparse(sys.argv[1])
host = url.hostname or "127.0.0.1"
port = url.port or (443 if url.scheme == "https" else 80)
print(host)
print(port)
PY
}

require_command curl
require_command docker
require_command python3
require_command uv

backend_port="${CRE_PORT:-$(read_env_value CRE_PORT)}"
backend_port="${backend_port:-8020}"
backend_health_url="http://127.0.0.1:${backend_port}/health/deps"

ocr_backend_url="${CRE_OCR_BACKEND_URL:-$(read_env_value CRE_OCR_BACKEND_URL)}"
ocr_backend_url="${ocr_backend_url:-http://127.0.0.1:5003}"
readarray -t ocr_endpoint < <(parse_url_host_port "$ocr_backend_url")
ocr_host="${ocr_endpoint[0]}"
ocr_port="${ocr_endpoint[1]}"
ocr_health_url="${ocr_backend_url%/}/health"

public_callback_url="${CLOUDFLARE_PUBLIC_CALLBACK_URL:-$(read_env_value CLOUDFLARE_PUBLIC_CALLBACK_URL)}"
public_health_url=""
if [[ -n "$public_callback_url" ]]; then
    public_health_url="${public_callback_url%/}/health/deps"
fi

cloudflared_config="${CLOUDFLARED_CONFIG:-$HOME/.cloudflared/config.yml}"
cloudflared_tunnel="${CLOUDFLARED_TUNNEL:-cre-knowledge-engine}"
glm_ocr_backend_dir="${GLM_OCR_BACKEND_DIR:-/home/Aaditya/GLM-OCR/apps/backend}"
glm_ocr_reasoner_api_url="${GLM_OCR_REASONER_API_URL:-http://127.0.0.1:8000/v1/chat/completions}"
glm_ocr_reasoner_model="${GLM_OCR_REASONER_MODEL:-qwen3-4b-instruct-2507-nvfp4}"
glm_ocr_reasoner_api_key="${GLM_OCR_REASONER_API_KEY:-dummy}"

exit_code=0

log "Starting Postgres and Qdrant via docker compose"
(cd "$repo_root" && docker compose up -d postgres qdrant >/dev/null)

if http_ok "$backend_health_url"; then
    log "FastAPI already healthy at $backend_health_url"
else
    if port_in_use "$backend_port"; then
        warn "Port $backend_port is already listening, but FastAPI health is unavailable; inspect manually"
        exit_code=1
    else
        log "Starting FastAPI app on port $backend_port"
        backend_log="$runtime_dir/backend.log"
        backend_pid=$(start_detached \
            backend \
            "$backend_log" \
            bash -lc "cd \"$repo_root\" && uv run uvicorn app.main:app --host 0.0.0.0 --port \"$backend_port\" --reload --no-access-log")
        if wait_for_http_ok "$backend_health_url" "FastAPI" 45; then
            log "FastAPI recovered with pid $backend_pid"
        else
            warn "FastAPI failed to become healthy; see $backend_log"
            exit_code=1
        fi
    fi
fi

if http_ok "$ocr_health_url"; then
    log "GLM-OCR already healthy at $ocr_health_url"
else
    if port_in_use "$ocr_port"; then
        warn "Port $ocr_port is already listening, but OCR health is unavailable; inspect manually"
        exit_code=1
    elif [[ ! -d "$glm_ocr_backend_dir" ]]; then
        warn "GLM-OCR backend directory not found at $glm_ocr_backend_dir"
        exit_code=1
    else
        log "Starting GLM-OCR from $glm_ocr_backend_dir"
        ocr_log="$runtime_dir/ocr.log"
        ocr_pid=$(start_detached \
            ocr \
            "$ocr_log" \
            bash -lc "cd \"$glm_ocr_backend_dir\" && env -i HOME=\"$HOME\" PATH=\"$PATH\" LANG=\"${LANG:-C.UTF-8}\" HOST=\"$ocr_host\" PORT=\"$ocr_port\" BACKEND_PUBLIC_URL=\"$ocr_backend_url\" REASONER_API_URL=\"$glm_ocr_reasoner_api_url\" REASONER_MODEL=\"$glm_ocr_reasoner_model\" REASONER_API_KEY=\"$glm_ocr_reasoner_api_key\" .venv/bin/uvicorn app.main:app --host \"$ocr_host\" --port \"$ocr_port\"")
        if wait_for_http_ok "$ocr_health_url" "GLM-OCR" 45; then
            log "GLM-OCR recovered with pid $ocr_pid"
        else
            warn "GLM-OCR failed to become healthy; see $ocr_log"
            exit_code=1
        fi
    fi
fi

if [[ -z "$public_health_url" ]]; then
    warn "CLOUDFLARE_PUBLIC_CALLBACK_URL is not configured; skipping public tunnel recovery"
elif http_ok "$public_health_url"; then
    log "Public callback already healthy at $public_health_url"
elif ! command -v cloudflared >/dev/null 2>&1; then
    warn "cloudflared is not installed; public callback remains unavailable"
    exit_code=1
elif [[ ! -f "$cloudflared_config" ]]; then
    warn "cloudflared config not found at $cloudflared_config"
    exit_code=1
else
    log "Starting cloudflared tunnel $cloudflared_tunnel"
    tunnel_log="$runtime_dir/cloudflared.log"
    tunnel_pid=$(start_detached \
        cloudflared \
        "$tunnel_log" \
        bash -lc "cloudflared tunnel --config \"$cloudflared_config\" run \"$cloudflared_tunnel\"")
    if wait_for_http_ok "$public_health_url" "Public callback" 45; then
        log "Public callback recovered with cloudflared pid $tunnel_pid"
    else
        warn "Public callback failed to recover; see $tunnel_log"
        exit_code=1
    fi
fi

log "Recovery check complete"
log "Backend health: $backend_health_url"
log "OCR health: $ocr_health_url"
if [[ -n "$public_health_url" ]]; then
    log "Public health: $public_health_url"
fi
log "Runtime logs: $runtime_dir"

exit "$exit_code"