from __future__ import annotations

import base64
import logging
from io import BytesIO

from telegram import BotCommand, BotCommandScopeChat, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from riftline_gm.characters import (
    FIELD_LABELS_ES,
    append_turn,
    build_character_messages,
    draft_to_player_fields,
    format_character_draft,
    missing_minimum_fields,
    new_ai_draft_data,
    parse_character_ai_response,
    update_ai_draft_data,
)
from riftline_gm.config import Config
from riftline_gm.db import Store, cooldown_remaining, start_of_utc_day
from riftline_gm.dice import parse_and_roll
from riftline_gm.i18n import CONTENT_PRESETS, LANGUAGE_OPTIONS, content_label, language_label
from riftline_gm.keyboards import (
    content_keyboard,
    character_topic_keyboard,
    experience_keyboard,
    gm_keyboard,
    help_keyboard,
    image_approval_keyboard,
    language_keyboard,
    lobby_keyboard,
    profile_keyboard,
    quick_keyboard,
    remove_keyboard,
    settings_keyboard,
)
from riftline_gm.models import Campaign, CharacterDraft, Player
from riftline_gm.openrouter import OpenRouterClient
from riftline_gm.prompts import build_chat_messages, build_summary_messages
from riftline_gm.profiles import GAME_PROFILES, profile_or_default

logger = logging.getLogger(__name__)

GROUP_TOPIC_TEMPLATES: tuple[tuple[str, str, str], ...] = (
    (
        "start",
        "Inicio",
        "Bienvenido. Este es el lobby de la mesa: únete, crea tu personaje, revisa comandos y deja preguntas de organización aquí.",
    ),
    (
        "table",
        "Chat de mesa",
        "Usa este topic para hablar fuera de personaje, coordinar horarios, expectativas y temas de la mesa.",
    ),
    (
        "play",
        "Juego en personaje",
        "Usa este topic para escenas en vivo cuando el grupo quiera tener la acción principal en un solo lugar. Menciona al bot o usa /gm para hablar con el GM.",
    ),
    (
        "images",
        "Escenas e imágenes",
        "Usa este topic para pedir imágenes, guardar referencias visuales e inspiración de escena. Generar imágenes sigue necesitando aprobación admin.",
    ),
    (
        "rolls",
        "Tiradas y reglas",
        "Usa este topic para tiradas, rulings rápidos, preguntas de reglas y notas mecánicas.",
    ),
)

GROUP_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("help", "Ver guía de la mesa"),
    BotCommand("join", "Unirte al crew activo"),
    BotCommand("character", "Crear tu personaje en un topic"),
    BotCommand("gm", "Hablar con el GM"),
    BotCommand("roll", "Tirar dados como d10+7"),
    BotCommand("image", "Sugerir una imagen para aprobación admin"),
    BotCommand("players", "Ver jugadores activos"),
    BotCommand("summary", "Ver resumen de campaña"),
    BotCommand("settings", "Ver ajustes de campaña"),
    BotCommand("setup_group", "Admin: preparar la UX del grupo"),
)


def build_application(config: Config, store: Store, openrouter: OpenRouterClient) -> Application:
    async def _shutdown(_: Application) -> None:
        await openrouter.close()
        store.close()

    application = ApplicationBuilder().token(config.telegram_bot_token).post_shutdown(_shutdown).build()
    application.bot_data["config"] = config
    application.bot_data["store"] = store
    application.bot_data["openrouter"] = openrouter

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setup_group", setup_group))
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
    application.add_handler(CommandHandler("character", character))
    application.add_handler(CommandHandler("sheet", sheet))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CallbackQueryHandler(callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    return application


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Soy Riftline GM: un bot para dirigir mesas RPG en Telegram. Usa /setup_group para preparar la mesa, "
        "/session_start para abrir campaña, /join para entrar y /help si alguien se pierde.",
        reply_markup=lobby_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    campaign = ensure_campaign(update, context)
    await update.effective_message.reply_text(
        format_help_text(campaign),
        reply_markup=help_keyboard(),
    )
    await update.effective_message.reply_text("También te dejo los botones rápidos abajo.", reply_markup=quick_keyboard())


async def setup_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    chat = update.effective_chat
    if chat.type == "private":
        await update.effective_message.reply_text("Esto se corre dentro del grupo, no por DM.")
        return

    report: list[str] = ["Preparación de UX del grupo"]
    await add_bot_permission_report(context, campaign.chat_id, report)
    await install_group_commands(context, campaign.chat_id, report)
    await update_group_description(context, campaign.chat_id, report)

    ready_topics: list[str] = []
    start_thread_id: int | None = None
    if chat.type == "supergroup" and bool(getattr(chat, "is_forum", False)):
        for topic_key, name, intro in GROUP_TOPIC_TEMPLATES:
            thread_id = await ensure_group_topic(context, store, campaign.chat_id, topic_key, name, intro, report)
            if thread_id is not None:
                ready_topics.append(name)
                if topic_key == "start":
                    start_thread_id = thread_id
    else:
        report.append("Topics: todavía no están disponibles. Activa Topics en la configuración del grupo y corre /setup_group otra vez.")

    target_thread_id = start_thread_id
    try:
        guide = await context.bot.send_message(
            chat_id=campaign.chat_id,
            message_thread_id=target_thread_id,
            text=format_lobby_text(campaign),
            reply_markup=lobby_keyboard(),
        )
    except TelegramError:
        logger.info("Could not send setup guide to start topic in chat %s", campaign.chat_id, exc_info=True)
        report.append("Guía de inicio: falló en el topic, la mandé a General.")
        guide = await context.bot.send_message(
            chat_id=campaign.chat_id,
            text=format_lobby_text(campaign),
            reply_markup=lobby_keyboard(),
        )
    await pin_message_if_possible(context, campaign.chat_id, guide.message_id, report)

    await update.effective_message.reply_text(
        format_setup_report(report, ready_topics),
        reply_markup=lobby_keyboard(),
    )


async def session_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    config, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    campaign = store.update_campaign(campaign.chat_id, active=1)
    await update.effective_message.reply_text(
        "Sesión abierta. Te dejo botones rápidos abajo para jugar sin memorizar comandos.",
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
    await join_player(update, context, update.effective_message)


async def join_player(update: Update, context: ContextTypes.DEFAULT_TYPE, message) -> Player | None:
    config, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    user = update.effective_user
    existing = store.maybe_player(campaign.chat_id, user.id)
    if (not existing or not existing.active) and store.count_active_players(campaign.chat_id) >= config.max_players:
        await message.reply_text(f"La mesa ya tiene el máximo configurado: {config.max_players} jugadores.")
        return None
    player = store.upsert_player(
        chat_id=campaign.chat_id,
        user_id=user.id,
        username=user.username,
        display_name=user.full_name or user.username or str(user.id),
    )
    await message.reply_text(
        f"{player.display_name} entra al crew. Elige cómo quieres que el GM te guíe.",
        reply_markup=experience_keyboard(user.id),
    )
    return player


async def character(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(
            "La creación de personaje vive en topics del grupo. Vuelve al grupo, activa Topics si hace falta y usa /character ahí."
        )
        return

    player = await ensure_player_for_character(update, context)
    if not player:
        return

    action = context.args[0].lower() if context.args else "home"
    if action == "cancel":
        draft = store.maybe_character_draft(campaign.chat_id, player.user_id)
        if not draft:
            await update.effective_message.reply_text("No tienes borrador de personaje activo.")
            return
        store.cancel_character_draft(campaign.chat_id, player.user_id)
        if draft.topic_thread_id:
            await send_character_topic_message(context, draft, "Borrador de personaje cancelado.")
        else:
            await update.effective_message.reply_text("Borrador de personaje cancelado.")
        return

    restart = action in {"new", "start", "restart"}
    draft = await get_or_create_character_draft(context, campaign, player, restart=restart)
    if not draft:
        return
    if action in {"finish", "finalize"}:
        draft = await ensure_character_topic(update, context, campaign, player, draft)
        if not draft:
            return
        await finalize_character(update.effective_message, context, draft)
        return

    draft = await ensure_character_topic(update, context, campaign, player, draft)
    if not draft:
        return

    thread_id = get_message_thread_id(update.effective_message)
    if thread_id != draft.topic_thread_id:
        await update.effective_message.reply_text(
            f"Listo: usa el topic {draft.topic_name} para crear tu personaje sin llenar el chat principal.",
        )

    if restart or not draft.data.get("transcript"):
        await run_character_ai_turn(context, draft, latest_user_text=None)
    else:
        await send_character_topic_message(
            context,
            draft,
            f"{format_character_draft(draft, player)}\n\nEscribe en este topic para seguir creando el personaje.",
            reply_markup=character_topic_keyboard(draft),
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
    _, store, _ = deps(context)

    if chat.type != "private":
        campaign = ensure_campaign(update, context)
        thread_id = get_message_thread_id(message)
        if thread_id is not None:
            draft = store.maybe_character_draft_by_topic(campaign.chat_id, thread_id)
            if draft:
                if update.effective_user.id == draft.user_id:
                    await run_character_ai_turn(context, draft, latest_user_text=text)
                elif await should_answer_wrong_topic_user(update, context):
                    player = store.maybe_player(draft.chat_id, draft.user_id)
                    owner = player.display_name if player else "otro jugador"
                    await message.reply_text(f"Este topic de personaje es de {owner}. Usa /character para abrir el tuyo.")
                return

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
        if data == "menu:help":
            await query.answer()
            await query.message.reply_text(format_help_text(campaign), reply_markup=help_keyboard())
            return
        if data == "menu:join":
            await query.answer()
            await join_player(update, context, query.message)
            return
        if data == "menu:character":
            await query.answer()
            player = await ensure_player_for_character(update, context)
            if not player:
                return
            draft = await get_or_create_character_draft(context, campaign, player, restart=False)
            if not draft:
                return
            draft = await ensure_character_topic(update, context, campaign, player, draft)
            if not draft:
                return
            await query.message.reply_text(f"Listo: abre el topic {draft.topic_name} para crear tu personaje.")
            await run_character_ai_turn(context, draft, latest_user_text=None)
            return
        if data == "menu:settings":
            await query.answer()
            await query.message.reply_text(format_settings(campaign, config), reply_markup=settings_keyboard(campaign))
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
                f"Listo. Modo: {'jugador nuevo' if mode == 'newbie' else 'jugador con experiencia'}.\n{sheet_help_text()}"
            )
            return
        if data.startswith("char:"):
            await handle_character_callback(update, context, data)
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
            await query.message.reply_text(f"Turno para {player.handle or player.display_name}.")
            return
        if data == "spotlight:clear":
            await query.answer()
            if campaign.spotlight_user_id in {None, query.from_user.id} or await is_admin(update, context):
                store.update_campaign(campaign.chat_id, spotlight_user_id=None)
                await query.message.reply_text("Turno liberado.")
            else:
                await query.answer("Solo quien tiene el turno o un admin puede pasarlo.", show_alert=True)
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
        await query.message.reply_text("Algo falló procesando ese botón. Revisa los logs.")


async def handle_character_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    _, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    parts = data.split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    target_user_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else query.from_user.id
    if query.from_user.id != target_user_id:
        await query.answer("Ese botón es personal.", show_alert=True)
        return

    player = store.maybe_player(campaign.chat_id, target_user_id)
    if not player or not player.active:
        await query.answer("Primero entra con /join.", show_alert=True)
        return

    draft = store.maybe_character_draft(campaign.chat_id, target_user_id)
    if not draft or action == "start":
        draft = await get_or_create_character_draft(context, campaign, player, restart=action == "start")
        if not draft:
            return

    if action in {"start", "continue"}:
        draft = await ensure_character_topic(update, context, campaign, player, draft)
        if not draft:
            return
        if get_message_thread_id(query.message) != draft.topic_thread_id:
            await query.message.reply_text(f"Listo: abrí el topic {draft.topic_name} para tu personaje.")
        await run_character_ai_turn(context, draft, latest_user_text=None)
        return
    if action in {"home", "summary"}:
        draft = await ensure_character_topic(update, context, campaign, player, draft)
        if not draft:
            return
        await send_character_topic_message(
            context,
            draft,
            format_character_draft(draft, player),
            reply_markup=character_topic_keyboard(draft),
        )
        return
    if action == "finish":
        await finalize_character(query.message, context, draft)
        return
    if action == "cancel":
        store.cancel_character_draft(campaign.chat_id, target_user_id)
        if draft.topic_thread_id:
            await send_character_topic_message(context, draft, "Borrador de personaje cancelado.")
        else:
            await query.message.reply_text("Borrador de personaje cancelado.")
        return

    await query.answer("No reconozco ese botón.", show_alert=True)


async def finalize_character(message, context: ContextTypes.DEFAULT_TYPE, draft: CharacterDraft) -> None:
    _, store, _ = deps(context)
    missing = missing_minimum_fields(draft.data.get("sheet", {}))
    if missing:
        missing_text = ", ".join(FIELD_LABELS_ES.get(str(item), str(item)) for item in missing)
        await send_character_topic_message(
            context,
            draft,
            "Todavía faltan estos detalles base antes de cerrar: "
            + missing_text
            + ". Responde en este topic y el GM te guía.",
            reply_markup=character_topic_keyboard(draft),
        )
        return

    fields = draft_to_player_fields(draft)
    if not fields:
        await send_character_topic_message(context, draft, "El borrador está vacío. Usa /character start para empezar.")
        return
    player = store.update_player_sheet(draft.chat_id, draft.user_id, **fields)
    store.cancel_character_draft(draft.chat_id, draft.user_id)
    await send_character_topic_message(
        context,
        draft,
        "Personaje finalizado y guardado en tu ficha ligera.\n\n"
        f"{format_player(player)}\n\nUsa /sheet cuando quieras ajustar detalles manualmente."
    )


async def get_or_create_character_draft(
    context: ContextTypes.DEFAULT_TYPE,
    campaign: Campaign,
    player: Player,
    *,
    restart: bool = False,
) -> CharacterDraft | None:
    _, store, _ = deps(context)
    draft = store.maybe_character_draft(campaign.chat_id, player.user_id)
    if draft and not restart:
        return draft

    return store.upsert_character_draft(
        chat_id=campaign.chat_id,
        user_id=player.user_id,
        game_profile=campaign.game_profile,
        current_field="ai",
        data=new_ai_draft_data(player),
        active=True,
    )


async def ensure_character_topic(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campaign: Campaign,
    player: Player,
    draft: CharacterDraft,
) -> CharacterDraft | None:
    if draft.topic_thread_id:
        return draft

    message = update.callback_query.message if update.callback_query else update.effective_message
    chat = update.effective_chat
    if chat.type != "supergroup":
        await message.reply_text(
            "Para usar subchannels de personaje, el grupo tiene que ser un supergroup de Telegram con Topics activados."
        )
        return None
    if getattr(chat, "is_forum", None) is False:
        await message.reply_text(
            "Este grupo todavía no tiene Topics activados. Actívalos en la configuración del grupo y dame permiso para gestionar topics."
        )
        return None

    _, store, _ = deps(context)
    topic_name = character_topic_name(player)
    try:
        topic = await context.bot.create_forum_topic(chat_id=campaign.chat_id, name=topic_name)
    except TelegramError:
        logger.exception("Failed to create character topic for chat=%s user=%s", campaign.chat_id, player.user_id)
        await message.reply_text(
            "No pude crear el topic de personaje. Revisa que el grupo tenga Topics activos y que el bot sea admin con permiso para gestionar topics."
        )
        return None

    draft = store.update_character_draft(
        campaign.chat_id,
        player.user_id,
        current_field="ai",
        topic_thread_id=topic.message_thread_id,
        topic_name=topic.name or topic_name,
        data=draft.data,
    )
    await send_character_topic_message(
        context,
        draft,
        f"{player.display_name}, este es tu topic de personaje. Escribe aquí y el GM te ayuda a crear la ficha sin llenar el chat principal.",
        reply_markup=character_topic_keyboard(draft),
    )
    return draft


async def run_character_ai_turn(
    context: ContextTypes.DEFAULT_TYPE,
    draft: CharacterDraft,
    *,
    latest_user_text: str | None,
) -> None:
    config, store, openrouter = deps(context)
    campaign = store.get_campaign(draft.chat_id)
    player = store.maybe_player(draft.chat_id, draft.user_id)
    if not player or not player.active:
        await send_character_topic_message(context, draft, "Primero entra al crew con /join.")
        return

    data = dict(draft.data or new_ai_draft_data(player))
    if latest_user_text:
        data = append_turn(data, role="user", content=latest_user_text)
        draft = store.update_character_draft(draft.chat_id, draft.user_id, current_field="ai", data=data)

    try:
        await context.bot.send_chat_action(
            chat_id=draft.chat_id,
            action=ChatAction.TYPING,
            message_thread_id=draft.topic_thread_id,
        )
        messages = build_character_messages(
            campaign=campaign,
            player=player,
            draft=draft,
            latest_user_text=latest_user_text,
        )
        result = await openrouter.chat(
            messages,
            model=campaign.text_model or config.openrouter_text_model,
            max_tokens=800,
            temperature=0.7,
        )
    except Exception:
        logger.exception("Character AI turn failed for chat=%s user=%s", draft.chat_id, draft.user_id)
        await send_character_topic_message(
            context,
            draft,
            "Se me cortó la señal con el modelo. Tu draft sigue guardado; prueba otra vez en un momento.",
            reply_markup=character_topic_keyboard(draft),
        )
        return

    ai_payload = parse_character_ai_response(result.text, draft.data.get("sheet", {}))
    updated_data = update_ai_draft_data(data, ai_payload)
    draft = store.update_character_draft(draft.chat_id, draft.user_id, current_field="ai", data=updated_data)
    store.add_cost_log(
        chat_id=draft.chat_id,
        model=result.model,
        kind="character",
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_cost=result.total_cost,
    )

    reply = ai_payload["message"]
    if ai_payload["ready"]:
        reply = f"{reply}\n\n{format_character_draft(draft, player)}"
    await send_character_topic_message(context, draft, reply, reply_markup=character_topic_keyboard(draft))


async def send_character_topic_message(
    context: ContextTypes.DEFAULT_TYPE,
    draft: CharacterDraft,
    text: str,
    *,
    reply_markup=None,
) -> None:
    await context.bot.send_message(
        chat_id=draft.chat_id,
        message_thread_id=draft.topic_thread_id,
        text=text,
        reply_markup=reply_markup,
    )


async def should_answer_wrong_topic_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    bot = context.bot
    username = (bot.username or "").lower()
    is_reply_to_bot = bool(
        message.reply_to_message
        and message.reply_to_message.from_user
        and message.reply_to_message.from_user.id == bot.id
    )
    is_mention = bool(username and f"@{username}" in (message.text or "").lower())
    return is_reply_to_bot or is_mention


def get_message_thread_id(message) -> int | None:
    return getattr(message, "message_thread_id", None)


def character_topic_name(player: Player) -> str:
    name = (player.handle or player.display_name or str(player.user_id)).replace("\n", " ").strip()
    if not name:
        name = str(player.user_id)
    return f"PJ - {name}"[:120]


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

    await context.bot.send_chat_action(
        chat_id=campaign.chat_id,
        action=ChatAction.TYPING,
        message_thread_id=get_message_thread_id(update.effective_message),
    )
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


async def install_group_commands(context: ContextTypes.DEFAULT_TYPE, chat_id: int, report: list[str]) -> None:
    try:
        await context.bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeChat(chat_id))
        report.append("Comandos: menú instalado para este grupo.")
    except TelegramError:
        logger.exception("Failed to install group commands for chat %s", chat_id)
        report.append("Comandos: falló la instalación. El bot igual funciona con comandos escritos.")


async def add_bot_permission_report(context: ContextTypes.DEFAULT_TYPE, chat_id: int, report: list[str]) -> None:
    try:
        member = await context.bot.get_chat_member(chat_id, context.bot.id)
    except TelegramError:
        logger.info("Could not read bot permissions in chat %s", chat_id, exc_info=True)
        report.append("Permisos del bot: no pude inspeccionarlos.")
        return

    is_bot_admin = member.status in {"administrator", "creator", "owner"}
    report.append(f"Bot admin: {'sí' if is_bot_admin else 'no'}")
    if is_bot_admin:
        manage_topics = bool(getattr(member, "can_manage_topics", False))
        pin_messages = bool(getattr(member, "can_pin_messages", False))
        change_info = bool(getattr(member, "can_change_info", False))
        report.append(f"Gestionar topics: {'sí' if manage_topics else 'no'}")
        report.append(f"Fijar mensajes: {'sí' if pin_messages else 'no'}")
        report.append(f"Cambiar info del grupo: {'sí' if change_info else 'no'}")


async def update_group_description(context: ContextTypes.DEFAULT_TYPE, chat_id: int, report: list[str]) -> None:
    description = "Mesa Riftline GM. Usa /help para jugar, /join para entrar, /character para crear personaje y /gm para hablar con el GM."
    try:
        await context.bot.set_chat_description(chat_id=chat_id, description=description)
        report.append("Descripción: actualizada.")
    except TelegramError:
        logger.info("Could not update chat description for chat %s", chat_id, exc_info=True)
        report.append("Descripción: omitida. Da permiso de Cambiar info si quieres que el bot la maneje.")


async def ensure_group_topic(
    context: ContextTypes.DEFAULT_TYPE,
    store: Store,
    chat_id: int,
    topic_key: str,
    name: str,
    intro: str,
    report: list[str],
) -> int | None:
    existing = store.get_group_topic(chat_id, topic_key)
    if existing:
        existing_name = str(existing["name"])
        if existing_name != name:
            try:
                await context.bot.edit_forum_topic(chat_id=chat_id, message_thread_id=int(existing["message_thread_id"]), name=name)
                store.upsert_group_topic(chat_id, topic_key=topic_key, message_thread_id=int(existing["message_thread_id"]), name=name)
                existing_name = name
            except TelegramError:
                logger.info("Could not rename group topic %s in chat %s", topic_key, chat_id, exc_info=True)
        report.append(f"Topic: reutilizado {existing_name}.")
        return int(existing["message_thread_id"])

    try:
        topic = await context.bot.create_forum_topic(chat_id=chat_id, name=name)
    except TelegramError:
        logger.exception("Failed to create group topic %s in chat %s", topic_key, chat_id)
        report.append(f"Topic: no pude crear {name}. Revisa el permiso Gestionar topics.")
        return None

    store.upsert_group_topic(
        chat_id,
        topic_key=topic_key,
        message_thread_id=topic.message_thread_id,
        name=topic.name or name,
    )
    report.append(f"Topic: creado {topic.name or name}.")
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=topic.message_thread_id,
            text=intro,
            reply_markup=lobby_keyboard() if topic_key == "start" else None,
        )
    except TelegramError:
        logger.info("Could not send intro to topic %s in chat %s", topic_key, chat_id, exc_info=True)
        report.append(f"Intro de topic: omitida para {topic.name or name}.")
    return topic.message_thread_id


async def pin_message_if_possible(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    report: list[str],
) -> None:
    try:
        await context.bot.pin_chat_message(chat_id=chat_id, message_id=message_id, disable_notification=True)
        report.append("Guía fijada: listo.")
    except TelegramError:
        logger.info("Could not pin setup guide in chat %s", chat_id, exc_info=True)
        report.append("Guía fijada: omitida. Da permiso de Fijar mensajes si quieres que el bot la fije.")


def format_lobby_text(campaign: Campaign) -> str:
    profile = profile_or_default(campaign.game_profile)
    return (
        "Guía de la mesa Riftline GM\n\n"
        f"Juego: {profile.label}\n"
        f"Idioma: {language_label(campaign.language)}\n"
        f"Tono: {content_label(campaign.content_preset)}\n\n"
        "Si eres nuevo:\n"
        "1. Toca Unirme al crew.\n"
        "2. Toca Crear personaje. El bot abre tu propio topic de personaje.\n"
        "3. Usa /gm o responde al GM cuando quieras actuar en una escena.\n"
        "4. Usa /roll d10+7 para tiradas rápidas.\n\n"
        "Admins: /settings, /profile, /model, /session_start y /setup_group."
    )


def format_help_text(campaign: Campaign) -> str:
    profile = profile_or_default(campaign.game_profile)
    return (
        "Cómo jugar con Riftline GM\n\n"
        f"Juego actual: {profile.label}\n"
        f"Idioma: {language_label(campaign.language)}\n\n"
        "Básicos para jugadores:\n"
        "/join - entrar al crew\n"
        "/character - crear tu personaje en tu propio topic\n"
        "/gm <acción> - decirle al GM qué haces\n"
        "/roll d10+7 - tirar dados\n"
        "/sheet - ver cómo ajustar tu ficha ligera\n"
        "/players - ver el crew\n"
        "/summary - ponerte al día con la historia\n\n"
        "Tip: en topics de personaje, escribe natural. Si el bot no responde, respóndele a su mensaje o menciónalo."
    )


def format_setup_report(report: list[str], topics: list[str]) -> str:
    topic_text = ", ".join(topics) if topics else "ninguno"
    return "Setup listo.\n\n" + "\n".join(f"- {line}" for line in report) + f"\n- Topics listos: {topic_text}"


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


async def ensure_player_for_character(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Player | None:
    config, store, _ = deps(context)
    campaign = ensure_campaign(update, context)
    user = update.effective_user
    player = store.maybe_player(campaign.chat_id, user.id)
    if player and player.active:
        return player

    if store.count_active_players(campaign.chat_id) >= config.max_players:
        await update.effective_message.reply_text(f"La mesa ya tiene el máximo configurado: {config.max_players} jugadores.")
        return None

    return store.upsert_player(
        chat_id=campaign.chat_id,
        user_id=user.id,
        username=user.username,
        display_name=user.full_name or user.username or str(user.id),
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
    active = "activa" if campaign.active else "pausada"
    profile = profile_or_default(campaign.game_profile)
    return (
        f"Sesión: {active}\n"
        f"Perfil: {profile.label}\n"
        f"Idioma: {language_label(campaign.language)}\n"
        f"Tono: {content_label(campaign.content_preset)}\n"
        f"Modelo de texto: {campaign.text_model or config.openrouter_text_model}\n"
        f"Modelo de imagen: {campaign.image_model or config.openrouter_image_model}"
    )


def format_players(players: list[Player]) -> str:
    if not players:
        return "No hay jugadores activos. Usa /join."
    return "Crew activo:\n" + "\n".join(f"- {format_player(player)}" for player in players)


def format_player(player: Player) -> str:
    name = player.handle or player.display_name
    mode = "nuevo" if player.experience_mode == "newbie" else "con experiencia"
    bits = [name, mode]
    if player.role:
        bits.append(player.role)
    if player.hp is not None:
        bits.append(f"HP {player.hp}")
    if player.humanity is not None:
        bits.append(f"Humanidad {player.humanity}")
    if player.gear:
        bits.append(f"Equipo: {player.gear}")
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
