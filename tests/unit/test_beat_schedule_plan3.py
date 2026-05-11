from apps.workers.celery_app import app


def test_digest_send_daily_scheduled():
    sched = app.conf.beat_schedule
    assert "digest-send-daily" in sched
    entry = sched["digest-send-daily"]
    assert entry["task"] == "digest.send.daily"
    assert entry["schedule"].hour == {4}
    assert entry["schedule"].minute == {0}


def test_match_cleanup_dead_scheduled():
    sched = app.conf.beat_schedule
    assert "match-cleanup-dead" in sched
    assert sched["match-cleanup-dead"]["task"] == "match.cleanup.dead"
    entry = sched["match-cleanup-dead"]
    assert entry["schedule"].hour == {4}
    assert entry["schedule"].minute == {45}


def test_match_threshold_recompute_scheduled():
    sched = app.conf.beat_schedule
    assert "match-threshold-recompute" in sched
    assert sched["match-threshold-recompute"]["task"] == "match.threshold.recompute"
    entry = sched["match-threshold-recompute"]
    assert entry["schedule"].hour == {5}
    assert entry["schedule"].minute == {0}
