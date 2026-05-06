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


def test_character_draft_persists_for_forum_topic(tmp_path):
    store = Store(tmp_path / "bot.sqlite")
    store.init_schema()

    draft = store.upsert_character_draft(
        chat_id=-100123,
        user_id=55,
        game_profile="cyberpunk_2077",
        current_field="ai",
        topic_thread_id=88,
        topic_name="PJ - Hex",
        data={"sheet": {"handle": "Hex"}},
        active=True,
    )

    assert draft.topic_thread_id == 88
    assert draft.topic_name == "PJ - Hex"
    assert store.maybe_character_draft_by_topic(-100123, 88) == draft

    updated = store.update_character_draft(
        -100123,
        55,
        current_field="ai",
        data={"sheet": {"handle": "Hex", "role": "netrunner"}},
    )

    assert updated.topic_thread_id == 88
    assert updated.data["sheet"]["role"] == "netrunner"
    store.close()


def test_group_topics_are_persisted_by_key(tmp_path):
    store = Store(tmp_path / "bot.sqlite")
    store.init_schema()

    store.upsert_group_topic(-100123, topic_key="start", message_thread_id=12, name="Start Here")
    store.upsert_group_topic(-100123, topic_key="start", message_thread_id=14, name="Start Here")

    row = store.get_group_topic(-100123, "start")
    assert row is not None
    assert row["message_thread_id"] == 14
    assert row["name"] == "Start Here"
    assert len(store.list_group_topics(-100123)) == 1
    store.close()
