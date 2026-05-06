from __future__ import annotations

import json
import re
from typing import Any

from riftline_gm.i18n import CONTENT_PRESETS, LANGUAGE_OPTIONS
from riftline_gm.models import Campaign, CharacterDraft, Player
from riftline_gm.profiles import profile_or_default


MINIMUM_FIELDS = ("handle", "concept", "role")


def new_ai_draft_data(player: Player | None = None) -> dict[str, Any]:
    sheet: dict[str, Any] = {}
    if player:
        if player.handle:
            sheet["handle"] = player.handle
        if player.role:
            sheet["role"] = player.role
        if player.style:
            sheet["style"] = player.style
        if player.gear:
            sheet["gear"] = player.gear
        if player.cyberware:
            sheet["special"] = player.cyberware
        if player.hp is not None:
            sheet["durability"] = str(player.hp)
        if player.humanity is not None:
            sheet["strain"] = str(player.humanity)
        if player.notes:
            sheet["concept"] = player.notes
    return {"transcript": [], "sheet": sheet, "ready": False, "missing": list(missing_minimum_fields(sheet))}


def build_character_messages(
    *,
    campaign: Campaign,
    player: Player,
    draft: CharacterDraft,
    latest_user_text: str | None,
) -> list[dict[str, str]]:
    profile = profile_or_default(campaign.game_profile)
    language = LANGUAGE_OPTIONS.get(campaign.language, LANGUAGE_OPTIONS["es_latam_keep_terms"])
    content = CONTENT_PRESETS.get(campaign.content_preset, CONTENT_PRESETS["gritty_21_plus"])
    sheet_json = json.dumps(draft.data.get("sheet", {}), ensure_ascii=False, sort_keys=True)
    transcript = draft.data.get("transcript", [])
    transcript_text = "\n".join(f"{turn.get('role')}: {turn.get('content')}" for turn in transcript[-16:])
    latest = latest_user_text or "Start character creation now."
    keep_terms = ", ".join(profile.keep_terms) if profile.keep_terms else "none"

    system = f"""
You are Riftline GM's character-creation coach inside one player's Telegram forum topic.
Guide the player through making an original tabletop RPG character for the selected campaign profile.
Do not use fixed classes, official rulebook text, copyrighted stat blocks, or prewritten setting material.
Ask one short, useful question at a time. Adapt to the player's answers and taste.

Campaign profile:
{profile.label}
{profile.prompt}

Language:
{language["prompt"]}
Keep profile terms in English when appropriate: {keep_terms}.

Tone:
{content["prompt"]}

Player guidance mode: {player.experience_mode}.
For newbie players, explain choices in plain language while staying concise.
For experienced players, keep the flow compact and let them drive.

Output strict JSON only, no Markdown:
{{
  "message": "short character-topic reply to the player",
  "sheet": {{
    "handle": null,
    "concept": null,
    "role": null,
    "style": null,
    "strengths": null,
    "skills": null,
    "gear": null,
    "durability": null,
    "strain": null,
    "special": null,
    "bonds": null,
    "notes": null
  }},
  "ready": false,
  "missing": ["handle", "concept", "role"]
}}

Rules:
- Merge new information into the existing sheet.
- Keep unknown fields null or omit them.
- "ready" may be true only when handle/name, concept, and role/archetype/job are known.
- If the player says done, finalize, listo, or enough, summarize what is known and set ready true if the minimum fields are present.
- If the character is not ready, ask the single next best question.
""".strip()

    user = f"""
Player display name: {player.display_name}
Existing sheet JSON:
{sheet_json}

Recent character-topic transcript:
{transcript_text or "(empty)"}

Latest player message:
{latest}
""".strip()
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_character_ai_response(text: str, previous_sheet: dict[str, Any]) -> dict[str, Any]:
    payload = _extract_json(text)
    sheet = dict(previous_sheet)
    incoming_sheet = payload.get("sheet") if isinstance(payload, dict) else None
    if isinstance(incoming_sheet, dict):
        for key, value in incoming_sheet.items():
            if value is not None and str(value).strip():
                sheet[key] = str(value).strip()

    missing = payload.get("missing") if isinstance(payload, dict) else None
    if not isinstance(missing, list):
        missing = list(missing_minimum_fields(sheet))
    ready = bool(payload.get("ready")) if isinstance(payload, dict) else False
    current_missing = list(missing_minimum_fields(sheet))
    if current_missing:
        ready = False
        missing = current_missing

    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str) or not message.strip():
        message = text.strip() or "Tell me one more thing about who this character is."

    return {"message": message.strip(), "sheet": sheet, "ready": ready, "missing": missing}


def append_turn(data: dict[str, Any], *, role: str, content: str) -> dict[str, Any]:
    updated = dict(data)
    transcript = list(updated.get("transcript") or [])
    transcript.append({"role": role, "content": content})
    updated["transcript"] = transcript[-30:]
    return updated


def update_ai_draft_data(data: dict[str, Any], ai_payload: dict[str, Any]) -> dict[str, Any]:
    updated = append_turn(data, role="assistant", content=str(ai_payload["message"]))
    updated["sheet"] = ai_payload["sheet"]
    updated["ready"] = bool(ai_payload["ready"])
    updated["missing"] = list(ai_payload["missing"])
    return updated


def format_character_draft(draft: CharacterDraft, player: Player | None = None) -> str:
    sheet = draft.data.get("sheet", {})
    lines = ["Character draft"]
    for label, key in (
        ("Name", "handle"),
        ("Concept", "concept"),
        ("Role", "role"),
        ("Look", "style"),
        ("Strengths", "strengths"),
        ("Skills", "skills"),
        ("Gear", "gear"),
        ("Durability", "durability"),
        ("Strain", "strain"),
        ("Special", "special"),
        ("Bonds", "bonds"),
        ("Notes", "notes"),
    ):
        value = sheet.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    if len(lines) == 1:
        lines.append(f"- Player: {player.display_name if player else 'unknown'}")
    missing = draft.data.get("missing") or list(missing_minimum_fields(sheet))
    if missing:
        lines.append("Missing: " + ", ".join(str(item) for item in missing))
    if draft.data.get("ready"):
        lines.append("Ready to finalize.")
    return "\n".join(lines)


def draft_to_player_fields(draft: CharacterDraft) -> dict[str, Any]:
    sheet = draft.data.get("sheet", {})
    fields: dict[str, Any] = {}
    if sheet.get("handle"):
        fields["handle"] = sheet["handle"]
    if sheet.get("role"):
        fields["role"] = sheet["role"]
    if sheet.get("style"):
        fields["style"] = sheet["style"]
    if sheet.get("strengths"):
        fields["stats_json"] = {"notes": sheet["strengths"]}
    if sheet.get("skills"):
        fields["skills_json"] = {"notes": sheet["skills"]}
    if sheet.get("gear"):
        fields["gear"] = sheet["gear"]
    if sheet.get("durability"):
        number = _first_int(sheet["durability"])
        if number is not None:
            fields["hp"] = number
    if sheet.get("strain"):
        number = _first_int(sheet["strain"])
        if number is not None:
            fields["humanity"] = number
    if sheet.get("special"):
        fields["cyberware"] = sheet["special"]

    notes = []
    for key, label in (
        ("concept", "Concept"),
        ("bonds", "Bonds/debts"),
        ("durability", "Durability"),
        ("strain", "Strain"),
        ("notes", "Notes"),
    ):
        if sheet.get(key):
            notes.append(f"{label}: {sheet[key]}")
    if notes:
        fields["notes"] = " | ".join(notes)
    return fields


def missing_minimum_fields(sheet: dict[str, Any]) -> tuple[str, ...]:
    return tuple(field for field in MINIMUM_FIELDS if not str(sheet.get(field, "")).strip())


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if not match:
            return {}
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}


def _first_int(value: Any) -> int | None:
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else None
