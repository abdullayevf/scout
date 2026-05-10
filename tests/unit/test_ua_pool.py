from apps.shared.scraping.ua_pool import UAPool


def test_ua_pool_rotates():
    pool = UAPool(["A", "B", "C"])
    seen = {pool.next() for _ in range(20)}
    assert seen == {"A", "B", "C"}


def test_ua_pool_default_has_modern_chrome():
    pool = UAPool()
    ua = pool.next()
    assert "Mozilla" in ua and "Chrome" in ua
