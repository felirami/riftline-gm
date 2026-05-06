from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GameProfile:
    key: str
    label: str
    short_name: str
    prompt: str
    image_style: str
    keep_terms: tuple[str, ...] = ()


GAME_PROFILES: dict[str, GameProfile] = {
    "cyberpunk_2077": GameProfile(
        key="cyberpunk_2077",
        label="Cyberpunk 2077-inspired street crew",
        short_name="Cyberpunk",
        prompt=(
            "Run a 2077-era cyberpunk campaign inspired by street-level crews, fixers, corpos, netrunners, "
            "black-market cyberware, urban decay, neon excess, and hard consequences. Use original material; "
            "do not reproduce copyrighted missions, rulebook text, stat blocks, maps, or art."
        ),
        image_style=(
            "2077-era cyberpunk city scene, neon noir, rain-slick streets, chrome, megacorp pressure, "
            "tabletop RPG scene art"
        ),
        keep_terms=(
            "netrunner",
            "cyberpsychosis",
            "corpo",
            "fixer",
            "edgerunner",
            "braindance",
            "ripperdoc",
            "choom",
            "flatline",
            "solo",
            "nomad",
            "tech",
            "medtech",
            "exec",
        ),
    ),
    "generic_fantasy": GameProfile(
        key="generic_fantasy",
        label="Fantasy adventuring party",
        short_name="Fantasy",
        prompt=(
            "Run a fantasy tabletop RPG campaign about dangerous expeditions, local politics, ancient magic, "
            "monsters, bargains, ruins, travel, and character-driven choices. Keep rules lightweight and original."
        ),
        image_style="fantasy tabletop RPG scene art, dramatic lighting, adventuring party, painterly detail",
        keep_terms=("dungeon", "spell", "cleric", "rogue", "paladin", "warlock"),
    ),
    "space_opera": GameProfile(
        key="space_opera",
        label="Space opera crew",
        short_name="Space Opera",
        prompt=(
            "Run a sci-fi tabletop RPG campaign about crews, ships, factions, strange worlds, smugglers, "
            "corporate powers, alien mysteries, and high-stakes missions. Keep technology plausible enough for play."
        ),
        image_style="space opera tabletop RPG scene art, starship crew, alien worlds, cinematic sci-fi lighting",
        keep_terms=("jump drive", "airlock", "station", "crew", "captain", "smuggler"),
    ),
    "modern_horror": GameProfile(
        key="modern_horror",
        label="Modern horror investigation",
        short_name="Horror",
        prompt=(
            "Run a modern horror tabletop RPG campaign about investigation, dread, secrets, fragile trust, "
            "dangerous rituals, and escalating consequences. Preserve mystery and avoid overexplaining the unknown."
        ),
        image_style="modern horror tabletop RPG scene art, unsettling realism, investigation, shadows, cinematic tension",
        keep_terms=("ritual", "entity", "cult", "case", "witness"),
    ),
}

DEFAULT_PROFILE = "cyberpunk_2077"


def profile_or_default(profile_key: str | None) -> GameProfile:
    return GAME_PROFILES.get(profile_key or DEFAULT_PROFILE, GAME_PROFILES[DEFAULT_PROFILE])

