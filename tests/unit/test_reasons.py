from dataclasses import dataclass
from datetime import datetime, timedelta, UTC

from apps.shared.enums import PosterRole
from apps.shared.matching.reasons import (
    build_reasons,
    format_uzs,
    age_human,
    rooms_str,
    tuman_ru,
    ScoreComponents,
)


def _listing(**kw):
    @dataclass
    class L:
        price_uzs: int = 1_400_000
        rooms: int | None = 2
        area: str | None = "Yunusabad"
        poster_role: str | None = PosterRole.OWNER
        agent_fee_text: str | None = None
        posted_at: datetime | None = None
        is_furnished: bool | None = None
        risk_flags: dict | None = None
        summary_one_line: str | None = None
    return L(**kw)


def _user(**kw):
    @dataclass
    class U:
        budget_min: int = 1_000_000
        budget_max: int = 1_500_000
    return U(**kw)


def test_format_uzs_thousands_separator():
    assert format_uzs(1_400_000) == "1 400 000 UZS"


def test_age_human_buckets():
    now = datetime.now(UTC)
    assert "мин назад" in age_human(now - timedelta(minutes=12))
    assert "ч назад" in age_human(now - timedelta(hours=3))
    assert age_human(now - timedelta(hours=20)) == "вчера" or "ч назад" in age_human(now - timedelta(hours=20))
    assert "дн назад" in age_human(now - timedelta(days=3))


def test_rooms_str():
    assert rooms_str(2) == "2-комн."
    assert rooms_str(None) == "квартира"
    assert rooms_str(4) == "4-комн."


def test_tuman_ru_passthrough():
    assert tuman_ru("Yunusabad") == "Юнусабад"
    assert tuman_ru("Chilanzar") == "Чиланзар"


def test_reasons_under_budget():
    posted = datetime.now(UTC) - timedelta(minutes=30)
    r = build_reasons(
        _user(),
        _listing(price_uzs=1_400_000, posted_at=posted),
        ScoreComponents(cosine=0.7),
    )
    assert any("в твоём бюджете" in s for s in r)
    assert any("📍 Юнусабад" in s for s in r)
    assert any("👤 хозяин" in s for s in r)


def test_reasons_over_budget():
    posted = datetime.now(UTC) - timedelta(hours=2)
    r = build_reasons(
        _user(budget_max=1_500_000),
        _listing(price_uzs=1_800_000, posted_at=posted),
        ScoreComponents(),
    )
    assert any("выше бюджета" in s for s in r)


def test_reasons_agent_with_fee():
    r = build_reasons(
        _user(),
        _listing(poster_role=PosterRole.AGENT, agent_fee_text="50%"),
        ScoreComponents(),
    )
    assert any("🏢 агент · комиссия 50%" in s for s in r)


def test_reasons_agent_without_fee():
    r = build_reasons(
        _user(),
        _listing(poster_role=PosterRole.AGENT),
        ScoreComponents(),
    )
    assert any(s == "🏢 агент" for s in r)


def test_reasons_includes_commute_when_known():
    r = build_reasons(
        _user(),
        _listing(),
        ScoreComponents(commute_minutes=18),
    )
    assert any("🚇 18 мин до работы" in s for s in r)


def test_reasons_omits_commute_when_unknown():
    r = build_reasons(_user(), _listing(), ScoreComponents(commute_minutes=None))
    assert not any("🚇" in s for s in r)


def test_reasons_risk_warnings():
    r = build_reasons(
        _user(),
        _listing(risk_flags={"phash_collision": True, "price_outlier": True}),
        ScoreComponents(),
    )
    assert any("возможно повторное фото" in s for s in r)
    assert any("необычно низкая цена" in s for s in r)
