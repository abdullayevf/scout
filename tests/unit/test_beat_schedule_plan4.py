from apps.workers.celery_app import app


def test_kpi_chase_48h_in_schedule():
    assert "kpi-chase-48h" in app.conf.beat_schedule


def test_kpi_chase_5d_in_schedule():
    assert "kpi-chase-5d" in app.conf.beat_schedule


def test_kpi_weekly_checkin_in_schedule():
    entry = app.conf.beat_schedule.get("kpi-weekly-checkin")
    assert entry is not None
    assert entry["task"] == "kpi.weekly.checkin.send"


def test_kpi_purge_inactive_in_schedule():
    assert "kpi-maintenance-purge-inactive" in app.conf.beat_schedule
