from __future__ import annotations

from riftline_gm.i18n import CONTENT_PRESETS, LANGUAGE_OPTIONS
from riftline_gm.models import Campaign, Player
from riftline_gm.profiles import profile_label, profile_or_default


def build_system_prompt(campaign: Campaign, players: list[Player]) -> str:
    language = LANGUAGE_OPTIONS.get(campaign.language, LANGUAGE_OPTIONS["es_latam_keep_terms"])
    content = CONTENT_PRESETS.get(campaign.content_preset, CONTENT_PRESETS["gritty_21_plus"])
    profile = profile_or_default(campaign.game_profile)
    player_lines = "\n".join(_player_line(player) for player in players) or "No active players yet."
    terms = ", ".join(profile.keep_terms)
    term_instruction = f"Keep these terms in English when keep-terms mode is enabled: {terms}." if terms else ""

    return f"""
You are the Telegram game master for a tabletop RPG campaign.
Use original wording. Do not quote or reproduce copyrighted rulebook text, tables, stat blocks, missions, or art.
You are not a complete official rules engine; make concise rulings and keep play moving.

Game profile:
{profile_label(profile.key, campaign.language)}
{profile.prompt}

Language:
{language["prompt"]}
{term_instruction}

Tone:
{content["prompt"]}
Avoid content that breaks provider or platform policy. When in doubt, imply, cut away, or summarize.

Table style:
- Make the campaign feel specific to the selected profile, not generic.
- Use plain Telegram text. Do not use Markdown markers such as **bold**, __underline__, backticks, or code fences.
- Favor danger, relationships, factions, debt, consequences, and hard choices.
- Spotlight turns during tense scenes and combat.
- Short, playable replies. End with a clear prompt, choice, or consequence.
- Use button-friendly options when useful: 2 to 4 concrete actions.
- For new players, explain the immediate rule or roll briefly. For experienced players, stay compact.
- Ask for rolls only when uncertainty and risk matter.

Active players:
{player_lines}
""".strip()


def build_chat_messages(
    *,
    campaign: Campaign,
    players: list[Player],
    recent_messages: list[object],
    user_display: str,
    user_message: str,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": build_system_prompt(campaign, players)}]
    if campaign.summary:
        messages.append({"role": "system", "content": f"Campaign summary so far:\n{campaign.summary}"})

    for row in recent_messages:
        role = row["role"]
        content = str(row["content"])
        if role == "gm":
            messages.append({"role": "assistant", "content": content})
        elif role == "user":
            messages.append({"role": "user", "content": content})

    messages.append({"role": "user", "content": f"{user_display}: {user_message}"})
    return messages


def build_summary_messages(campaign: Campaign, recent_messages: list[object]) -> list[dict[str, str]]:
    transcript = "\n".join(f"{row['role']}: {row['content']}" for row in recent_messages)
    return [
        {
            "role": "system",
            "content": (
                "Update a compact campaign memory for a tabletop RPG Telegram GM bot. "
                "Keep names, promises, factions, injuries, clues, debts, pending choices, and tone. "
                "Do not exceed 250 words."
            ),
        },
        {
            "role": "user",
            "content": f"Existing summary:\n{campaign.summary or '(empty)'}\n\nRecent transcript:\n{transcript}",
        },
    ]


def _player_line(player: Player) -> str:
    handle = player.handle or player.display_name
    details = []
    if player.role:
        details.append(f"role={player.role}")
    if player.hp is not None:
        details.append(f"hp={player.hp}")
    if player.humanity is not None:
        details.append(f"humanity={player.humanity}")
    if player.gear:
        details.append(f"gear={player.gear}")
    if player.cyberware:
        details.append(f"cyberware={player.cyberware}")
    if player.notes:
        details.append(f"notes={player.notes}")
    detail_text = ", ".join(details) if details else "light sheet incomplete"
    return f"- {handle} ({player.experience_mode}): {detail_text}"
