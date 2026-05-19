def test_delivered_via_has_welcome():
    from apps.shared.enums import DeliveredVia
    assert DeliveredVia.WELCOME == "welcome"
