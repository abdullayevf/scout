import logging
import re

from playwright.async_api import async_playwright

from apps.shared.scraping.ua_pool import UAPool

log = logging.getLogger(__name__)

_PHONE_RE = r"\+?998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"


class PhoneRevealer:
    """Reveals the phone behind OLX's "Show phone" click. One-shot per listing."""

    def __init__(self) -> None:
        self._uas = UAPool()

    async def reveal(self, listing_url: str, timeout_ms: int = 25000) -> str | None:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=self._uas.next(), locale="ru-RU")
            page = await ctx.new_page()
            try:
                await page.goto(listing_url, wait_until="load", timeout=timeout_ms)
                button = page.locator('button[data-cy="ad-contact-phone"]').first
                try:
                    await button.wait_for(state="visible", timeout=timeout_ms)
                except Exception:
                    log.warning("phone reveal button not found on %s", listing_url)
                    return None
                await button.click(timeout=timeout_ms)
                try:
                    await page.wait_for_function(
                        f"() => new RegExp({_PHONE_RE!r}).test(document.body.innerText)",
                        timeout=timeout_ms,
                    )
                except Exception:
                    log.warning("phone number did not appear after click on %s", listing_url)
                    return None
                body = await page.evaluate("() => document.body.innerText")
                m = re.search(_PHONE_RE, body)
                return m.group(0).strip() if m else None
            finally:
                await ctx.close()
                await browser.close()
