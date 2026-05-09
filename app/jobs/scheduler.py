from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.jobs.send_digests import run_digest_sweep
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


async def _digest_sweep_job() -> None:
    try:
        results = await run_digest_sweep()
        sent = sum(1 for r in results if r.get("status") == "sent")
        if sent:
            log.info("Digest sweep: %d sent (of %d active subs)", sent, len(results))
    except Exception:
        log.exception("Digest sweep crashed")


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = AsyncIOScheduler(timezone="UTC")
    # Daily ingest+evaluate at 03:00 UTC ≈ 11:00 Asia/Shanghai.
    sched.add_job(
        _platform_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="platform_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Per-minute digest sweep. Each subscription decides whether to fire based
    # on user's local time + last_sent_on; sweep itself is cheap (1 SELECT).
    sched.add_job(
        _digest_sweep_job,
        trigger=IntervalTrigger(minutes=1),
        id="digest_sweep",
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
