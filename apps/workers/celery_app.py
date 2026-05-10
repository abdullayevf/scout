from celery import Celery
from celery.schedules import crontab  # noqa: F401

from apps.shared.config import settings

app = Celery(
    "scout",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "apps.workers.tasks.scrape",
        "apps.workers.tasks.enrich",
        "apps.workers.tasks.recheck",
        "apps.workers.tasks.purge",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Tashkent",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

app.conf.beat_schedule = {
    "scrape-long-term": {
        "task": "scrape.olx.category",
        "schedule": 300,  # 5 min
        "args": ("long_term_apt",),
    },
    "scrape-rooms": {
        "task": "scrape.olx.category",
        "schedule": 300,
        "args": ("rooms",),
    },
    "scrape-looking-for": {
        "task": "scrape.olx.category",
        "schedule": 300,
        "args": ("looking_for",),
    },
    # daily category disabled by default; enable per user demand later
}
