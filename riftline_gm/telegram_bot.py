from __future__ import annotations

import base64
import logging
from io import BytesIO

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from riftline_gm.config import Config
from riftline_gm.db import Store, cooldown_remaining, start_of_utc_day
from riftline_gm.dice import parse_and_roll
from riftline_gm.i18n import CONTENT_PRESETS, LANGUAGE_OPTIONS, content_label, language_label
from riftline_gm.keyboards import (
    content_keyboard,
    experience_keyboard,
    gm_keyboard,
    image_approval_keyboard,
    language_keyboard,
    profile_keyboard,
    quick_keyboard,
    remove_keyboard,
    settings_keyboard,
)
from riftline_gm.models import Campaign, Player
from riftline_gm.openrouter import OpenRouterClient
from riftline_gm.prompts import build_chat_messages, build_summary_messages
from riftline_gm.profiles import GAME_PROFILES, profile_or_default

logger = logging.getLogger(__name__)


def build_application(config: Config, store: Store, openrouter: OpenRouterClient) -> Application:
    async def _shutdown(_: Application) -> None:
        await openrouter.close()
        store.close()

    application = ApplicationBuilder().token(config.telegram_bot_token).post_shutdown(_shutdown).build()
    application.bot_data["config"] = config
    application.bot_data["store"] = store
    application.bot_data["openrouter"] = openrouter

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("session_start", session_start))
    application.add_handler(CommandHandler("session_pause", session_pause))
    application.add_handler(CommandHandler("join", join))
    application.add_handler(CommandHandler("leave", leave))
    application.add_handler(CommandHandler("gm", gm))
    application.add_handler(CommandHandler("roll", roll))
    application.add_handler(CommandHandler("image", image))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CommandHandler("players", players))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("model", model_settings))
    application.add_handler(CommandHandler("profile", profile_settings))
    application.add_handler(CommandHandler("sheet", sheet))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    return application


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Soy Riftline GM: un bot para dirigir mesas RPG en Telegram. Usa /session_start para abrir campaña, "
        "/profile para elegir mundo, /join para entrar y /gm para hablar con la mesa.",
        reply_markup=quick_keyboard(),
    )


async def session_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    config, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    campaign = store.update_campaign(campaign.chat_id, active=1)
    await update.effective_message.reply_text(
        "Sesión abierta. Te dejo los botones rápidos abajo para jugar sin memorizar comandos.",
        reply_markup=quick_keyboard(),
    )
    await update.effective_message.reply_text(
        "Primero elige perfil de juego. Cyberpunk viene como punto de partida, pero Riftline GM puede correr otras mesas.",
        reply_markup=profile_keyboard(),
    )
    await update.effective_message.reply_text(
        "Después elige idioma y estilo de traducción para esta campaña.",
        reply_markup=language_keyboard(),
    )
    logger.info("Session started for chat %s with max_players=%s", campaign.chat_id, config.max_players)


async def session_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    store.update_campaign(campaign.chat_id, active=0, spotlight_user_id=None)
    await update.effective_message.reply_text("Sesión pausada. La mesa baja el volumen.", reply_markup=remove_keyboard())


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    user = update.effective_user
    existing = store.maybe_player(campaign.chat_id, user.id)
    if (not existing or not existing.active) and store.count_active_players(campaign.chat_id) >= config.max_players:
        await update.effective_message.reply_text(f"La mesa ya tiene el máximo configurado: {config.max_players} players.")
        return
    player = store.upsert_player(
        chat_id=campaign.chat_id,
        user_id=user.id,
        username=user.username,
        display_name=user.full_name or user.username or str(user.id),
    )
    await update.effective_message.reply_text(
        f"{player.display_name} entra al crew. Elige cómo quieres que el GM te guíe.",
        reply_markup=experience_keyboard(user.id),
    )


async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    store.deactivate_player(campaign.chat_id, update.effective_user.id)
    await update.effective_message.reply_text("Sales de la sesión activa. Tu ficha ligera queda guardada.")


async def gm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        await update.effective_message.reply_text("Usa `/gm intento colarme por la puerta trasera`.", parse_mode="Markdown")
        return
    await process_gm_text(update, context, text)


async def roll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    expression = " ".join(context.args).strip() or "d10"
    await send_roll(update, context, expression)


async def image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.effective_message.reply_text("Usa `/image escena tensa del grupo en el perfil actual`.")
        return
    await create_image_request(update, context, prompt)


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    text = campaign.summary or "Aún no hay resumen. Dame unas escenas y lo compacto."
    await update.effective_message.reply_text(text)


async def players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    await update.effective_message.reply_text(format_players(store.list_active_players(campaign.chat_id)))


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config, _, _ = deps(context)
    campaign = ensure_campaign(update, context)
    await update.effective_message.reply_text(
        format_settings(campaign, config),
        reply_markup=settings_keyboard(campaign),
    )


async def model_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    config, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    args = context.args
    if not args:
        await update.effective_message.reply_text(
            "Modelos actuales:\n"
            f"Text: {campaign.text_model or config.openrouter_text_model}\n"
            f"Image: {campaign.image_model or config.openrouter_image_model}\n\n"
            "Usa `/model text openai/gpt-5.4-mini`, `/model image openai/gpt-5.4-image-2`, o `/model reset`.",
            parse_mode="Markdown",
        )
        return
    if args[0].lower() == "reset":
        campaign = store.update_campaign(campaign.chat_id, text_model=None, image_model=None)
        await update.effective_message.reply_text(format_settings(campaign, config))
        return
    if len(args) >= 2 and args[0].lower() in {"text", "image"}:
        field = "text_model" if args[0].lower() == "text" else "image_model"
        campaign = store.update_campaign(campaign.chat_id, **{field: args[1]})
        await update.effective_message.reply_text(format_settings(campaign, config))
        return
    campaign = store.update_campaign(campaign.chat_id, text_model=args[0])
    await update.effective_message.reply_text(format_settings(campaign, config))


async def profile_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    args = context.args
    if not args:
        await update.effective_message.reply_text(
            f"Perfil actual: {profile_or_default(campaign.game_profile).label}\nElige uno:",
            reply_markup=profile_keyboard(),
        )
        return
    profile_key = args[0].strip()
    if profile_key not in GAME_PROFILES:
        await update.effective_message.reply_text(
            "Perfil desconocido. Opciones: " + ", ".join(GAME_PROFILES.keys())
        )
        return
    store.update_campaign(campaign.chat_id, game_profile=profile_key)
    await update.effective_message.reply_text(f"Perfil elegido: {GAME_PROFILES[profile_key].label}")


async def sheet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    player = store.maybe_player(campaign.chat_id, update.effective_user.id)
    if not player or not player.active:
        await update.effective_message.reply_text("Primero entra con /join.")
        return

    payload = " ".join(context.args).strip()
    if not payload:
        await update.effective_message.reply_text(sheet_help_text())
        return
    fields = parse_sheet_payload(payload)
    if not fields:
        await update.effective_message.reply_text("No entendí la ficha. Usa pares como `handle: Hex; role: netrunner; hp: 35`.")
        return
    updated = store.update_player_sheet(campaign.chat_id, update.effective_user.id, **fields)
    await update.effective_message.reply_text(f"Ficha actualizada:\n{format_player(updated)}")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("pong")


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = (message.text or "").strip()
    if not text:
        return

    chat = update.effective_chat
    bot = context.bot
    username = (bot.username or "").lower()
    is_private = chat.type == "private"
    is_reply_to_bot = bool(message.reply_to_message and message.reply_to_message.from_user and message.reply_to_message.from_user.id == bot.id)
    is_mention = bool(username and f"@{username}" in text.lower())
    if not (is_private or is_reply_to_bot or is_mention):
        return

    if username:
        text = text.replace(f"@{bot.username}", "").strip()
    await process_gm_text(update, context, text)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    config, store, openrouter = deps(context)
    campaign = ensure_campaign(update, context)

    try:
        if data == "noop":
            await query.answer()
            return
        if data.startswith("lang:"):
            await query.answer()
            if not await require_admin(update, context, query_only=True):
                return
            language = data.split(":", 1)[1]
            if language not in LANGUAGE_OPTIONS:
                await query.message.reply_text("Idioma desconocido.")
                return
            store.update_campaign(campaign.chat_id, language=language)
            await query.message.reply_text(
                f"Idioma elegido: {language_label(language)}.\nAhora elige el tono de la mesa.",
                reply_markup=content_keyboard(),
            )
            return
        if data.startswith("profile:"):
            await query.answer()
            if not await require_admin(update, context, query_only=True):
                return
            profile_key = data.split(":", 1)[1]
            if profile_key not in GAME_PROFILES:
                await query.message.reply_text("Perfil desconocido.")
                return
            store.update_campaign(campaign.chat_id, game_profile=profile_key)
            await query.message.reply_text(f"Perfil elegido: {GAME_PROFILES[profile_key].label}")
            return
        if data == "menu:profile":
            await query.answer()
            if await require_admin(update, context, query_only=True):
                await query.message.reply_text("Elige perfil de juego.", reply_markup=profile_keyboard())
            return
        if data.startswith("content:"):
            await query.answer()
            if not await require_admin(update, context, query_only=True):
                return
            content_preset = data.split(":", 1)[1]
            if content_preset not in CONTENT_PRESETS:
                await query.message.reply_text("Preset desconocido.")
                return
            store.update_campaign(campaign.chat_id, content_preset=content_preset)
            await query.message.reply_text(f"Tono elegido: {content_label(content_preset)}. El crew puede entrar con /join.")
            return
        if data == "menu:language":
            await query.answer()
            if await require_admin(update, context, query_only=True):
                await query.message.reply_text("Elige idioma.", reply_markup=language_keyboard())
            return
        if data == "menu:content":
            await query.answer()
            if await require_admin(update, context, query_only=True):
                await query.message.reply_text("Elige tono.", reply_markup=content_keyboard())
            return
        if data == "menu:players":
            await query.answer()
            await query.message.reply_text(format_players(store.list_active_players(campaign.chat_id)))
            return
        if data == "menu:summary":
            await query.answer()
            await query.message.reply_text(campaign.summary or "Aún no hay resumen.")
            return
        if data == "admin:pause":
            await query.answer()
            if await require_admin(update, context, query_only=True):
                store.update_campaign(campaign.chat_id, active=0, spotlight_user_id=None)
                await query.message.reply_text("Sesión pausada.", reply_markup=remove_keyboard())
            return
        if data.startswith("xp:"):
            await query.answer()
            _, user_id_raw, mode = data.split(":", 2)
            target_user_id = int(user_id_raw)
            if query.from_user.id != target_user_id:
                await query.answer("Ese botón es personal.", show_alert=True)
                return
            store.update_player_experience(campaign.chat_id, target_user_id, mode)
            await query.message.reply_text(
                f"Listo. Modo: {'nuevo player' if mode == 'newbie' else 'experienced'}.\n{sheet_help_text()}"
            )
            return
        if data.startswith("sheet_help:"):
            await query.answer()
            target_user_id = int(data.split(":", 1)[1])
            if query.from_user.id != target_user_id:
                await query.answer("Ese botón es personal.", show_alert=True)
                return
            await query.message.reply_text(sheet_help_text())
            return
        if data == "roll:d10":
            await query.answer()
            await query.message.reply_text(parse_and_roll("d10").format(), parse_mode="Markdown")
            return
        if data == "spotlight:claim":
            await query.answer()
            player = store.maybe_player(campaign.chat_id, query.from_user.id)
            if not player or not player.active:
                await query.answer("Primero entra con /join.", show_alert=True)
                return
            store.update_campaign(campaign.chat_id, spotlight_user_id=query.from_user.id)
            await query.message.reply_text(f"Spotlight para {player.handle or player.display_name}.")
            return
        if data == "spotlight:clear":
            await query.answer()
            if campaign.spotlight_user_id in {None, query.from_user.id} or await is_admin(update, context):
                store.update_campaign(campaign.chat_id, spotlight_user_id=None)
                await query.message.reply_text("Spotlight liberado.")
            else:
                await query.answer("Solo el spotlight actual o un admin puede pasarlo.", show_alert=True)
            return
        if data.startswith("image:approve:"):
            await query.answer()
            if not await require_admin(update, context, query_only=True):
                return
            image_id = int(data.rsplit(":", 1)[1])
            await approve_image(query.message, context, image_id, config, store, openrouter)
            return
        if data.startswith("image:cancel:"):
            await query.answer()
            image_id = int(data.rsplit(":", 1)[1])
            image_request = store.get_image_request(image_id)
            if query.from_user.id != image_request.user_id and not await is_admin(update, context):
                await query.answer("Solo quien la pidió o un admin puede cancelarla.", show_alert=True)
                return
            store.update_image_request(image_id, status="cancelled")
            await query.message.reply_text("Imagen cancelada.")
            return

        await query.answer("No reconozco ese botón.", show_alert=True)
    except Exception:
        logger.exception("Callback failed: %s", data)
        await query.message.reply_text("Algo falló procesando ese botón. Revisa logs.")


async def process_gm_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    config, store, openrouter = deps(context)
    campaign = ensure_campaign(update, context)
    if not campaign.active:
        await update.effective_message.reply_text("La sesión está pausada. Un admin puede usar /session_start.")
        return
    player = store.maybe_player(campaign.chat_id, update.effective_user.id)
    if not player or not player.active:
        await update.effective_message.reply_text("Primero entra al crew con /join.")
        return

    await context.bot.send_chat_action(chat_id=campaign.chat_id, action=ChatAction.TYPING)
    display = player.handle or player.display_name
    recent = store.recent_messages(campaign.chat_id, limit=18)
    players = store.list_active_players(campaign.chat_id)
    messages = build_chat_messages(
        campaign=campaign,
        players=players,
        recent_messages=recent,
        user_display=display,
        user_message=text,
    )

    store.add_message(campaign.chat_id, role="user", content=f"{display}: {text}", user_id=player.user_id)
    result = await openrouter.chat(messages, model=campaign.text_model or config.openrouter_text_model)
    store.add_cost_log(
        chat_id=campaign.chat_id,
        model=result.model,
        kind="text",
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_cost=result.total_cost,
    )
    store.add_message(campaign.chat_id, role="gm", content=result.text)
    await maybe_refresh_summary(campaign.chat_id, context)
    updated_campaign = store.get_campaign(campaign.chat_id)
    await update.effective_message.reply_text(result.text, reply_markup=gm_keyboard(updated_campaign))


async def send_roll(update: Update, context: ContextTypes.DEFAULT_TYPE, expression: str) -> None:
    try:
        result = parse_and_roll(expression)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(result.format(), parse_mode="Markdown")


async def create_image_request(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> None:
    config, store, openrouter = deps(context)
    campaign = ensure_campaign(update, context)
    if not campaign.active:
        await update.effective_message.reply_text("La sesión está pausada.")
        return
    player = store.maybe_player(campaign.chat_id, update.effective_user.id)
    if not player or not player.active:
        await update.effective_message.reply_text("Primero entra al crew con /join.")
        return

    daily_count = store.count_generated_images_since(campaign.chat_id, start_of_utc_day())
    if daily_count >= config.daily_image_limit:
        await update.effective_message.reply_text("Límite diario de imágenes alcanzado para este chat.")
        return
    remaining = cooldown_remaining(store.latest_image_created_at(campaign.chat_id), config.image_cooldown_seconds)
    if remaining:
        await update.effective_message.reply_text(f"Espera {remaining}s antes de pedir otra imagen.")
        return

    await context.bot.send_chat_action(chat_id=campaign.chat_id, action=ChatAction.TYPING)
    language_instruction = LANGUAGE_OPTIONS.get(campaign.language, LANGUAGE_OPTIONS["es_latam_keep_terms"])["prompt"]
    profile = profile_or_default(campaign.game_profile)
    draft = await openrouter.draft_image_prompt(
        language_instruction=language_instruction,
        profile_instruction=profile.image_style,
        original_prompt=prompt,
        model=campaign.text_model or config.openrouter_text_model,
    )
    if draft.model != "local-fallback":
        store.add_cost_log(
            chat_id=campaign.chat_id,
            model=draft.model,
            kind="image_prompt",
            prompt_tokens=draft.prompt_tokens,
            completion_tokens=draft.completion_tokens,
            total_cost=draft.total_cost,
        )
    image_request = store.create_image_request(
        chat_id=campaign.chat_id,
        user_id=update.effective_user.id,
        original_prompt=prompt,
        drafted_prompt=draft.text,
    )
    await update.effective_message.reply_text(
        "Prompt preparado. Solo admins pueden gastar la generación:\n\n"
        f"{image_request.drafted_prompt}",
        reply_markup=image_approval_keyboard(image_request),
    )


async def approve_image(message, context: ContextTypes.DEFAULT_TYPE, image_id: int, config: Config, store: Store, openrouter: OpenRouterClient) -> None:
    image_request = store.get_image_request(image_id)
    if image_request.status != "pending":
        await message.reply_text(f"Esta imagen ya está en estado `{image_request.status}`.")
        return
    daily_count = store.count_generated_images_since(image_request.chat_id, start_of_utc_day())
    if daily_count >= config.daily_image_limit:
        await message.reply_text("Límite diario de imágenes alcanzado para este chat.")
        return
    store.update_image_request(image_id, status="generating")
    await context.bot.send_chat_action(chat_id=image_request.chat_id, action=ChatAction.UPLOAD_PHOTO)
    try:
        campaign = store.get_campaign(image_request.chat_id)
        result = await openrouter.image(image_request.drafted_prompt, model=campaign.image_model or config.openrouter_image_model)
        store.add_cost_log(
            chat_id=image_request.chat_id,
            model=result.model,
            kind="image",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_cost=result.total_cost,
        )
        store.update_image_request(image_id, status="generated", image_url=result.image_url)
        await send_photo(context, image_request.chat_id, result.image_url, caption=result.text or "Escena generada.")
    except Exception:
        store.update_image_request(image_id, status="failed")
        logger.exception("Image generation failed for request %s", image_id)
        await message.reply_text("Falló la generación de imagen. No cierro la escena; prueba más tarde.")


async def send_photo(context: ContextTypes.DEFAULT_TYPE, chat_id: int, image_url: str, *, caption: str) -> None:
    if image_url.startswith("data:"):
        _, encoded = image_url.split(",", 1)
        image_bytes = BytesIO(base64.b64decode(encoded))
        image_bytes.name = "riftline_gm-scene.png"
        await context.bot.send_photo(chat_id=chat_id, photo=image_bytes, caption=caption[:1024])
        return
    await context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=caption[:1024])


async def maybe_refresh_summary(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, store, openrouter = deps(context)
    count = store.message_count(chat_id)
    if count < 16 or count % 8 != 0:
        return
    campaign = store.get_campaign(chat_id)
    recent = store.recent_messages(chat_id, limit=24)
    try:
        result = await openrouter.chat(build_summary_messages(campaign, recent), max_tokens=350, temperature=0.2)
        store.update_campaign(chat_id, summary=result.text)
        store.add_cost_log(
            chat_id=chat_id,
            model=result.model,
            kind="summary",
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_cost=result.total_cost,
        )
    except Exception:
        logger.exception("Summary refresh failed for chat %s", chat_id)


def ensure_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Campaign:
    config, store, _ = deps(context)
    chat = update.effective_chat
    title = getattr(chat, "title", None) or getattr(chat, "full_name", None) or f"chat-{chat.id}"
    return store.get_or_create_campaign(
        chat.id,
        title=title,
        default_game_profile=config.default_game_profile,
        default_language=config.default_language,
        content_preset=config.content_preset,
    )


def deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Config, Store, OpenRouterClient]:
    return (
        context.application.bot_data["config"],
        context.application.bot_data["store"],
        context.application.bot_data["openrouter"],
    )


async def require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, *, query_only: bool = False) -> bool:
    if await is_admin(update, context):
        return True
    message = update.callback_query.message if update.callback_query else update.effective_message
    if update.callback_query:
        await update.callback_query.answer("Solo admins pueden hacer eso.", show_alert=True)
    if not query_only and message:
        await message.reply_text("Solo admins del grupo pueden hacer eso.")
    return False


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    if chat.type == "private":
        return True
    member = await context.bot.get_chat_member(chat.id, user.id)
    return member.status in {"administrator", "creator", "owner"}


def format_settings(campaign: Campaign, config: Config) -> str:
    active = "active" if campaign.active else "paused"
    profile = profile_or_default(campaign.game_profile)
    return (
        f"Session: {active}\n"
        f"Profile: {profile.label}\n"
        f"Language: {language_label(campaign.language)}\n"
        f"Tone: {content_label(campaign.content_preset)}\n"
        f"Text model: {campaign.text_model or config.openrouter_text_model}\n"
        f"Image model: {campaign.image_model or config.openrouter_image_model}"
    )


def format_players(players: list[Player]) -> str:
    if not players:
        return "No hay players activos. Usa /join."
    return "Crew activo:\n" + "\n".join(f"- {format_player(player)}" for player in players)


def format_player(player: Player) -> str:
    name = player.handle or player.display_name
    bits = [name, player.experience_mode]
    if player.role:
        bits.append(player.role)
    if player.hp is not None:
        bits.append(f"HP {player.hp}")
    if player.humanity is not None:
        bits.append(f"Humanity {player.humanity}")
    if player.gear:
        bits.append(f"Gear: {player.gear}")
    if player.cyberware:
        bits.append(f"Cyberware: {player.cyberware}")
    return " | ".join(bits)


def sheet_help_text() -> str:
    return (
        "Ficha ligera: usa `/sheet handle: Hex; role: netrunner; style: chaqueta roja; "
        "hp: 35; humanity: 52; gear: pistol, deck; cyberware: neural link; notes: le debe plata a un fixer`. "
        "En otros perfiles, usa esos campos para clase, arquetipo, equipo, magia, heridas o notas relevantes."
    )


def parse_sheet_payload(payload: str) -> dict[str, object]:
    aliases = {
        "handle": "handle",
        "name": "handle",
        "role": "role",
        "style": "style",
        "gear": "gear",
        "hp": "hp",
        "humanity": "humanity",
        "cyberware": "cyberware",
        "notes": "notes",
        "stats": "stats_json",
        "skills": "skills_json",
    }
    fields: dict[str, object] = {}
    for chunk in payload.split(";"):
        if ":" in chunk:
            key, value = chunk.split(":", 1)
        elif "=" in chunk:
            key, value = chunk.split("=", 1)
        else:
            continue
        target = aliases.get(key.strip().lower())
        if not target:
            continue
        cleaned = value.strip()
        if target in {"hp", "humanity"}:
            try:
                fields[target] = int(cleaned)
            except ValueError:
                continue
        elif target in {"stats_json", "skills_json"}:
            fields[target] = {"notes": cleaned}
        else:
            fields[target] = cleaned
    return fields
