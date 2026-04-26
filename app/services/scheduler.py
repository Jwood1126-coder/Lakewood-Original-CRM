"""APScheduler integration.

Important: in production with multiple Gunicorn workers, the scheduler runs
in EVERY worker, which would run jobs 2x. We control this with the
RUN_SCHEDULER env var — set it only on one worker (or use --workers 1 for
the scheduler-aware process). For Phase 1 we'll just use one worker.
"""
from __future__ import annotations

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler: BackgroundScheduler | None = None


def init_scheduler(app) -> BackgroundScheduler | None:
    """Start the scheduler if RUN_SCHEDULER=1 (default) and not in TESTING mode.

    Returns the scheduler instance (or None if disabled).
    """
    global _scheduler

    if app.config.get("TESTING"):
        return None
    if os.environ.get("RUN_SCHEDULER", "1") != "1":
        return None
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(
        timezone=app.config.get("APP_TIMEZONE", "America/New_York"),
    )

    def _wrap(fn):
        """Wrap a job so it runs inside an app context and logs failures."""
        def runner():
            with app.app_context():
                try:
                    result = fn()
                    app.logger.info("Job %s OK: %s", fn.__name__, result)
                except Exception as e:
                    app.logger.exception("Job %s failed: %s", fn.__name__, e)
        return runner

    # --- Nightly backup at 03:00 local ---
    from app.services.backup import run_backup
    _scheduler.add_job(
        _wrap(run_backup),
        trigger=CronTrigger(hour=3, minute=0),
        id="nightly_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _scheduler.start()
    app.logger.info("Scheduler started with %d job(s)", len(_scheduler.get_jobs()))

    # Graceful shutdown on app teardown
    import atexit
    atexit.register(lambda: _scheduler and _scheduler.shutdown(wait=False))

    return _scheduler
