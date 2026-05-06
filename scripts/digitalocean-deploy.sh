#!/usr/bin/env bash
set -euo pipefail

if ! command -v doctl >/dev/null 2>&1; then
  echo "doctl is not installed. Install it first: brew install doctl"
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

doctl account get >/dev/null

: "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN in your shell before deploying.}"
: "${OPENROUTER_API_KEY:?Set OPENROUTER_API_KEY in your shell before deploying.}"

DROPLET_NAME="${DO_DROPLET_NAME:-riftline-gm}"
REGION="${DO_REGION:-sfo3}"
SIZE="${DO_SIZE:-s-1vcpu-512mb-10gb}"
IMAGE="${DO_IMAGE:-ubuntu-24-04-x64}"
REPO_URL="${RIFTLINE_REPO_URL:-https://github.com/felirami/riftline-gm.git}"
BRANCH="${RIFTLINE_BRANCH:-main}"
SSH_KEY_IDS="${DO_SSH_KEY_IDS:-}"

TEXT_MODEL="${OPENROUTER_TEXT_MODEL:-openai/gpt-5.4-mini}"
IMAGE_MODEL="${OPENROUTER_IMAGE_MODEL:-openai/gpt-5.4-image-2}"
FALLBACK_MODEL="${OPENROUTER_FALLBACK_MODEL:-qwen/qwen3.6-flash}"
MAX_PLAYERS="${MAX_PLAYERS:-6}"
DEFAULT_GAME_PROFILE="${DEFAULT_GAME_PROFILE:-cyberpunk_2077}"
DEFAULT_LANGUAGE="${DEFAULT_LANGUAGE:-es_latam_keep_terms}"
CONTENT_PRESET="${CONTENT_PRESET:-gritty_21_plus}"
DAILY_IMAGE_LIMIT="${DAILY_IMAGE_LIMIT:-5}"
IMAGE_COOLDOWN_SECONDS="${IMAGE_COOLDOWN_SECONDS:-60}"

cloud_init="$(mktemp)"
cleanup() {
  rm -f "$cloud_init"
}
trap cleanup EXIT

cat >"$cloud_init" <<YAML
#cloud-config
package_update: true
packages:
  - docker.io
  - docker-compose-plugin
  - git
  - sqlite3
runcmd:
  - systemctl enable --now docker
  - mkdir -p /opt/riftline-gm
  - if [ ! -d /opt/riftline-gm/.git ]; then git clone --branch "$BRANCH" --depth 1 "$REPO_URL" /opt/riftline-gm; else cd /opt/riftline-gm && git fetch origin "$BRANCH" && git reset --hard "origin/$BRANCH"; fi
  - |
    cat >/opt/riftline-gm/.env <<'ENVEOF'
    TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
    OPENROUTER_API_KEY=$OPENROUTER_API_KEY
    OPENROUTER_TEXT_MODEL=$TEXT_MODEL
    OPENROUTER_IMAGE_MODEL=$IMAGE_MODEL
    OPENROUTER_FALLBACK_MODEL=$FALLBACK_MODEL
    MAX_PLAYERS=$MAX_PLAYERS
    DEFAULT_GAME_PROFILE=$DEFAULT_GAME_PROFILE
    DEFAULT_LANGUAGE=$DEFAULT_LANGUAGE
    CONTENT_PRESET=$CONTENT_PRESET
    DAILY_IMAGE_LIMIT=$DAILY_IMAGE_LIMIT
    IMAGE_COOLDOWN_SECONDS=$IMAGE_COOLDOWN_SECONDS
    SQLITE_PATH=data/bot.sqlite
    ENVEOF
  - chmod 600 /opt/riftline-gm/.env
  - cd /opt/riftline-gm && docker compose up -d --build
YAML

args=(
  "$DROPLET_NAME"
  --region "$REGION"
  --size "$SIZE"
  --image "$IMAGE"
  --user-data-file "$cloud_init"
  --wait
)

if [[ -n "$SSH_KEY_IDS" ]]; then
  args+=(--ssh-keys "$SSH_KEY_IDS")
fi

echo "Creating DigitalOcean Droplet '$DROPLET_NAME' in $REGION using $SIZE..."
doctl compute droplet create "${args[@]}"

ip="$(doctl compute droplet get "$DROPLET_NAME" --format PublicIPv4 --no-header | tr -d '[:space:]')"
echo "Droplet created: $DROPLET_NAME"
echo "Public IPv4: $ip"
echo "Cloud-init is installing Docker and starting Riftline GM. Check later with:"
echo "  ssh root@$ip 'cloud-init status --wait && cd /opt/riftline-gm && docker compose ps && docker compose logs --tail=80'"
