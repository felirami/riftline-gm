from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Campaign:
    chat_id: int
    title: str
    active: bool
    game_profile: str
    language: str
    content_preset: str
    text_model: str | None
    image_model: str | None
    summary: str
    spotlight_user_id: int | None


@dataclass(frozen=True)
class Player:
    chat_id: int
    user_id: int
    username: str | None
    display_name: str
    experience_mode: str
    active: bool
    handle: str | None
    role: str | None
    style: str | None
    stats_json: str | None
    skills_json: str | None
    gear: str | None
    hp: int | None
    humanity: int | None
    cyberware: str | None
    notes: str | None


@dataclass(frozen=True)
class ImageRequest:
    id: int
    chat_id: int
    user_id: int
    original_prompt: str
    drafted_prompt: str
    status: str
    image_url: str | None


JSONDict = dict[str, Any]
