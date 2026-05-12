"""Preference update functions applied when a user reacts to a match."""

import numpy as np

from apps.shared.models import Listing, User

ALPHA_LIKE    = 0.15
ALPHA_CONTACT = 0.07
BETA_DISLIKE  = 0.10
BUDGET_TIGHTEN_RATIO = 0.03


def _normalize(v: list[float]) -> list[float]:
    arr = np.array(v, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0.0:
        return v
    return (arr / norm).tolist()


def apply_like(user: User, listing: Listing, alpha: float = ALPHA_LIKE) -> None:
    """pref ← normalize((1-α)·pref + α·listing.embedding) — α controls shift strength."""
    if user.preference_embedding is None or listing.embedding is None:
        return
    pref = np.array(user.preference_embedding, dtype=np.float32)
    emb  = np.array(listing.embedding, dtype=np.float32)
    user.preference_embedding = _normalize(((1 - alpha) * pref + alpha * emb).tolist())


def apply_contact(user: User, listing: Listing) -> None:
    """Like with a smaller alpha — weaker positive signal."""
    apply_like(user, listing, alpha=ALPHA_CONTACT)


def apply_dislike_expensive(user: User, listing: Listing) -> None:
    """Tighten budget_max by 3 % of the gap between listing price and current budget_max."""
    if listing.price_uzs is None or user.budget_max is None:
        return
    gap = max(0, user.budget_max - listing.price_uzs)
    user.budget_max = user.budget_max - int(gap * BUDGET_TIGHTEN_RATIO)


def apply_dislike_area(user: User, listing: Listing) -> None:
    """Add listing's area to negative_area_mask."""
    if listing.area is None:
        return
    mask = list(user.negative_area_mask or [])
    if listing.area not in mask:
        user.negative_area_mask = mask + [listing.area]


def apply_dislike_fishy(user: User, listing: Listing) -> None:
    """Add listing's phone_hash to user.distrust_set."""
    if listing.phone_hash is None:
        return
    ds = list(user.distrust_set or [])
    if listing.phone_hash not in ds:
        user.distrust_set = ds + [listing.phone_hash]


def apply_dislike_seen(user: User, listing_id: int) -> None:
    """Add listing_id to user.seen_set; no embedding update."""
    ss = list(user.seen_set or [])
    if listing_id not in ss:
        user.seen_set = ss + [listing_id]


def apply_dislike_generic(user: User, listing: Listing) -> None:
    """pref ← normalize(α·pref − β·listing.embedding)"""
    if user.preference_embedding is None or listing.embedding is None:
        return
    pref = np.array(user.preference_embedding, dtype=np.float32)
    emb  = np.array(listing.embedding, dtype=np.float32)
    user.preference_embedding = _normalize((ALPHA_LIKE * pref - BETA_DISLIKE * emb).tolist())
