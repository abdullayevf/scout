"""Daily 09:00 Tashkent digest sender.

Beat fires digest.send.daily once at 04:00 UTC (= 09:00 Tashkent), which
fans out one digest.send.user task per active user.
"""

import logging
from collections import namedtuple

from sqlalchemy import select

from apps.bot.keyboards import match_actions_kb
from apps.shared.db import session_scope
from apps.shared.enums import DeliveredVia, ListingState, MatchState, UserState
from apps.shared.matching.coldstart import is_cold_start, stratified_pick
from apps.shared.models import Event, Listing, Match, User
from apps.shared.telegram_send import send_digest_header, send_match_message
from apps.workers.celery_app import app

log = logging.getLogger(__name__)

_Pick = namedtuple("_Pick", ["id", "score", "price_uzs", "area", "is_furnished", "listing_id"])


@app.task(name="digest.send.daily")
def digest_send_daily() -> dict:
    with session_scope() as s:
        ids = [r[0] for r in s.execute(
            select(User.id).where(User.state == UserState.ACTIVE)
        )]
    for uid in ids:
        digest_send_for_user.delay(uid)
    return {"users": len(ids)}


@app.task(name="digest.send.user", bind=True, max_retries=2, default_retry_delay=120)
def digest_send_for_user(self, user_id: int) -> dict:
    with session_scope() as s:
        user = s.get(User, user_id)
        if not user or user.state != UserState.ACTIVE:
            return {"ok": False, "matches": 0}

        rows = s.execute(
            select(Match, Listing)
            .join(Listing, Listing.id == Match.listing_id)
            .where(
                Match.user_id == user_id,
                Match.state == MatchState.PENDING,
                Listing.state == ListingState.ACTIVE,
            )
            .order_by(Match.score.desc())
            .limit(200)
        ).all()

        if not rows:
            return {"ok": True, "matches": 0}

        picks_carriers = [
            _Pick(
                id=m.id, score=m.score,
                price_uzs=l.price_uzs or 0, area=l.area or "",
                is_furnished=l.is_furnished, listing_id=l.id,
            )
            for m, l in rows
        ]
        listing_by_id = {l.id: l for _, l in rows}
        match_by_id = {m.id: m for m, _ in rows}

        if is_cold_start(s, user):
            picks = stratified_pick(picks_carriers, user, k=8)
        else:
            picks = picks_carriers[:8]

        send_digest_header(user, count=len(picks))
        for p in picks:
            match = match_by_id[p.id]
            listing = listing_by_id[p.listing_id]
            send_match_message(
                user, listing, match,
                reply_markup=match_actions_kb(match.id),
            )
            match.state = MatchState.SENT
            match.delivered_via = DeliveredVia.DIGEST
            s.add(Event(
                kind="match_sent_digest",
                user_id=user.id, listing_id=listing.id, match_id=match.id,
            ))
        return {"ok": True, "matches": len(picks)}
