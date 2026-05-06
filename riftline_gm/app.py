from __future__ import annotations

import logging

from telegram import Update

from riftline_gm.config import load_config
from riftline_gm.db import Store
from riftline_gm.openrouter import OpenRouterClient
from riftline_gm.telegram_bot import build_application


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = load_config(validate_runtime=True)
    store = Store(config.sqlite_path)
    store.init_schema()
    openrouter = OpenRouterClient(config)
    application = build_application(config, store, openrouter)
    application.run_polling(allowed_updates=Update.ALL_TYPES)
