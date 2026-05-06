from riftline_gm.characters import (
    draft_to_player_fields,
    missing_minimum_fields,
    parse_character_ai_response,
)
from riftline_gm.models import CharacterDraft


def test_parse_character_ai_response_merges_sheet_and_ready_state():
    payload = """
    {
      "message": "Perfecto. Ya tengo lo base.",
      "sheet": {
        "handle": "Hex",
        "concept": "ex corpo on the run",
        "role": "netrunner"
      },
      "ready": true,
      "missing": []
    }
    """

    parsed = parse_character_ai_response(payload, {"style": "red jacket"})

    assert parsed["ready"] is True
    assert parsed["sheet"]["style"] == "red jacket"
    assert parsed["sheet"]["handle"] == "Hex"
    assert parsed["missing"] == []


def test_parse_character_ai_response_blocks_ready_when_minimum_fields_are_missing():
    parsed = parse_character_ai_response(
        '{"message":"Dame nombre.","sheet":{"concept":"solo merc"},"ready":true,"missing":[]}',
        {},
    )

    assert parsed["ready"] is False
    assert set(parsed["missing"]) == {"handle", "role"}


def test_draft_to_player_fields_maps_generic_ai_sheet_to_light_sheet():
    draft = CharacterDraft(
        chat_id=1,
        user_id=2,
        game_profile="cyberpunk_2077",
        current_field="ai",
        topic_thread_id=99,
        topic_name="PJ - Hex",
        data={
            "sheet": {
                "handle": "Hex",
                "concept": "burned corpo courier",
                "role": "fixer",
                "style": "chrome jacket",
                "skills": "street deals, lies",
                "durability": "HP 35",
                "strain": "Humanity 52",
                "special": "neural link",
            }
        },
        active=True,
    )

    fields = draft_to_player_fields(draft)

    assert missing_minimum_fields(draft.data["sheet"]) == ()
    assert fields["handle"] == "Hex"
    assert fields["role"] == "fixer"
    assert fields["hp"] == 35
    assert fields["humanity"] == 52
    assert fields["cyberware"] == "neural link"
    assert "burned corpo courier" in fields["notes"]
