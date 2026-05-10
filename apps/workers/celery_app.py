from celery import Celery
from celery.schedules import crontab

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

app.conf.beat_schedule.update({
    "enrich-pending": {
        "task": "enrich.listings.pending",
        "schedule": 60,  # every minute
        "args": (),
    },
    "recheck-active": {
        "task": "recheck.listings.active",
        "schedule": crontab(hour=3, minute=0),  # daily 03:00 UTC
    },
    "purge-dead-bodies": {
        "task": "purge.listings.dead",
        "schedule": crontab(hour=4, minute=30),  # daily 04:30 UTC
    },
})
