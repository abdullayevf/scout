from apps.workers.celery_app import app


def test_celery_app_configured():
    assert app.main == "scout"
    assert app.conf.timezone == "Asia/Tashkent"


def test_welcome_task_registered():
    from apps.workers.celery_app import app
    assert "match.welcome.user" in app.tasks
