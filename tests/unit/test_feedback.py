import math
import pytest
from apps.shared.feedback import (
    ALPHA_CONTACT, ALPHA_LIKE, BETA_DISLIKE, BUDGET_TIGHTEN_RATIO,
    apply_contact, apply_dislike_area, apply_dislike_expensive,
    apply_dislike_fishy, apply_dislike_generic, apply_dislike_seen, apply_like,
)
from apps.shared.models import Listing, User


def _user(**kw) -> User:
    return User(tg_user_id=1, **kw)


def _listing(**kw) -> Listing:
    return Listing(
        source_url="u", source_listing_id="x", source_category="long_term_apt",
        title="t", description_raw="", image_urls=[], image_phashes=[], **kw
    )


def _norm(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


# --- apply_like ---

def test_apply_like_shifts_pref_toward_listing():
    pref = _norm([1.0, 0.0, 0.0])
    emb  = _norm([0.0, 1.0, 0.0])
    u = _user(preference_embedding=pref)
    l = _listing(embedding=emb)
    apply_like(u, l)
    # result should be normalized and between pref and emb
    assert abs(u.preference_embedding[1]) > 0.1  # moved toward emb


def test_apply_like_result_is_unit_vector():
    pref = _norm([1.0, 2.0, 3.0])
    emb  = _norm([3.0, 2.0, 1.0])
    u = _user(preference_embedding=pref)
    l = _listing(embedding=emb)
    apply_like(u, l)
    length = math.sqrt(sum(x * x for x in u.preference_embedding))
    assert abs(length - 1.0) < 1e-5


def test_apply_like_noop_when_no_pref_embedding():
    u = _user(preference_embedding=None)
    l = _listing(embedding=[0.5, 0.5])
    apply_like(u, l)  # should not raise
    assert u.preference_embedding is None


def test_apply_like_noop_when_no_listing_embedding():
    u = _user(preference_embedding=[1.0, 0.0])
    l = _listing(embedding=None)
    apply_like(u, l)
    assert u.preference_embedding == [1.0, 0.0]


def test_apply_contact_uses_smaller_alpha():
    pref = _norm([1.0, 0.0, 0.0])
    emb  = _norm([0.0, 1.0, 0.0])
    u_like    = _user(preference_embedding=list(pref))
    u_contact = _user(preference_embedding=list(pref))
    l = _listing(embedding=emb)
    apply_like(u_like, l)
    apply_contact(u_contact, l)
    # contact alpha < like alpha → contact shifts less toward emb
    assert abs(u_contact.preference_embedding[1]) < abs(u_like.preference_embedding[1])


# --- apply_dislike_expensive ---

def test_apply_dislike_expensive_tightens_budget():
    u = _user(budget_max=3_000_000)
    l = _listing(price_uzs=2_000_000)
    apply_dislike_expensive(u, l)
    gap = 3_000_000 - 2_000_000
    expected = 3_000_000 - int(gap * BUDGET_TIGHTEN_RATIO)
    assert u.budget_max == expected


def test_apply_dislike_expensive_noop_when_no_price():
    u = _user(budget_max=3_000_000)
    l = _listing(price_uzs=None)
    apply_dislike_expensive(u, l)
    assert u.budget_max == 3_000_000


def test_apply_dislike_expensive_noop_when_no_budget_max():
    u = _user(budget_max=None)
    l = _listing(price_uzs=2_000_000)
    apply_dislike_expensive(u, l)
    assert u.budget_max is None


# --- apply_dislike_area ---

def test_apply_dislike_area_adds_to_mask():
    u = _user(negative_area_mask=[])
    l = _listing(area="Yunusabad")
    apply_dislike_area(u, l)
    assert "Yunusabad" in u.negative_area_mask


def test_apply_dislike_area_idempotent():
    u = _user(negative_area_mask=["Yunusabad"])
    l = _listing(area="Yunusabad")
    apply_dislike_area(u, l)
    assert u.negative_area_mask.count("Yunusabad") == 1


# --- apply_dislike_fishy ---

def test_apply_dislike_fishy_adds_phone_hash():
    u = _user(distrust_set=[])
    l = _listing(phone_hash="abc123")
    apply_dislike_fishy(u, l)
    assert "abc123" in u.distrust_set


def test_apply_dislike_fishy_idempotent():
    u = _user(distrust_set=["abc123"])
    l = _listing(phone_hash="abc123")
    apply_dislike_fishy(u, l)
    assert u.distrust_set.count("abc123") == 1


# --- apply_dislike_seen ---

def test_apply_dislike_seen_adds_listing_id():
    u = _user(seen_set=[])
    apply_dislike_seen(u, 42)
    assert 42 in u.seen_set


def test_apply_dislike_seen_idempotent():
    u = _user(seen_set=[42])
    apply_dislike_seen(u, 42)
    assert u.seen_set.count(42) == 1


# --- apply_dislike_generic ---

def test_apply_dislike_generic_moves_away_from_listing():
    pref = _norm([1.0, 0.0, 0.0])
    emb  = _norm([0.0, 1.0, 0.0])
    u = _user(preference_embedding=list(pref))
    l = _listing(embedding=emb)
    apply_dislike_generic(u, l)
    # pref moved away from emb direction → second component should decrease
    assert u.preference_embedding[1] < 0  # actually moved away (negative)
