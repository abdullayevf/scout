import json
from typing import Any

from google import genai
from tenacity import retry, stop_after_attempt, wait_exponential

from apps.shared.config import settings


class GeminiClient:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = settings.gemini_model
        self._embed_model = settings.gemini_embed_model

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=10), reraise=True)
    def generate_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Call Gemini with structured-output mode and parse the JSON response."""
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": schema,
                "temperature": 0.1,
            },
        )
        return json.loads(resp.text)

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=10), reraise=True)
    def translate_to_ru(self, text: str) -> str:
        prompt = (
            "Translate the following apartment listing text to Russian. "
            "Preserve numbers, addresses, and proper nouns. Output ONLY the translation, no commentary.\n\n"
            f"---\n{text}\n---"
        )
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config={"temperature": 0.0},
        )
        return resp.text.strip()

    @retry(stop=stop_after_attempt(4), wait=wait_exponential(min=1, max=10), reraise=True)
    def embed(self, text: str) -> list[float]:
        resp = self._client.models.embed_content(
            model=self._embed_model,
            contents=text,
        )
        # google-genai returns either single or list of embeddings depending on input shape
        emb = resp.embeddings[0]
        return list(emb.values)
