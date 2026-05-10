import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.shared.config import settings
from apps.shared.scraping.ua_pool import UAPool


class OlxClient:
    def __init__(self, ua_pool: UAPool | None = None) -> None:
        self._uas = ua_pool or UAPool()
        proxies = settings.scrape_proxy_url or None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0, connect=10.0),
            follow_redirects=True,
            proxy=proxies,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru,en;q=0.7",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _get(self, url: str) -> httpx.Response:
        return await self._client.get(url, headers={"User-Agent": self._uas.next()})

    async def fetch_list(self, url: str) -> tuple[str, bool]:
        try:
            r = await self._get(url)
        except Exception:
            return "", False
        return r.text, 200 <= r.status_code < 300

    async def fetch_detail(self, url: str) -> tuple[str, bool]:
        return await self.fetch_list(url)
