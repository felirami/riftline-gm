from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from riftline_gm.profiles import DEFAULT_PROFILE


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    openrouter_api_key: str
    openrouter_text_model: str = "openai/gpt-5.4-mini"
    openrouter_image_model: str = "openai/gpt-5.4-image-2"
    openrouter_fallback_model: str = "qwen/qwen3.6-flash"
    max_players: int = 6
    default_game_profile: str = DEFAULT_PROFILE
    default_language: str = "es_latam_keep_terms"
    content_preset: str = "gritty_21_plus"
    daily_image_limit: int = 5
    image_cooldown_seconds: int = 60
    sqlite_path: Path = Path("data/bot.sqlite")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    app_title: str = "Riftline GM"


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def load_config(*, validate_runtime: bool = True) -> Config:
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

    config = Config(
        telegram_bot_token=telegram_bot_token,
        openrouter_api_key=openrouter_api_key,
        openrouter_text_model=os.getenv("OPENROUTER_TEXT_MODEL", "openai/gpt-5.4-mini"),
        openrouter_image_model=os.getenv("OPENROUTER_IMAGE_MODEL", "openai/gpt-5.4-image-2"),
        openrouter_fallback_model=os.getenv("OPENROUTER_FALLBACK_MODEL", "qwen/qwen3.6-flash"),
        max_players=_int_env("MAX_PLAYERS", 6),
        default_game_profile=os.getenv("DEFAULT_GAME_PROFILE", DEFAULT_PROFILE),
        default_language=os.getenv("DEFAULT_LANGUAGE", "es_latam_keep_terms"),
        content_preset=os.getenv("CONTENT_PRESET", "gritty_21_plus"),
        daily_image_limit=_int_env("DAILY_IMAGE_LIMIT", 5),
        image_cooldown_seconds=_int_env("IMAGE_COOLDOWN_SECONDS", 60),
        sqlite_path=Path(os.getenv("SQLITE_PATH", "data/bot.sqlite")),
        openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        app_title=os.getenv("APP_TITLE", "Riftline GM"),
    )

    if validate_runtime:
        missing = []
        if not config.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not config.openrouter_api_key:
            missing.append("OPENROUTER_API_KEY")
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")

    if config.max_players < 1:
        raise ValueError("MAX_PLAYERS must be at least 1")
    if config.daily_image_limit < 0:
        raise ValueError("DAILY_IMAGE_LIMIT must be 0 or greater")

    return config
