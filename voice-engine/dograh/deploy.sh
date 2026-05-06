#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  deploy.sh — One-command deployment script for Dograh + PocketTTS stack
#
#  Works on CPU-only machines out of the box.
#  GPU (NVIDIA) is auto-detected and enabled if available.
#
#  Usage:
#    chmod +x deploy.sh
#    ./deploy.sh                          # Deploy (auto-detects GPU)
#    ./deploy.sh --pull-model llama3.2:1b # Use a smaller/different model
#    ./deploy.sh --no-gpu                 # Force CPU even if GPU present
#    ./deploy.sh --down                   # Stop everything (keep data)
#    ./deploy.sh --reset                  # Stop + delete ALL data (clean slate)
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}══ $* ══${RESET}"; }

# ── Parse flags ──────────────────────────────────────────────────────────────
FORCE_NO_GPU=false
PULL_MODEL=""
ACTION="deploy"

while [[ $# -gt 0 ]]; do
  case $1 in
    --no-gpu)       FORCE_NO_GPU=true; shift ;;
    --pull-model)   PULL_MODEL="$2"; shift 2 ;;
    --down)         ACTION="down"; shift ;;
    --reset)        ACTION="reset"; shift ;;
    -h|--help)
      sed -n '3,12p' "$0" | sed 's/^#  //'
      exit 0 ;;
    *) error "Unknown option: $1 (use --help for usage)"; exit 1 ;;
  esac
done

# ── .env bootstrapping ───────────────────────────────────────────────────────
header "Environment"
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    warn ".env was not found — created from .env.example"
    warn ">>> Open .env and set HF_TOKEN before running again <<<"
    warn "    Get your free token at: https://huggingface.co/settings/tokens"
    exit 1   # Exit so user sets the token before downloading models
  else
    error ".env.example missing. Cannot continue."
    exit 1
  fi
else
  success ".env found"
fi

# Source .env (make vars available to this script)
set -a; source .env; set +a

OLLAMA_MODEL="${PULL_MODEL:-${OLLAMA_MODEL:-llama3.2:3b}}"

# ── Tear-down ─────────────────────────────────────────────────────────────────
if [[ "$ACTION" == "down" ]]; then
  header "Stopping stack (data volumes preserved)"
  docker compose down --remove-orphans
  success "Stack stopped."
  exit 0
fi

if [[ "$ACTION" == "reset" ]]; then
  header "Full reset"
  echo -e "${RED}WARNING: This deletes all data — database, recordings, model cache.${RESET}"
  read -r -p "Type 'yes' to confirm: " confirm
  [[ "$confirm" == "yes" ]] || { info "Aborted."; exit 0; }
  docker compose down --volumes --remove-orphans
  success "Full reset complete."
  exit 0
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────
header "Pre-flight checks"

command -v docker >/dev/null 2>&1 \
  || { error "Docker not found. Install Docker Engine: https://docs.docker.com/engine/install/"; exit 1; }
success "Docker: $(docker --version | head -1)"

docker compose version >/dev/null 2>&1 \
  || { error "docker compose v2 not found. Update Docker or install the plugin."; exit 1; }
success "Docker Compose: $(docker compose version --short 2>/dev/null || echo 'v2')"

# ── GPU auto-detection (no heavy image pull needed) ───────────────────────────
header "Hardware detection"
GPU_AVAILABLE=false

if $FORCE_NO_GPU; then
  warn "--no-gpu flag set — running in CPU-only mode"
else
  # Check without pulling any image: just query the docker daemon
  if docker info 2>/dev/null | grep -qi "nvidia" || \
     (command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1); then
    GPU_AVAILABLE=true
    GPU_INFO=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA GPU")
    success "GPU detected: ${GPU_INFO}"
  else
    warn "No NVIDIA GPU detected — running in CPU-only mode"
    warn "  (Ollama will use CPU inference — expect ~20s per response on llama3.2:3b)"
    warn "  TIP: Use llama3.2:1b for faster CPU responses: ./deploy.sh --pull-model llama3.2:1b"
  fi
fi

# Generate compose override for GPU if available
if $GPU_AVAILABLE; then
  info "Writing GPU compose override..."
  cat > /tmp/docker-compose.gpu.yml <<'EOF'
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
EOF
  COMPOSE_ARGS="-f docker-compose.yaml -f /tmp/docker-compose.gpu.yml"
  success "GPU mode enabled for Ollama"
else
  COMPOSE_ARGS="-f docker-compose.yaml"
  info "CPU mode — no GPU override needed"
fi

# Convenience alias that includes the right compose files
dc() { docker compose $COMPOSE_ARGS "$@"; }

# ── Check HF_TOKEN ────────────────────────────────────────────────────────────
header "HuggingFace token"
HF_TOKEN="${HF_TOKEN:-}"
if [[ -z "$HF_TOKEN" || "$HF_TOKEN" == "hf_REPLACEME" ]]; then
  error "HF_TOKEN is not set in .env!"
  error "The PocketTTS model requires a HuggingFace token."
  error "  1. Create a free account at https://huggingface.co"
  error "  2. Accept the model license at https://huggingface.co/kyutai/pocket-tts"
  error "  3. Create a token at https://huggingface.co/settings/tokens"
  error "  4. Set HF_TOKEN=hf_your_token in .env"
  exit 1
fi
success "HF_TOKEN is set"

# ── Build all images ──────────────────────────────────────────────────────────
header "Building Docker images"
info "This takes a few minutes on first run (downloading base images + pip packages)..."

info "Building Dograh API..."
dc build --quiet api

info "Building Dograh UI..."
dc build --quiet ui

info "Building PocketTTS..."
dc build --quiet pocket-tts

success "All images built"

# ── Start infrastructure ──────────────────────────────────────────────────────
header "Starting infrastructure"
dc up -d postgres redis minio

info "Waiting for PostgreSQL..."
_wait_healthy() {
  local svc="$1" max="${2:-60}" n=0
  while [[ "$(docker inspect --format='{{.State.Health.Status}}' "$(dc ps -q "$svc" 2>/dev/null)" 2>/dev/null)" != "healthy" ]]; do
    sleep 2; n=$((n+2))
    [[ $n -ge $max ]] && { warn "$svc health check timed out"; return 1; }
  done
  return 0
}
_wait_healthy postgres 60
success "PostgreSQL ready"

_wait_healthy minio 60
success "MinIO ready"

# ── Start Ollama ──────────────────────────────────────────────────────────────
header "Starting Ollama (local LLM)"
dc up -d ollama
sleep 5   # Give Ollama a moment to bind its port

info "Pulling Ollama model: ${OLLAMA_MODEL} (downloads ~2 GB on first run)..."
_pull_attempt() {
  dc exec -T ollama ollama pull "$OLLAMA_MODEL" 2>&1
}
if ! _pull_attempt; then
  warn "First pull attempt failed — retrying in 10s..."
  sleep 10
  _pull_attempt || warn "Model pull failed — you can pull manually: docker compose exec ollama ollama pull ${OLLAMA_MODEL}"
fi
success "Ollama model '${OLLAMA_MODEL}' ready"

# Pre-load model into memory (eliminates 20s cold-start on first call)
info "Pre-loading model into memory..."
dc exec -T ollama sh -c "ollama run ${OLLAMA_MODEL} '' 2>/dev/null; true"
success "Model loaded into RAM (OLLAMA_KEEP_ALIVE=-1 keeps it there)"

# ── Start PocketTTS ───────────────────────────────────────────────────────────
header "Starting PocketTTS"
info "First run downloads the Kyutai model (~438 MB). This may take 5-10 minutes..."
dc up -d pocket-tts voice-files

TIMEOUT=600
ELAPSED=0
while [[ "$(docker inspect --format='{{.State.Health.Status}}' "$(dc ps -q pocket-tts 2>/dev/null)" 2>/dev/null)" != "healthy" ]]; do
  sleep 5
  ELAPSED=$((ELAPSED + 5))
  PBAR=$(printf '#%.0s' $(seq 1 $((ELAPSED * 20 / TIMEOUT))))
  printf "\r${CYAN}[INFO]${RESET}  PocketTTS: [%-20s] %ds / %ds" "$PBAR" "$ELAPSED" "$TIMEOUT"
  if [[ $ELAPSED -ge $TIMEOUT ]]; then
    echo ""
    warn "PocketTTS health check timed out — check logs: docker compose logs pocket-tts"
    break
  fi
done
echo ""
success "PocketTTS ready"

# ── Start Cloudflared tunnel ──────────────────────────────────────────────────
header "Starting Cloudflared tunnel"
dc up -d cloudflared
success "Cloudflared started (public URL printed in its logs)"

# ── Start Dograh API ──────────────────────────────────────────────────────────
header "Starting Dograh API"
dc up -d api

info "Waiting for API health check..."
TIMEOUT=120; ELAPSED=0
until curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1; do
  sleep 3; ELAPSED=$((ELAPSED + 3))
  printf "\r${CYAN}[INFO]${RESET}  API starting... %ds" "$ELAPSED"
  [[ $ELAPSED -ge $TIMEOUT ]] && { echo ""; warn "API health check timed out"; break; }
done
echo ""
success "Dograh API is healthy"

# ── Start Dograh UI ───────────────────────────────────────────────────────────
header "Starting Dograh UI"
dc up -d ui
success "UI started"

# ── Summary ───────────────────────────────────────────────────────────────────
header "Deployment complete 🎉"
GPU_LABEL=$( $GPU_AVAILABLE && echo "GPU (${GPU_INFO})" || echo "CPU-only" )
echo ""
echo -e "  Mode: ${BOLD}${GPU_LABEL}${RESET}"
echo -e "  LLM:  ${BOLD}Ollama ${OLLAMA_MODEL}${RESET}"
echo ""
echo -e "  ${BOLD}Dograh UI${RESET}       →  http://localhost:3010"
echo -e "  ${BOLD}Dograh API${RESET}      →  http://localhost:8000/api/v1/health"
echo -e "  ${BOLD}PocketTTS${RESET}       →  http://localhost:8100/health"
echo -e "  ${BOLD}MinIO console${RESET}   →  http://localhost:9001  (minioadmin / minioadmin)"
echo -e "  ${BOLD}Ollama${RESET}          →  http://localhost:11434"
echo ""
echo -e "  ${YELLOW}Useful commands:${RESET}"
echo -e "    All logs:          docker compose logs -f"
echo -e "    API logs:          docker compose logs -f api"
echo -e "    PocketTTS logs:    docker compose logs -f pocket-tts"
echo -e "    Stop:              ./deploy.sh --down"
echo -e "    Wipe all data:     ./deploy.sh --reset"
if ! $GPU_AVAILABLE; then
  echo ""
  echo -e "  ${YELLOW}CPU performance tips:${RESET}"
  echo -e "    Use a smaller model:  ./deploy.sh --pull-model llama3.2:1b"
  echo -e "    LLM response time:    ~8-25s depending on model + CPU speed"
fi
echo ""
