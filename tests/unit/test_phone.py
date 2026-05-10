from apps.shared.phone import hash_phone, normalize_phone


def test_normalize_uz_phone_variants():
    assert normalize_phone("+998 90 123 45 67") == "998901234567"
    assert normalize_phone("90-123-45-67") == "998901234567"
    assert normalize_phone("(90) 123 45 67") == "998901234567"
    assert normalize_phone("998901234567") == "998901234567"
    assert normalize_phone("8 90 123 45 67") == "998901234567"


def test_normalize_returns_none_on_garbage():
    assert normalize_phone("") is None
    assert normalize_phone("call me") is None
    assert normalize_phone("123") is None  # too short


def test_hash_phone_is_stable_and_hex():
    assert hash_phone("998901234567") == hash_phone("998901234567")
    h = hash_phone("998901234567")
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)
