import logging
import re

from playwright.async_api import async_playwright

from apps.shared.scraping.ua_pool import UAPool

log = logging.getLogger(__name__)

_PHONE_RE = r"\+?998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"

# OLX is fronted by CloudFront and returns a 403 ERROR page to default
# Playwright Chromium because `navigator.webdriver` and the bot-default
# `HeadlessChrome` user-agent are easy automation tells. Patching these
# in an init script makes the page render normally.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU','ru','en-US','en'] });
window.chrome = { runtime: {} };
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (p) => (
        p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : origQuery(p)
    );
}
"""

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


class PhoneRevealer:
    """Reveals the phone behind OLX's "Show phone" click. One-shot per listing."""

    def __init__(self) -> None:
        self._uas = UAPool()

    async def reveal(self, listing_url: str, timeout_ms: int = 25000) -> str | None:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=_LAUNCH_ARGS)
            ctx = await browser.new_context(
                user_agent=self._uas.next(),
                locale="ru-RU",
                viewport={"width": 1366, "height": 768},
            )
            await ctx.add_init_script(_STEALTH_JS)
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
