import pytest
import respx
from httpx import Response

from apps.shared.scraping.olx_client import OlxClient


@pytest.mark.asyncio
@respx.mock
async def test_fetch_list_returns_html_and_marks_success():
    respx.get("https://www.olx.uz/nedvizhimost/dolgosrochnaya-arenda-kvartir/tashkent/").mock(
        return_value=Response(200, text="<html>list</html>")
    )
    client = OlxClient()
    html, ok = await client.fetch_list("https://www.olx.uz/nedvizhimost/dolgosrochnaya-arenda-kvartir/tashkent/")
    assert ok and "<html>list" in html
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_returns_failure_on_5xx():
    respx.get("https://www.olx.uz/x").mock(return_value=Response(503, text="bad"))
    client = OlxClient()
    _html, ok = await client.fetch_list("https://www.olx.uz/x")
    assert not ok
    await client.aclose()
