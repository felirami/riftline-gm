from riftline_gm.config import Config
from riftline_gm.db import Store
from riftline_gm.i18n import LANGUAGE_OPTIONS
from riftline_gm.keyboards import help_keyboard, language_keyboard, lobby_keyboard, profile_keyboard
from riftline_gm.openrouter import OpenRouterClient
from riftline_gm.profiles import GAME_PROFILES
from riftline_gm.telegram_bot import callback, parse_sheet_payload


def test_parse_sheet_payload_accepts_semicolon_pairs():
    fields = parse_sheet_payload(
        "handle: Hex; role: netrunner; hp: 35; humanity: 52; gear: deck, pistol; stats: ref 7"
    )

    assert fields["handle"] == "Hex"
    assert fields["role"] == "netrunner"
    assert fields["hp"] == 35
    assert fields["humanity"] == 52
    assert fields["stats_json"] == {"notes": "ref 7"}


def test_language_keyboard_contains_all_language_options():
    markup = language_keyboard()
    callback_data = {button.callback_data for row in markup.inline_keyboard for button in row}

    assert callback_data == {f"lang:{key}" for key in LANGUAGE_OPTIONS}


def test_profile_keyboard_contains_all_profiles():
    markup = profile_keyboard()
    callback_data = {button.callback_data for row in markup.inline_keyboard for button in row}

    assert callback_data == {f"profile:{key}" for key in GAME_PROFILES}


def test_lobby_and_help_keyboards_expose_guided_actions():
    lobby_data = {button.callback_data for row in lobby_keyboard().inline_keyboard for button in row}
    help_data = {button.callback_data for row in help_keyboard().inline_keyboard for button in row}

    for action in {"menu:join", "menu:character", "menu:help", "menu:players", "menu:summary", "menu:settings"}:
        assert action in lobby_data
    for action in {"menu:join", "menu:character", "roll:d10", "menu:players", "menu:summary", "menu:settings"}:
        assert action in help_data


async def test_language_callback_updates_campaign(tmp_path):
    store = Store(tmp_path / "bot.sqlite")
    store.init_schema()
    config = Config(telegram_bot_token="token", openrouter_api_key="key", sqlite_path=tmp_path / "bot.sqlite")
    openrouter = OpenRouterClient(config)
    context = FakeContext(config, store, openrouter)
    update = FakeUpdate(callback_data="lang:es_es_keep_terms")

    await callback(update, context)

    campaign = store.get_campaign(777)
    assert campaign.language == "es_es_keep_terms"
    assert any("tono" in text.lower() for text in update.callback_query.message.replies)
    await openrouter.close()
    store.close()


class FakeContext:
    def __init__(self, config, store, openrouter):
        self.application = FakeApplication(config, store, openrouter)
        self.bot = FakeBot()


class FakeApplication:
    def __init__(self, config, store, openrouter):
        self.bot_data = {"config": config, "store": store, "openrouter": openrouter}


class FakeBot:
    username = "RiftlineGMTestBot"
    id = 999

    async def get_chat_member(self, chat_id, user_id):
        return FakeMember()


class FakeMember:
    status = "administrator"


class FakeUpdate:
    def __init__(self, callback_data):
        self.effective_chat = FakeChat()
        self.effective_user = FakeUser()
        self.callback_query = FakeCallbackQuery(callback_data, self.effective_user)


class FakeChat:
    id = 777
    title = "Test Chat"
    full_name = None
    type = "supergroup"


class FakeUser:
    id = 42
    username = "admin"
    full_name = "Admin"


class FakeCallbackQuery:
    def __init__(self, data, user):
        self.data = data
        self.from_user = user
        self.message = FakeMessage()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replies.append(text)
