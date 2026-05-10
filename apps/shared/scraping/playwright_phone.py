import logging

from playwright.async_api import async_playwright

from apps.shared.scraping.ua_pool import UAPool

log = logging.getLogger(__name__)


class PhoneRevealer:
    """Reveals the phone behind OLX's "Show phone" click. One-shot per listing."""

    def __init__(self) -> None:
        self._uas = UAPool()

    async def reveal(self, listing_url: str, timeout_ms: int = 20000) -> str | None:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=self._uas.next(), locale="ru-RU")
            page = await ctx.new_page()
            try:
                await page.goto(listing_url, wait_until="domcontentloaded", timeout=timeout_ms)
                # OLX phone-reveal button — text-based selectors are most stable across redesigns
                button = page.get_by_role(
                    "button",
                    name=lambda t: bool(t and ("Показать телефон" in t or "Show phone" in t)),
                )
                if await button.count() == 0:
                    log.warning("phone reveal button not found on %s", listing_url)
                    return None
                await button.first.click(timeout=timeout_ms)
                # phone usually rendered inside an <a href="tel:..."> or within a span next to the button
                tel = page.locator("a[href^='tel:']").first
                await tel.wait_for(state="visible", timeout=timeout_ms)
                href = await tel.get_attribute("href")
                if href and href.startswith("tel:"):
                    return href.removeprefix("tel:").strip()
                return (await tel.inner_text()).strip() or None
            finally:
                await ctx.close()
                await browser.close()
