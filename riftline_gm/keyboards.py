from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove

from riftline_gm.i18n import CONTENT_PRESETS, content_label, language_label
from riftline_gm.models import Campaign, CharacterDraft, ImageRequest
from riftline_gm.profiles import GAME_PROFILES, profile_or_default


def quick_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            ["/help", "/join"],
            ["/gm", "/roll d10"],
            ["/character", "/sheet"],
            ["/players", "/summary"],
            ["/image", "/settings"],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("LatAm + términos en inglés", callback_data="lang:es_latam_keep_terms"),
                InlineKeyboardButton("España + términos en inglés", callback_data="lang:es_es_keep_terms"),
            ],
            [
                InlineKeyboardButton("LatAm traducción completa", callback_data="lang:es_latam_full"),
                InlineKeyboardButton("España traducción completa", callback_data="lang:es_es_full"),
            ],
        ]
    )


def content_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(option["label"], callback_data=f"content:{key}")] for key, option in CONTENT_PRESETS.items()]
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(profile.label, callback_data=f"profile:{key}")] for key, profile in GAME_PROFILES.items()]
    )


def settings_keyboard(campaign: Campaign) -> InlineKeyboardMarkup:
    profile = profile_or_default(campaign.game_profile)
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Perfil: {profile.short_name}", callback_data="menu:profile")],
            [InlineKeyboardButton(f"Idioma: {language_label(campaign.language)}", callback_data="menu:language")],
            [InlineKeyboardButton(f"Tono: {content_label(campaign.content_preset)}", callback_data="menu:content")],
            [InlineKeyboardButton("Pausar sesión", callback_data="admin:pause")],
        ]
    )


def lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Unirme al crew", callback_data="menu:join"),
                InlineKeyboardButton("Crear personaje", callback_data="menu:character"),
            ],
            [
                InlineKeyboardButton("Cómo jugar", callback_data="menu:help"),
                InlineKeyboardButton("Jugadores", callback_data="menu:players"),
            ],
            [
                InlineKeyboardButton("Resumen", callback_data="menu:summary"),
                InlineKeyboardButton("Ajustes", callback_data="menu:settings"),
            ],
        ]
    )


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Unirme al crew", callback_data="menu:join"),
                InlineKeyboardButton("Crear personaje", callback_data="menu:character"),
            ],
            [
                InlineKeyboardButton("Tirar d10", callback_data="roll:d10"),
                InlineKeyboardButton("Jugadores", callback_data="menu:players"),
            ],
            [
                InlineKeyboardButton("Resumen", callback_data="menu:summary"),
                InlineKeyboardButton("Ajustes", callback_data="menu:settings"),
            ],
        ]
    )


def experience_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Soy nuevo", callback_data=f"xp:{user_id}:newbie"),
                InlineKeyboardButton("Tengo experiencia", callback_data=f"xp:{user_id}:experienced"),
            ],
            [
                InlineKeyboardButton("Crear personaje", callback_data=f"char:start:{user_id}"),
                InlineKeyboardButton("Ayuda de ficha", callback_data=f"sheet_help:{user_id}"),
            ],
        ]
    )


def gm_keyboard(campaign: Campaign) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("Tirar d10", callback_data="roll:d10"),
            InlineKeyboardButton("Jugadores", callback_data="menu:players"),
            InlineKeyboardButton("Resumen", callback_data="menu:summary"),
        ],
        [
            InlineKeyboardButton("Tomar turno", callback_data="spotlight:claim"),
            InlineKeyboardButton("Ceder turno", callback_data="spotlight:clear"),
            InlineKeyboardButton("Pausar", callback_data="admin:pause"),
        ],
    ]
    if campaign.spotlight_user_id:
        rows.append([InlineKeyboardButton("Turno activo", callback_data="noop")])
    return InlineKeyboardMarkup(rows)


def image_approval_keyboard(image_request: ImageRequest) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Generar imagen", callback_data=f"image:approve:{image_request.id}"),
                InlineKeyboardButton("Cancelar", callback_data=f"image:cancel:{image_request.id}"),
            ]
        ]
    )


def character_topic_keyboard(draft: CharacterDraft) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Siguiente", callback_data=f"char:continue:{draft.user_id}"),
                InlineKeyboardButton("Ver borrador", callback_data=f"char:summary:{draft.user_id}"),
            ],
            [
                InlineKeyboardButton("Finalizar", callback_data=f"char:finish:{draft.user_id}"),
                InlineKeyboardButton("Cancelar", callback_data=f"char:cancel:{draft.user_id}"),
            ],
        ]
    )
