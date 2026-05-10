import json
from pathlib import Path
from unittest.mock import MagicMock

from apps.shared.enrichment.classify import classify_listing


def test_classify_returns_structured_fields():
    expected = json.loads(Path("tests/fixtures/gemini_classify_owner.json").read_text())
    llm = MagicMock()
    llm.generate_json.return_value = expected

    out = classify_listing(
        title="2-\u043a\u043e\u043c\u043d., \u042e\u043d\u0443\u0441\u0430\u0431\u0430\u0434",
        description_ru="\u041f\u0440\u043e\u0441\u0442\u043e\u0440\u043d\u0430\u044f \u0434\u0432\u0443\u0448\u043a\u0430 \u0441 \u043c\u0435\u0431\u0435\u043b\u044c\u044e...",
        llm=llm,
    )
    assert out["search_type"] == "whole_apt_solo"
    assert out["bathroom_type"] == "private"
    assert out["poster_role"] == "owner"
    llm.generate_json.assert_called_once()


def test_classify_handles_missing_optional_fields():
    llm = MagicMock()
    llm.generate_json.return_value = {
        "search_type": "shared_room",
        "gender_constraint": "female",
        "is_furnished": None,
        "has_parking": None,
        "is_first_floor": None,
        "bathroom_type": "shared",
        "poster_role": "unknown",
        "agent_fee_text": None,
        "summary_one_line": "\u041a\u043e\u043c\u043d\u0430\u0442\u0430 \u0434\u043b\u044f \u0434\u0435\u0432\u0443\u0448\u043a\u0438.",
    }
    out = classify_listing(title="", description_ru="\u043a\u043e\u043c\u043d\u0430\u0442\u0430 \u0434\u0435\u0432\u0443\u0448\u043a\u0435", llm=llm)
    assert out["gender_constraint"] == "female"
    assert out["is_furnished"] is None
