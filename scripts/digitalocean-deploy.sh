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
RECREATE="${DO_RECREATE:-0}"

TEXT_MODEL="${OPENROUTER_TEXT_MODEL:-openai/gpt-5.4-mini}"
IMAGE_MODEL="${OPENROUTER_IMAGE_MODEL:-openai/gpt-5.4-image-2}"
FALLBACK_MODEL="${OPENROUTER_FALLBACK_MODEL:-qwen/qwen3.6-flash}"
MAX_PLAYERS="${MAX_PLAYERS:-6}"
DEFAULT_GAME_PROFILE="${DEFAULT_GAME_PROFILE:-cyberpunk_2077}"
DEFAULT_LANGUAGE="${DEFAULT_LANGUAGE:-es_latam_keep_terms}"
CONTENT_PRESET="${CONTENT_PRESET:-gritty_21_plus}"
DAILY_IMAGE_LIMIT="${DAILY_IMAGE_LIMIT:-5}"
IMAGE_COOLDOWN_SECONDS="${IMAGE_COOLDOWN_SECONDS:-60}"

existing_ids="$(doctl compute droplet list --format ID,Name --no-header | awk -v name="$DROPLET_NAME" '$2 == name {print $1}')"
if [[ -n "$existing_ids" ]]; then
  if [[ "$RECREATE" == "1" ]]; then
    echo "Deleting existing Droplet(s) named '$DROPLET_NAME': $existing_ids"
    for id in $existing_ids; do
      doctl compute droplet delete "$id" --force
    done
  else
    echo "A Droplet named '$DROPLET_NAME' already exists: $existing_ids"
    echo "Set DO_RECREATE=1 to delete and recreate it."
    exit 1
  fi
fi

if [[ -z "$SSH_KEY_IDS" ]]; then
  key_count="$(doctl compute ssh-key list --format ID --no-header | wc -l | tr -d ' ')"
  if [[ "$key_count" == "1" ]]; then
    SSH_KEY_IDS="$(doctl compute ssh-key list --format ID --no-header | tr -d '[:space:]')"
  elif [[ "$key_count" == "0" ]]; then
    key_path="${DO_SSH_KEY_PATH:-$HOME/.ssh/riftline_gm_do}"
    if [[ ! -f "$key_path" ]]; then
      echo "No DigitalOcean SSH keys found. Creating $key_path and importing it."
      mkdir -p "$(dirname "$key_path")"
      ssh-keygen -t ed25519 -C "riftline-gm-do" -f "$key_path" -N ""
    fi
    SSH_KEY_IDS="$(
      doctl compute ssh-key import riftline-gm-do \
        --public-key-file "${key_path}.pub" \
        --format ID \
        --no-header
    )"
    SSH_KEY_IDS="$(echo "$SSH_KEY_IDS" | tr -d '[:space:]')"
  else
    echo "Multiple DigitalOcean SSH keys found. Set DO_SSH_KEY_IDS to the key ID(s) to attach."
    doctl compute ssh-key list --format ID,Name,Fingerprint
    exit 1
  fi
fi

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
  - git
  - sqlite3
runcmd:
  - systemctl enable --now docker
  - |
    arch="$(uname -m)"
    case "$arch" in
      x86_64) compose_arch=x86_64 ;;
      aarch64|arm64) compose_arch=aarch64 ;;
      *) echo "Unsupported architecture: $arch"; exit 1 ;;
    esac
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -fsSL "https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-${compose_arch}" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    docker compose version
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
