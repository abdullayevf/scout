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
        "apps.workers.tasks.match",
        "apps.workers.tasks.digest",
        "apps.workers.tasks.kpi",
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

app.conf.beat_schedule.update({
    "digest-send-daily": {
        "task": "digest.send.daily",
        "schedule": crontab(hour=4, minute=0),  # 04:00 UTC = 09:00 Tashkent
    },
    "match-cleanup-dead": {
        "task": "match.cleanup.dead",
        "schedule": crontab(hour=4, minute=45),
    },
    "match-threshold-recompute": {
        "task": "match.threshold.recompute",
        "schedule": crontab(hour=5, minute=0),
    },
})

app.conf.beat_schedule.update({
    "kpi-chase-48h": {
        "task": "kpi.chase.48h.run",
        "schedule": 600,  # every 10 min
    },
    "kpi-chase-5d": {
        "task": "kpi.chase.5d.run",
        "schedule": 600,
    },
    "kpi-weekly-checkin": {
        "task": "kpi.weekly.checkin.send",
        "schedule": crontab(hour=13, minute=0, day_of_week=0),  # Sunday 13:00 UTC = 18:00 Tashkent
    },
    "kpi-maintenance-purge-inactive": {
        "task": "kpi.maintenance.purge_inactive",
        "schedule": crontab(hour=2, minute=0),  # daily 02:00 UTC
    },
})
