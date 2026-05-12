"""KPI dashboard queries. All functions accept a SQLAlchemy Session and return scalars."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.shared.enums import MatchState, UserState
from apps.shared.models import Match, User

_REACTED = [MatchState.SENT, MatchState.LIKED, MatchState.DISLIKED,
            MatchState.CONTACTED, MatchState.RENTED]
_LIKED   = [MatchState.LIKED, MatchState.CONTACTED, MatchState.RENTED]
_CONTACTED = [MatchState.CONTACTED, MatchState.RENTED]


def like_rate(session: Session, days: int = 30) -> float:
    """Fraction of matches created in the window that were liked, contacted, or rented.

    Uses match creation date (when the match was sent) as the window boundary,
    not reaction date. This measures recommendation quality for recent matches.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    total = session.execute(
        select(func.count()).select_from(Match)
        .where(Match.created_at >= cutoff, Match.state.in_(_REACTED))
    ).scalar() or 0
    if total == 0:
        return 0.0
    liked = session.execute(
        select(func.count()).select_from(Match)
        .where(Match.created_at >= cutoff, Match.state.in_(_LIKED))
    ).scalar() or 0
    return liked / total


def contact_rate(session: Session, days: int = 30) -> float:
    """Fraction of matches created in the window that resulted in contact or rent.

    Uses match creation date as the window boundary (see like_rate for rationale).
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    total = session.execute(
        select(func.count()).select_from(Match)
        .where(Match.created_at >= cutoff, Match.state.in_(_REACTED))
    ).scalar() or 0
    if total == 0:
        return 0.0
    contacted = session.execute(
        select(func.count()).select_from(Match)
        .where(Match.created_at >= cutoff, Match.state.in_(_CONTACTED))
    ).scalar() or 0
    return contacted / total


def days_to_success(session: Session) -> float | None:
    """Median days from user creation to success_at (users who found an apartment)."""
    rows = session.execute(
        select(User.created_at, User.success_at).where(User.success_at.is_not(None))
    ).all()
    if not rows:
        return None
    deltas = sorted(
        abs((r.success_at - r.created_at).total_seconds()) / 86400 for r in rows
    )
    n = len(deltas)
    mid = n // 2
    return (deltas[mid - 1] + deltas[mid]) / 2 if n % 2 == 0 else deltas[mid]


def mute_rate(session: Session, days: int = 30) -> float:
    """Fraction of ACTIVE users who have not reacted to any match in the window."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    active_total = session.execute(
        select(func.count()).select_from(User).where(User.state == UserState.ACTIVE)
    ).scalar() or 0
    if active_total == 0:
        return 0.0
    reacted = session.execute(
        select(func.count(func.distinct(Match.user_id))).select_from(Match)
        .join(User, User.id == Match.user_id)
        .where(
            User.state == UserState.ACTIVE,
            Match.state.in_([MatchState.LIKED, MatchState.DISLIKED, MatchState.CONTACTED]),
            Match.updated_at >= cutoff,
        )
    ).scalar() or 0
    return (active_total - reacted) / active_total
