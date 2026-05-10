from unittest.mock import MagicMock, patch

from apps.shared.llm.gemini import GeminiClient


@patch("apps.shared.llm.gemini.genai.Client")
def test_generate_json_parses_response(MockClient):
    inst = MockClient.return_value
    fake = MagicMock()
    fake.text = '{"x": 1, "y": "z"}'
    inst.models.generate_content.return_value = fake

    c = GeminiClient()
    out = c.generate_json("anything", schema={"type": "object"})
    assert out == {"x": 1, "y": "z"}


@patch("apps.shared.llm.gemini.genai.Client")
def test_translate_strips_whitespace(MockClient):
    inst = MockClient.return_value
    fake = MagicMock()
    fake.text = "  Привет!\n"
    inst.models.generate_content.return_value = fake

    c = GeminiClient()
    assert c.translate_to_ru("Hello!") == "Привет!"
