from datetime import UTC, datetime, timedelta

from riftline_gm.db import Store


def test_campaign_player_and_image_persistence(tmp_path):
    db_path = tmp_path / "bot.sqlite"
    store = Store(db_path)
    store.init_schema()

    campaign = store.get_or_create_campaign(
        123,
        title="Night City",
        default_game_profile="cyberpunk_2077",
        default_language="es_latam_keep_terms",
        content_preset="gritty_21_plus",
    )
    assert campaign.chat_id == 123
    assert campaign.game_profile == "cyberpunk_2077"
    assert campaign.language == "es_latam_keep_terms"

    updated = store.update_campaign(123, active=1, language="es_es_full")
    assert updated.active is True
    assert updated.language == "es_es_full"

    player = store.upsert_player(chat_id=123, user_id=55, username="hex", display_name="Hex")
    assert player.active is True
    assert store.count_active_players(123) == 1

    player = store.update_player_sheet(123, 55, handle="Hex", role="netrunner", hp=35)
    assert player.handle == "Hex"
    assert player.role == "netrunner"
    assert player.hp == 35

    request = store.create_image_request(
        chat_id=123,
        user_id=55,
        original_prompt="callejon",
        drafted_prompt="neon alley",
    )
    store.update_image_request(request.id, status="generated", image_url="data:image/png;base64,abc")
    assert store.count_generated_images_since(123, datetime.now(UTC) - timedelta(days=1)) == 1

    store.close()
