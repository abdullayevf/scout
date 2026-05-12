"""KPI chase runners, weekly check-in, and maintenance tasks."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from sqlalchemy import select, update

from apps.shared.config import settings
from apps.shared.db import session_scope
from apps.shared.enums import MatchState, UserState
from apps.shared.models import Event, Match, User
from apps.workers.celery_app import app

log = logging.getLogger(__name__)


def _bot_send(tg_user_id: int, text: str, reply_markup=None) -> None:
    async def _send():
        bot = Bot(token=settings.telegram_bot_token)
        try:
            await bot.send_message(chat_id=tg_user_id, text=text, reply_markup=reply_markup)
        finally:
            await bot.session.close()
    asyncio.run(_send())


@app.task(name="kpi.chase.48h.run")
def kpi_chase_48h_run() -> dict:
    """Every 10 min: send '48h contact?' chase for due matches."""
    from apps.bot.keyboards import chase_48h_kb
    now = datetime.now(UTC)
    sent = 0
    with session_scope() as s:
        due = s.execute(
            select(Match).where(
                Match.chase_48h_due_at <= now,
                Match.chase_48h_done_at.is_(None),
                Match.state.in_([MatchState.LIKED, MatchState.CONTACTED]),
            )
        ).scalars().all()
        for m in due:
            user = s.get(User, m.user_id)
            m.chase_48h_done_at = now
            if user is None or user.state != UserState.ACTIVE:
                continue
            _bot_send(
                user.tg_user_id,
                f"📋 Вы связались с этим объявлением? (match #{m.id})",
                reply_markup=chase_48h_kb(m.id),
            )
            s.add(Event(kind="chase_48h_sent", user_id=user.id, match_id=m.id))
            sent += 1
        s.flush()
    return {"sent": sent}


@app.task(name="kpi.chase.5d.run")
def kpi_chase_5d_run() -> dict:
    """Every 10 min: send '5d rented?' chase for due matches."""
    from apps.bot.keyboards import chase_5d_kb
    now = datetime.now(UTC)
    sent = 0
    with session_scope() as s:
        due = s.execute(
            select(Match).where(
                Match.chase_5d_due_at <= now,
                Match.chase_5d_done_at.is_(None),
                Match.state == MatchState.CONTACTED,
            )
        ).scalars().all()
        for m in due:
            user = s.get(User, m.user_id)
            m.chase_5d_done_at = now
            if user is None or user.state != UserState.ACTIVE:
                continue
            _bot_send(
                user.tg_user_id,
                f"🏠 Вы сняли эту квартиру? (match #{m.id})",
                reply_markup=chase_5d_kb(m.id),
            )
            s.add(Event(kind="chase_5d_sent", user_id=user.id, match_id=m.id))
            sent += 1
        s.flush()
    return {"sent": sent}


@app.task(name="kpi.weekly.checkin.send")
def kpi_weekly_checkin_send() -> dict:
    """Sunday 13:00 UTC (18:00 Tashkent): check-in with all ACTIVE users."""
    from apps.bot.keyboards import weekly_checkin_kb
    sent = 0
    with session_scope() as s:
        users = s.execute(
            select(User).where(User.state == UserState.ACTIVE)
        ).scalars().all()
        for u in users:
            _bot_send(
                u.tg_user_id,
                "📅 Воскресная проверка: вы ещё ищете квартиру?",
                reply_markup=weekly_checkin_kb(),
            )
            s.add(Event(kind="weekly_checkin_sent", user_id=u.id))
            sent += 1
    return {"sent": sent}


@app.task(name="kpi.maintenance.purge_inactive")
def kpi_maintenance_purge_inactive(inactive_days: int = 90) -> dict:
    """Daily 02:00 UTC: mark ACTIVE users with stale last_active_at as DELETED."""
    cutoff = datetime.now(UTC) - timedelta(days=inactive_days)
    with session_scope() as s:
        result = s.execute(
            update(User)
            .where(User.state == UserState.ACTIVE, User.last_active_at < cutoff)
            .values(state=UserState.DELETED)
        )
    return {"deleted": result.rowcount or 0}
