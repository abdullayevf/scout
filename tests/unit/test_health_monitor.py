from apps.shared.scraping.health import HealthWindow


def test_window_records_outcomes():
    w = HealthWindow(window_seconds=60)
    for _ in range(8):
        w.record(success=True)
    for _ in range(2):
        w.record(success=False)
    assert w.failure_rate() == 0.2


def test_window_should_fallback_when_failure_rate_above_threshold():
    w = HealthWindow(window_seconds=60)
    for _ in range(7):
        w.record(success=False)
    for _ in range(3):
        w.record(success=True)
    assert w.failure_rate() == 0.7
    assert w.should_fallback(threshold=0.2) is True


def test_window_does_not_fallback_with_too_few_samples():
    w = HealthWindow(window_seconds=60, min_samples=5)
    w.record(success=False)
    w.record(success=False)
    assert w.should_fallback(threshold=0.2) is False
