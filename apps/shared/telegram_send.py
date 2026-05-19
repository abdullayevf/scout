import asyncio
import logging
from aiogram import Bot
from aiogram.types import InputMediaPhoto
from apps.shared.config import settings
from apps.shared.matching.reasons import rooms_str, tuman_ru

log = logging.getLogger(__name__)

def format_match_text(listing, reasons: list[str], prefix: str = "") -> str:
    lines: list[str] = []
    if prefix:
        lines.append(prefix)

    header = f"🏠 {rooms_str(listing.rooms)}, {tuman_ru(listing.area)}"
    if listing.floor and listing.total_floors:
        header += f" · {listing.floor}/{listing.total_floors} эт."
    elif listing.floor:
        header += f" · {listing.floor} эт."
    lines.append(header)

    lines.extend(reasons)

    amenities = []
    if listing.is_furnished:
        amenities.append("🛋 мебель")
    if listing.has_parking:
        amenities.append("🚗 парковка")
    if amenities:
        lines.append(" · ".join(amenities))

    if listing.summary_one_line:
        lines.append("")
        lines.append(listing.summary_one_line)
    lines.append("")
    lines.append(f"🔗 {listing.source_url}")
    return "\n".join(lines)

def send_match_message(user, listing, match, prefix: str = "", reply_markup=None) -> None:
    asyncio.run(_async_send_match_message(user, listing, match, prefix, reply_markup))

def send_digest_header(user, count: int) -> None:
    asyncio.run(_async_send_digest_header(user, count))

async def _async_send_match_message(user, listing, match, prefix, reply_markup):
    bot = Bot(token=settings.telegram_bot_token)
    try:
        text = format_match_text(listing, match.reasons, prefix=prefix)
        if listing.image_urls:
            try:
                await bot.send_media_group(
                    chat_id=user.tg_user_id,
                    media=[InputMediaPhoto(media=u) for u in listing.image_urls[:4]],
                )
            except Exception as e:
                log.warning("media group send failed for tg=%s: %s", user.tg_user_id, e)
        await bot.send_message(chat_id=user.tg_user_id, text=text, reply_markup=reply_markup)
    finally:
        await bot.session.close()

async def _async_send_digest_header(user, count: int):
    bot = Bot(token=settings.telegram_bot_token)
    try:
        await bot.send_message(
            chat_id=user.tg_user_id,
            text=f"Доброе утро ☀️ Подобрал {count} вариантов на сегодня"
        )
    finally:
        await bot.session.close()
