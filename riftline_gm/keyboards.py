from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove

from riftline_gm.i18n import CONTENT_PRESETS, LANGUAGE_OPTIONS
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
                InlineKeyboardButton("LatAm + English terms", callback_data="lang:es_latam_keep_terms"),
                InlineKeyboardButton("España + English terms", callback_data="lang:es_es_keep_terms"),
            ],
            [
                InlineKeyboardButton("LatAm full translation", callback_data="lang:es_latam_full"),
                InlineKeyboardButton("España full translation", callback_data="lang:es_es_full"),
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
            [InlineKeyboardButton(f"Profile: {profile.short_name}", callback_data="menu:profile")],
            [InlineKeyboardButton(f"Language: {LANGUAGE_OPTIONS[campaign.language]['label']}", callback_data="menu:language")],
            [InlineKeyboardButton(f"Tone: {CONTENT_PRESETS[campaign.content_preset]['label']}", callback_data="menu:content")],
            [InlineKeyboardButton("Pause session", callback_data="admin:pause")],
        ]
    )


def lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Join crew", callback_data="menu:join"),
                InlineKeyboardButton("Create character", callback_data="menu:character"),
            ],
            [
                InlineKeyboardButton("How to play", callback_data="menu:help"),
                InlineKeyboardButton("Players", callback_data="menu:players"),
            ],
            [
                InlineKeyboardButton("Summary", callback_data="menu:summary"),
                InlineKeyboardButton("Settings", callback_data="menu:settings"),
            ],
        ]
    )


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Join crew", callback_data="menu:join"),
                InlineKeyboardButton("Create character", callback_data="menu:character"),
            ],
            [
                InlineKeyboardButton("Roll d10", callback_data="roll:d10"),
                InlineKeyboardButton("Players", callback_data="menu:players"),
            ],
            [
                InlineKeyboardButton("Summary", callback_data="menu:summary"),
                InlineKeyboardButton("Settings", callback_data="menu:settings"),
            ],
        ]
    )


def experience_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("New player", callback_data=f"xp:{user_id}:newbie"),
                InlineKeyboardButton("Experienced", callback_data=f"xp:{user_id}:experienced"),
            ],
            [
                InlineKeyboardButton("Create character", callback_data=f"char:start:{user_id}"),
                InlineKeyboardButton("Sheet help", callback_data=f"sheet_help:{user_id}"),
            ],
        ]
    )


def gm_keyboard(campaign: Campaign) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("Roll d10", callback_data="roll:d10"),
            InlineKeyboardButton("Players", callback_data="menu:players"),
            InlineKeyboardButton("Summary", callback_data="menu:summary"),
        ],
        [
            InlineKeyboardButton("Claim spotlight", callback_data="spotlight:claim"),
            InlineKeyboardButton("Pass spotlight", callback_data="spotlight:clear"),
            InlineKeyboardButton("Pause", callback_data="admin:pause"),
        ],
    ]
    if campaign.spotlight_user_id:
        rows.append([InlineKeyboardButton("Spotlight active", callback_data="noop")])
    return InlineKeyboardMarkup(rows)


def image_approval_keyboard(image_request: ImageRequest) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Generate image", callback_data=f"image:approve:{image_request.id}"),
                InlineKeyboardButton("Cancel", callback_data=f"image:cancel:{image_request.id}"),
            ]
        ]
    )


def character_topic_keyboard(draft: CharacterDraft) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Ask next", callback_data=f"char:continue:{draft.user_id}"),
                InlineKeyboardButton("Show draft", callback_data=f"char:summary:{draft.user_id}"),
            ],
            [
                InlineKeyboardButton("Finalize", callback_data=f"char:finish:{draft.user_id}"),
                InlineKeyboardButton("Cancel", callback_data=f"char:cancel:{draft.user_id}"),
            ],
        ]
    )
