from apps.workers.celery_app import app


def test_celery_app_configured():
    assert app.main == "scout"
    assert app.conf.timezone == "Asia/Tashkent"
