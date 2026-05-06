# Riftline GM

Riftline GM is a tiny general-purpose Telegram game-master bot for tabletop RPG groups. It uses OpenRouter for text and image generation, SQLite for campaign memory, inline buttons for play, and Docker Compose for deployment to a small DigitalOcean Droplet.

The default starter profile is `cyberpunk_2077`, a 2077-era cyberpunk street-crew vibe. The repo is not limited to that: it also ships fantasy, space opera, and modern horror profiles, and new profiles are simple Python data entries.

Riftline GM does not include copyrighted rulebook text, stat tables, missions, setting excerpts, or art. It ships light dice helpers, original GM prompts, session memory, buttons, and player-authored notes.

## Features

- Telegram group play with `/session_start`, `/join`, `/gm`, `/roll`, `/image`, `/summary`, `/players`, `/settings`, `/profile`, `/model`, and `/sheet`.
- Hybrid buttons: persistent quick commands plus inline buttons for profile, language, tone, player mode, rolls, spotlight, and image approval.
- Built-in profiles: `cyberpunk_2077`, `generic_fantasy`, `space_opera`, and `modern_horror`.
- Spanish onboarding:
  - Español LatAm + English terms
  - Español España + English terms
  - Español LatAm full translation
  - Español España full translation
- Default mode: `cyberpunk_2077`, LatAm Spanish, and profile-specific terms like `netrunner`, `cyberpsychosis`, `corpo`, `fixer`, `edgerunner`, and `ripperdoc` kept in English.
- Adaptive player guidance: each player chooses new-player or experienced mode.
- AI-guided character creation in Telegram forum topics: one character topic per player, keeping the main chat clean.
- Light character sheets with `/sheet`, plus `/character` to create one from scratch.
- Admin-only session settings and image generation approval.
- SQLite persistence in `./data/bot.sqlite`.

## Models

Defaults:

- Text GM: `openai/gpt-5.4-mini`
- Image generation: `openai/gpt-5.4-image-2`
- Text fallback: `qwen/qwen3.6-flash`

OpenRouter image generation uses `/api/v1/chat/completions` with `modalities: ["image", "text"]`, following the official OpenRouter image docs.

## BotFather Setup

1. Create a bot with BotFather and put the token in `.env` as `TELEGRAM_BOT_TOKEN`.
2. Add the bot to your Telegram group.
3. For normal GM play, privacy mode can stay enabled if you only want commands, replies, and mentions.
4. For natural character-topic chat, disable privacy mode so the bot receives normal text inside each player's topic.
5. Enable Topics in the Telegram group and make the bot an admin with permission to manage topics if you want `/character` to create per-player character channels.
6. Make the bot a group admin if you want it to reliably check admin permissions.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill `.env`:

```bash
TELEGRAM_BOT_TOKEN=...
OPENROUTER_API_KEY=...
OPENROUTER_TEXT_MODEL=openai/gpt-5.4-mini
OPENROUTER_IMAGE_MODEL=openai/gpt-5.4-image-2
OPENROUTER_FALLBACK_MODEL=qwen/qwen3.6-flash
MAX_PLAYERS=6
DEFAULT_GAME_PROFILE=cyberpunk_2077
DEFAULT_LANGUAGE=es_latam_keep_terms
CONTENT_PRESET=gritty_21_plus
DAILY_IMAGE_LIMIT=5
IMAGE_COOLDOWN_SECONDS=60
SQLITE_PATH=data/bot.sqlite
```

Run:

```bash
riftline-gm
```

## Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

SQLite persists at:

```bash
./data/bot.sqlite
```

Backup:

```bash
sqlite3 ./data/bot.sqlite ".backup './data/bot-backup.sqlite'"
```

## DigitalOcean Droplet

Target size: DigitalOcean Basic Droplet, 512 MiB RAM, 1 vCPU, 10 GiB SSD.

Recommended server prep:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin sqlite3 git
sudo systemctl enable --now docker
```

Deploy:

```bash
git clone <your-repo-url> riftline-gm
cd riftline-gm
cp .env.example .env
nano .env
docker compose up -d --build
```

No inbound web port is needed because the bot uses Telegram long polling. SSH is enough.

Or deploy with the included DigitalOcean CLI helper after the repo is public:

```bash
brew install doctl
doctl auth init
export TELEGRAM_BOT_TOKEN=...
export OPENROUTER_API_KEY=...
export DO_SSH_KEY_IDS=<your-do-ssh-key-id>
./scripts/digitalocean-deploy.sh
```

Defaults: `sfo3`, `s-1vcpu-512mb-10gb`, `ubuntu-24-04-x64`, and `https://github.com/felirami/riftline-gm.git`.

## Playing

Start the table:

```text
/session_start
```

Choose a game profile:

```text
/profile
/profile cyberpunk_2077
```

Players join:

```text
/join
```

Create a character without filling the main chat:

```text
/character
```

Riftline GM creates a forum topic named like `PJ - Maria`. The player talks naturally in that topic and the AI guides the sheet from scratch without hardcoded classes or official rulebook data. Use the topic buttons for `Ask next`, `Show draft`, `Finalize`, and `Cancel`. If BotFather privacy mode is still enabled, players should reply to the bot or mention it in the topic; disabling privacy mode gives the smoothest flow.

Talk to the GM:

```text
/gm busco cámaras, rutas de escape y cualquier señal de un netrunner enemigo
```

Roll:

```text
/roll d10+7
```

Light sheet:

```text
/sheet handle: Hex; role: netrunner; style: chaqueta roja; hp: 35; humanity: 52; gear: deck, pistol; cyberware: neural link
```

Suggest an image:

```text
/image el grupo mira una torre corpo bajo lluvia ácida, neones violetas, drones arriba
```

Only a Telegram group admin can press `Generate image`.

Admin model override:

```text
/model text openai/gpt-5.4-mini
/model image openai/gpt-5.4-image-2
/model reset
```

## Content Presets

- `gritty_21_plus`: default adult tone with hard language, violence, drugs, body horror, exploitation, social horror, and harsh consequences.
- `vanilla`: dangerous noir tone with less gore and less extreme detail.
- `pg_13`: restrained action and drama.

Even in gritty mode, the bot prompt tells the model to avoid provider/platform-breaking content, real-world harm instructions, explicit sexual violence, and sexualized minors.

## Tests

```bash
pytest
python3 -m compileall riftline_gm
```

## References

- [Telegram Bot API](https://core.telegram.org/bots/api)
- [python-telegram-bot InlineKeyboardMarkup](https://docs.python-telegram-bot.org/en/v22.7/telegram.inlinekeyboardmarkup.html)
- [OpenRouter image generation](https://openrouter.ai/docs/guides/overview/multimodal/image-generation)
- [OpenRouter models API](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets)

## Trademark Note

Riftline GM is an independent open-source project. Cyberpunk 2077 and related marks belong to their owners. The included starter profile is original prompt guidance for private tabletop play and does not bundle protected rule or setting text.
