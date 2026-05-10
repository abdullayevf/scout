from apps.shared.enrichment.risk import compute_risk


def test_no_flags():
    score, flags = compute_risk(
        price_uzs=8_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=0,
        cross_phash_collision=False,
        agent_keywords_present=False,
        poster_role="owner",
    )
    assert score == 0 and flags == {}


def test_low_price_flag():
    score, flags = compute_risk(
        price_uzs=4_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=0,
        cross_phash_collision=False,
        agent_keywords_present=False,
        poster_role="owner",
    )
    assert flags["unusually_low_price"] is True
    assert score == 1


def test_phash_collision_and_agent_keywords_combine():
    score, flags = compute_risk(
        price_uzs=8_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=5,
        cross_phash_collision=True,
        agent_keywords_present=True,
        poster_role="owner",
    )
    assert flags == {
        "phone_seen_unrelated": True,
        "photo_possibly_reused": True,
        "agent_keywords_with_owner_label": True,
    }
    assert score == 3


def test_phone_unrelated_threshold():
    score, _ = compute_risk(
        price_uzs=8_000_000,
        area_median=8_500_000,
        area_stdev=1_000_000,
        phone_seen_unrelated=2,  # below default threshold of 3
        cross_phash_collision=False,
        agent_keywords_present=False,
        poster_role="owner",
    )
    assert score == 0
