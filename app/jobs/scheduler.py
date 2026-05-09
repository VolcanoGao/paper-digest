from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.pipeline.platform_run import run_platform_pipeline

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _platform_job() -> None:
    log.info("APScheduler: starting daily platform run")
    try:
        stats = run_platform_pipeline()
        log.info("Daily platform run finished: %s", stats)
    except Exception:
        log.exception("Daily platform run crashed")


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = AsyncIOScheduler(timezone="UTC")
    # Every day at 03:00 UTC ≈ 11:00 Asia/Shanghai. Adjust as needed.
    sched.add_job(
        _platform_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="platform_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    _scheduler = sched
    log.info("Scheduler started; jobs=%s", [j.id for j in sched.get_jobs()])
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
