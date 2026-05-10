from celery import Celery

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

# Beat schedule wired progressively in later tasks; placeholder dict for now.
app.conf.beat_schedule = {}
