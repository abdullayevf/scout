CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "search_type": {
            "type": "string",
            "enum": [
                "whole_apt_family",
                "whole_apt_solo",
                "shared_room",
                "looking_for_roommate",
            ],
        },
        "gender_constraint": {
            "type": "string",
            "enum": ["any", "male", "female"],
        },
        "is_furnished": {"type": "boolean", "nullable": True},
        "has_parking": {"type": "boolean", "nullable": True},
        "is_first_floor": {"type": "boolean", "nullable": True},
        "bathroom_type": {
            "type": "string",
            "enum": ["private", "shared", "unknown"],
        },
        "poster_role": {
            "type": "string",
            "enum": ["owner", "agent", "unknown"],
        },
        "agent_fee_text": {"type": "string", "nullable": True},
        "summary_one_line": {"type": "string"},
    },
    "required": [
        "search_type",
        "gender_constraint",
        "bathroom_type",
        "poster_role",
        "summary_one_line",
    ],
}


# Prompt template (Cyrillic text uses Unicode escapes for ruff RUF001 compliance).
CLASSIFY_PROMPT = (
    "\u0422\u044b \u043f\u043e\u043c\u043e\u0433\u0430\u0435\u0448\u044c \u0441\u0435\u0440\u0432\u0438\u0441\u0443 \u043f\u043e\u0438\u0441\u043a\u0430 \u043a\u0432\u0430\u0440\u0442\u0438\u0440 \u0432 \u0422\u0430\u0448\u043a\u0435\u043d\u0442\u0435.\n"
    "\u0418\u0437\u0432\u043b\u0435\u043a\u0438 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u044b\u0435 \u043f\u043e\u043b\u044f \u0438\u0437 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u044f \u043d\u0438\u0436\u0435.\n"
    "\u0415\u0441\u043b\u0438 \u043d\u0435 \u0443\u0432\u0435\u0440\u0435\u043d \u0432 \u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0438 \u2014 \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0430\u0439 null \u0438\u043b\u0438 \"unknown\".\n"
    "\"summary_one_line\" \u2014 \u043a\u043e\u0440\u043e\u0442\u043a\u043e\u0435 (\u2264120 \u0441\u0438\u043c\u0432.) \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u044f \u043d\u0430 \u0440\u0443\u0441\u0441\u043a\u043e\u043c.\n"
    "\n"
    "\u0417\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a:\n{title}\n\n"
    "\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435:\n{description}"
)


def classify_listing(*, title: str, description_ru: str, llm) -> dict:
    prompt = CLASSIFY_PROMPT.format(title=title or "", description=description_ru or "")
    return llm.generate_json(prompt, schema=CLASSIFY_SCHEMA)
