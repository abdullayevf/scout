"""Templated reason strings for match messages.

Reasons are computed once at fanout time and stored on the Match row so
the user always sees what the listing looked like *then*, not now.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from apps.shared.enums import PosterRole


@dataclass
class ScoreComponents:
    """Carrier for facts the reason builder needs but the listing alone
    doesn't expose (e.g. routing result)."""

    cosine: float | None = None
    budget_score: float | None = None
    commute_minutes: int | None = None
    commute: float | None = None
    freshness: float | None = None
    source_rep: float | None = None
    axis_bonus: float | None = None
    risk_penalty: int = 0


TUMAN_RU = {
    "Bektemir": "Бектемир",
    "Chilanzar": "Чиланзар",
    "Mirobod": "Мирабад",
    "Mirzo Ulugbek": "Мирзо-Улугбек",
    "Sergeli": "Сергели",
    "Shaykhantakhur": "Шайхантахур",
    "Uchtepa": "Учтепа",
    "Yakkasaray": "Яккасарай",
    "Yashnobod": "Яшнабад",
    "Yunusabad": "Юнусабад",
    "Almazar": "Алмазар",
    "Yangihayot": "Янгихаёт",
}


def format_uzs(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " UZS"


def rooms_str(rooms: int | None) -> str:
    if rooms is None:
        return "квартира"
    return f"{rooms}-комн."


def tuman_ru(area: str | None) -> str:
    if area is None:
        return ""
    return TUMAN_RU.get(area, area)


def age_human(posted_at: datetime | None) -> str:
    if posted_at is None:
        return "недавно"
    now = datetime.now(timezone.utc)
    delta = now - posted_at
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} мин назад"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} ч назад"
    days = hours // 24
    if days == 1:
        return "вчера"
    return f"{days} дн назад"


def build_reasons(user, listing, components: ScoreComponents) -> list[str]:
    out: list[str] = []

    if listing.price_uzs is not None:
        budget_max = getattr(user, "budget_max", None) or 0
        suffix = "в твоём бюджете" if listing.price_uzs <= budget_max else "выше бюджета"
        out.append(f"💰 {format_uzs(listing.price_uzs)} · {suffix}")

    if components.commute_minutes is not None:
        out.append(f"🚇 {components.commute_minutes} мин до работы")

    out.append(f"🆕 {age_human(listing.posted_at)}")

    if listing.location_text:
        out.append(f"📍 {listing.location_text}")

    role = listing.poster_role
    if role == PosterRole.OWNER:
        out.append("👤 хозяин")
    elif role == PosterRole.AGENT:
        if listing.agent_fee_text:
            out.append(f"🏢 агент · комиссия {listing.agent_fee_text}")
        else:
            out.append("🏢 агент")

    flags = listing.risk_flags or {}
    if flags.get("phash_collision"):
        out.append("⚠️ возможно повторное фото")
    if flags.get("price_outlier"):
        out.append("⚠️ необычно низкая цена")

    return out
