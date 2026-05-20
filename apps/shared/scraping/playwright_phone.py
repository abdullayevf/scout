import asyncio
import logging
import re

from playwright.async_api import async_playwright

from apps.shared.scraping.ua_pool import UAPool

log = logging.getLogger(__name__)

_PHONE_RE = r"\+?998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"

# OLX sits behind CloudFront and intermittently serves
# "ERROR: The request could not be satisfied" to headless Chromium.
# Stealth patches hide the most obvious automation tells; the retry loop
# handles the residual flakiness when patches alone are not enough.
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU','ru','en-US','en'] });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
window.chrome = { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (p) => (
        p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : origQuery(p)
    );
}
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    if (parameter === 37445) return 'Intel Inc.';
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.apply(this, [parameter]);
};
"""

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

_CLOUDFRONT_403_TITLE = "ERROR: The request could not be satisfied"
_MAX_ATTEMPTS = 3


class PhoneRevealer:
    """Reveals the phone behind OLX's "Show phone" click. One-shot per listing."""

    def __init__(self) -> None:
        self._uas = UAPool()

    async def reveal(self, listing_url: str, timeout_ms: int = 25000) -> str | None:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            result = await self._try_once(listing_url, timeout_ms)
            if result == "BLOCKED":
                if attempt < _MAX_ATTEMPTS:
                    log.warning(
                        "CloudFront blocked reveal for %s (attempt %d/%d), retrying",
                        listing_url, attempt, _MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(2 * attempt)
                    continue
                log.warning("CloudFront blocked reveal for %s after %d attempts", listing_url, _MAX_ATTEMPTS)
                return None
            return result
        return None

    async def _try_once(self, listing_url: str, timeout_ms: int) -> str | None:
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
                # Warm-up: hit the OLX home first so CloudFront issues us session
                # cookies before we touch the listing. Without this the first
                # request to a deep URL is reliably served the 403 page.
                await page.goto("https://www.olx.uz/", wait_until="load", timeout=timeout_ms)
                if _CLOUDFRONT_403_TITLE in (await page.title()):
                    return "BLOCKED"
                await asyncio.sleep(1.5)
                await page.goto(listing_url, wait_until="load", timeout=timeout_ms)
                title = await page.title()
                if _CLOUDFRONT_403_TITLE in title:
                    return "BLOCKED"
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
