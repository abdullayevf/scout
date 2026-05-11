"""Cold-start detection and stratified digest picker.

A user is in cold-start while they have fewer than COLD_START_REACTIONS
matches in {liked, disliked, contacted}. Plan 3 never writes those
states; Plan 4 will. In the meantime, all users stay in cold-start.
"""

from collections import defaultdict
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.shared.enums import MatchState
from apps.shared.matching.config import COLD_START_REACTIONS
from apps.shared.models import Match


_REACTION_STATES = (MatchState.LIKED, MatchState.DISLIKED, MatchState.CONTACTED)


def is_cold_start(session: Session, user) -> bool:
    count = session.execute(
        select(func.count())
        .select_from(Match)
        .where(Match.user_id == user.id, Match.state.in_(_REACTION_STATES))
    ).scalar_one()
    return count < COLD_START_REACTIONS


def _quartile_buckets(items: Sequence) -> list[list]:
    """Split items into 4 buckets by price_uzs quartile (inclusive lower).

    Returns four lists; some may be empty for small pools.
    """
    if not items:
        return [[], [], [], []]
    sorted_items = sorted(items, key=lambda x: x.price_uzs)
    n = len(sorted_items)
    q1 = n // 4
    q2 = n // 2
    q3 = (3 * n) // 4
    return [
        sorted_items[:q1],
        sorted_items[q1:q2],
        sorted_items[q2:q3],
        sorted_items[q3:],
    ]


def stratified_pick(matches: Sequence, user, k: int = 8) -> list:
    """Pick up to k matches with quartile / area / furnishing diversity.

    Inputs:
      matches: iterable of objects exposing .score, .price_uzs, .area,
               .is_furnished, .id
      user:    must expose .areas (list of strings the user selected)
      k:       max picks (default 8)

    Returns: a list of length min(k, len(matches)).
    """
    if not matches:
        return []
    if len(matches) <= k:
        return sorted(matches, key=lambda m: -m.score)

    buckets = _quartile_buckets(matches)
    per_bucket = max(1, k // 4)

    picks: list = []
    seen_ids: set = set()
    for b in buckets:
        chosen = sorted(b, key=lambda m: -m.score)[:per_bucket]
        for c in chosen:
            if c.id not in seen_ids:
                picks.append(c)
                seen_ids.add(c.id)

    # Top up with overall highest-scored remaining if we're below k.
    remaining = sorted(
        (m for m in matches if m.id not in seen_ids), key=lambda m: -m.score
    )
    while len(picks) < k and remaining:
        c = remaining.pop(0)
        picks.append(c)
        seen_ids.add(c.id)

    picks = picks[:k]

    # Area constraint: ensure ≥3 distinct areas if the user has ≥3 areas.
    user_areas = getattr(user, "areas", []) or []
    if len(user_areas) >= 3:
        picks = _ensure_areas(picks, matches, min_distinct=3, k=k)

    # Furnishing mix: if all picks share furnishing AND alternate exists in pool.
    picks = _ensure_furnishing_mix(picks, matches, k=k)

    return picks


def _ensure_areas(picks: list, pool: Sequence, min_distinct: int, k: int) -> list:
    distinct = {p.area for p in picks}
    if len(distinct) >= min_distinct:
        return picks
    counts: dict[str, int] = defaultdict(int)
    for p in picks:
        counts[p.area] += 1
    in_pool_areas = {m.area for m in pool}
    missing_areas = list(in_pool_areas - distinct)
    if not missing_areas:
        return picks

    pick_ids = {p.id for p in picks}
    for missing in missing_areas:
        if len({p.area for p in picks}) >= min_distinct:
            break
        replacement = max(
            (m for m in pool if m.area == missing and m.id not in pick_ids),
            key=lambda m: m.score,
            default=None,
        )
        if replacement is None:
            continue
        over_area = max(counts, key=lambda a: counts[a])
        victim = min((p for p in picks if p.area == over_area), key=lambda p: p.score)
        picks.remove(victim)
        pick_ids.remove(victim.id)
        counts[over_area] -= 1
        picks.append(replacement)
        pick_ids.add(replacement.id)
        counts[replacement.area] += 1

    return picks[:k]


def _ensure_furnishing_mix(picks: list, pool: Sequence, k: int) -> list:
    furn_values = {p.is_furnished for p in picks if p.is_furnished is not None}
    if len(furn_values) > 1 or not furn_values:
        return picks
    current = next(iter(furn_values))
    alternate_pool = [
        m for m in pool if m.is_furnished is not None and m.is_furnished != current
    ]
    if not alternate_pool:
        return picks
    replacement = max(alternate_pool, key=lambda m: m.score)
    if replacement in picks:
        return picks
    victim = min(picks, key=lambda p: p.score)
    picks.remove(victim)
    picks.append(replacement)
    return picks[:k]
