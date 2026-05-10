import json
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.shared.config import settings


class GroqClient:
    _BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=self._BASE_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            timeout=30.0,
        )
        self._model = settings.groq_model

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    def generate_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        schema_hint = json.dumps(schema.get("properties", {}), ensure_ascii=False)
        full_prompt = (
            f"{prompt}\n\nRespond with a JSON object matching these fields:\n{schema_hint}"
        )
        resp = self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": full_prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    def translate_to_ru(self, text: str) -> str:
        prompt = (
            "Translate the following apartment listing text to Russian. "
            "Preserve numbers, addresses, and proper nouns. Output ONLY the translation, no commentary.\n\n"
            f"---\n{text}\n---"
        )
        resp = self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
