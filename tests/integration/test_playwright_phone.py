import os

import pytest

from apps.shared.scraping.playwright_phone import PhoneRevealer


@pytest.mark.skipif(
    not os.getenv("RUN_PLAYWRIGHT_LIVE"),
    reason="set RUN_PLAYWRIGHT_LIVE=1 and PHONE_REVEAL_URL=<olx-listing> to run",
)
@pytest.mark.asyncio
async def test_reveal_phone_live():
    url = os.environ["PHONE_REVEAL_URL"]
    phone = await PhoneRevealer().reveal(url)
    # Sanity: contains digits, length plausible
    digits = "".join(c for c in (phone or "") if c.isdigit())
    assert len(digits) >= 9
