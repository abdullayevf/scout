"""Match fanout, instant alerts, threshold recompute, dead cleanup."""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update

from apps.shared.db import session_scope
from apps.shared.enums import (
    DeliveredVia, ListingState, MatchState, UserState,
)
from apps.shared.matching import config as cfg
from apps.shared.matching.coldstart import is_cold_start
from apps.shared.matching.filters import python_filter_pass, sql_filter_candidates
from apps.shared.matching.score import score_listing_for_user
from apps.shared.models import Event, Listing, Match, User
from apps.shared.telegram_send import send_match_message, send_plain_text
from apps.workers.celery_app import app
from apps.workers.tasks.digest import _Pick as _WelcomePick

log = logging.getLogger(__name__)


@app.task(name="match.fanout.listing", bind=True, max_retries=2, default_retry_delay=60)
def match_fanout_listing(self, listing_id: int) -> dict:
    pending_alerts: list[int] = []
    n_candidates = 0
    n_inserted = 0

    with session_scope() as s:
        listing = s.get(Listing, listing_id)
        if listing is None or listing.state != ListingState.ACTIVE:
            return {"ok": False, "reason": "not eligible"}
        if listing.suppressed:
            return {"ok": False, "reason": "suppressed"}
        if listing.canonical_listing_id is not None:
            return {"ok": False, "reason": "canonical pointer"}

        candidates = sql_filter_candidates(s, listing)
        n_candidates = len(candidates)

        # Skip users who already have a match row for this listing (idempotency).
        existing_user_ids = {
            row[0] for row in s.execute(
                select(Match.user_id).where(Match.listing_id == listing.id)
            )
        }
        candidates = [u for u in candidates if u.id not in existing_user_ids]

        for user in candidates:
            if not python_filter_pass(user, listing):
                continue
            score, reasons, _ = score_listing_for_user(user, listing)
            if score < cfg.INSERT_THRESHOLD:
                continue
            m = Match(
                user_id=user.id, listing_id=listing.id,
                score=score, reasons=reasons,
                state=MatchState.PENDING,
            )
            s.add(m)
            s.flush()
            n_inserted += 1
            threshold = user.top_1pct_threshold or 999.0
            if score >= threshold and not is_cold_start(s, user):
                pending_alerts.append(m.id)

    # Dispatch AFTER session commits — match rows are now visible.
    for mid in pending_alerts:
        match_alert_instant.delay(mid)

    return {"ok": True, "candidates": n_candidates, "inserted": n_inserted}


@app.task(name="match.alert.instant", bind=True, max_retries=2, default_retry_delay=60)
def match_alert_instant(self, match_id: int) -> dict:
    from apps.shared.telegram_send import send_match_message
    from apps.bot.keyboards import match_actions_kb

    with session_scope() as s:
        m = s.get(Match, match_id)
        if not m or m.state != MatchState.PENDING:
            return {"ok": False, "reason": "state changed"}
        user = s.get(User, m.user_id)
        if not user or user.state != UserState.ACTIVE:
            return {"ok": False, "reason": "user inactive"}

        now_tsk = datetime.now(ZoneInfo("Asia/Tashkent"))
        if now_tsk.hour >= cfg.QUIET_HOURS_START or now_tsk.hour < cfg.QUIET_HOURS_END:
            return {"ok": False, "reason": "quiet hours"}

        today_start = now_tsk.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        delivered_today = s.execute(
            select(func.count()).select_from(Match)
            .where(Match.user_id == user.id,
                   Match.delivered_via == DeliveredVia.INSTANT,
                   Match.created_at >= today_start)
        ).scalar() or 0
        if delivered_today >= cfg.INSTANT_DAILY_CAP:
            return {"ok": False, "reason": "cap reached"}

        listing = s.get(Listing, m.listing_id)
        send_match_message(
            user, listing, m,
            prefix="🔥 Свежий топ-вариант",
            reply_markup=match_actions_kb(m.id),
        )
        m.state = MatchState.SENT
        m.delivered_via = DeliveredVia.INSTANT
        s.add(Event(
            kind="match_sent_instant",
            user_id=user.id, listing_id=listing.id, match_id=m.id,
        ))
        return {"ok": True}


@app.task(name="match.threshold.recompute")
def match_threshold_recompute() -> dict:
    """Daily 05:00 UTC: recompute per-user top_1pct_threshold.

    Priority: reaction-weighted p99 (liked/contacted/rented) → personal p99 → global p99 → bootstrap.
    """
    with session_scope() as s:
        cutoff = datetime.now(UTC) - timedelta(days=14)
        global_scores = [
            row[0] for row in s.execute(
                select(Match.score).where(Match.created_at >= cutoff)
            )
        ]
        global_p99 = _percentile(global_scores, 99) if len(global_scores) >= cfg.THRESHOLD_MIN_GLOBAL else None

        user_ids = [r[0] for r in s.execute(
            select(User.id).where(User.state == UserState.ACTIVE)
        )]
        updated = 0
        for uid in user_ids:
            reaction_scores = [
                r[0] for r in s.execute(
                    select(Match.score).where(
                        Match.user_id == uid,
                        Match.state.in_([MatchState.LIKED, MatchState.CONTACTED, MatchState.RENTED]),
                        Match.created_at >= cutoff,
                    )
                )
            ]
            if len(reaction_scores) >= cfg.THRESHOLD_MIN_REACTIONS:
                t = _percentile(reaction_scores, 99)
            else:
                personal = [
                    r[0] for r in s.execute(
                        select(Match.score).where(
                            Match.user_id == uid,
                            Match.created_at >= cutoff,
                        )
                    )
                ]
                if len(personal) >= cfg.THRESHOLD_MIN_PERSONAL:
                    t = _percentile(personal, 99)
                elif global_p99 is not None:
                    t = global_p99
                else:
                    t = cfg.GLOBAL_TOP1PCT_BOOTSTRAP
            s.execute(
                update(User).where(User.id == uid).values(top_1pct_threshold=t)
            )
            updated += 1
        return {"updated": updated, "global_p99": global_p99}


@app.task(name="match.cleanup.dead")
def match_cleanup_dead() -> dict:
    """Mark matches whose listing is dead as dead too."""
    with session_scope() as s:
        result = s.execute(
            update(Match)
            .where(Match.state == MatchState.PENDING)
            .where(Match.listing_id.in_(
                select(Listing.id).where(Listing.state == ListingState.DEAD)
            ))
            .values(state=MatchState.DEAD)
        )
        return {"updated": result.rowcount or 0}


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sv = sorted(values)
    k = (len(sv) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sv) - 1)
    frac = k - lo
    return sv[lo] + (sv[hi] - sv[lo]) * frac


@app.task(name="match.welcome.user", bind=True, max_retries=2, default_retry_delay=120)
def match_welcome_for_user(self, user_id: int) -> dict:
    from apps.bot.keyboards import match_actions_kb
    from apps.bot.messages import welcome_batch_closing
    from apps.shared.matching.coldstart import stratified_pick

    with session_scope() as s:
        user = s.get(User, user_id)
        if not user or user.state != UserState.ACTIVE:
            return {"ok": False, "reason": "user inactive"}

        cutoff = datetime.now(UTC) - timedelta(days=7)
        listings = list(s.execute(
            select(Listing)
            .where(Listing.state == ListingState.ACTIVE)
            .where(Listing.enriched_at >= cutoff)
            .where(Listing.suppressed.is_(False))
            .where(Listing.canonical_listing_id.is_(None))
        ).scalars())

        existing_ids = {
            row[0] for row in s.execute(
                select(Match.listing_id).where(Match.user_id == user_id)
            )
        }

        scored: list[tuple] = []
        for listing in listings:
            if listing.id in existing_ids:
                continue
            if not python_filter_pass(user, listing):
                continue
            score, reasons, _ = score_listing_for_user(user, listing)
            if score < cfg.INSERT_THRESHOLD:
                continue
            m = Match(
                user_id=user_id, listing_id=listing.id,
                score=score, reasons=reasons,
                state=MatchState.PENDING,
            )
            s.add(m)
            s.flush()
            scored.append((m, listing, score))

        if not scored:
            return {"ok": True, "matches": 0}

        carries = [
            _WelcomePick(
                id=m.id, score=sc,
                price_uzs=l.price_uzs or 0,
                area=l.area or "",
                is_furnished=l.is_furnished,
                listing_id=l.id,
            )
            for m, l, sc in scored
        ]
        listing_by_id = {l.id: l for _, l, _ in scored}
        match_by_id = {m.id: m for m, _, _ in scored}

        picks = stratified_pick(carries, user, k=5)

        for p in picks:
            match = match_by_id[p.id]
            listing = listing_by_id[p.listing_id]
            send_match_message(user, listing, match, reply_markup=match_actions_kb(match.id))
            match.state = MatchState.SENT
            match.delivered_via = DeliveredVia.WELCOME
            s.add(Event(
                kind="match_sent_welcome",
                user_id=user_id, listing_id=listing.id, match_id=match.id,
            ))

        send_plain_text(user, welcome_batch_closing(len(picks)))
        return {"ok": True, "matches": len(picks)}
