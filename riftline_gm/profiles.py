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

PROFILE_LOCALIZATION: dict[str, dict[str, dict[str, str]]] = {
    "es": {
        "cyberpunk_2077": {
            "label": "Crew callejero Cyberpunk 2077",
            "short_name": "Cyberpunk",
            "image_style": (
                "escena cyberpunk de 2077 para tabletop RPG, neon noir, calles mojadas, cromo, "
                "presión megacorp, arte de escena cinematográfico"
            ),
        },
        "generic_fantasy": {
            "label": "Grupo de aventura fantástica",
            "short_name": "Fantasía",
            "image_style": "escena de fantasía para tabletop RPG, iluminación dramática, party aventurera, detalle pictórico",
        },
        "space_opera": {
            "label": "Crew de space opera",
            "short_name": "Space opera",
            "image_style": "escena de space opera para tabletop RPG, crew de nave, mundos alienígenas, iluminación sci-fi cinematográfica",
        },
        "modern_horror": {
            "label": "Investigación de horror moderno",
            "short_name": "Horror moderno",
            "image_style": "escena de horror moderno para tabletop RPG, realismo inquietante, investigación, sombras, tensión cinematográfica",
        },
    }
}


def profile_or_default(profile_key: str | None) -> GameProfile:
    return GAME_PROFILES.get(profile_key or DEFAULT_PROFILE, GAME_PROFILES[DEFAULT_PROFILE])


def profile_label(profile_key: str | None, language: str | None = None) -> str:
    profile = profile_or_default(profile_key)
    return _localized(profile.key, "label", language) or profile.label


def profile_short_name(profile_key: str | None, language: str | None = None) -> str:
    profile = profile_or_default(profile_key)
    return _localized(profile.key, "short_name", language) or profile.short_name


def profile_image_style(profile_key: str | None, language: str | None = None) -> str:
    profile = profile_or_default(profile_key)
    return _localized(profile.key, "image_style", language) or profile.image_style


def _localized(profile_key: str, field: str, language: str | None) -> str | None:
    if not language or not language.startswith("es_"):
        return None
    return PROFILE_LOCALIZATION.get("es", {}).get(profile_key, {}).get(field)
