"""APScheduler integration.

Runs in-process inside the single Gunicorn worker. RUN_SCHEDULER=0 disables
(useful in tests / when running multiple workers later).

Scheduled jobs:
- 03:00 nightly: backup
- Configurable daily briefing (default 06:30) → uses Claude + emails operator
- Sunday 17:00 weekly briefing
- 1st of month 08:00 monthly report
- Hourly: check for "job day reminder" notifications to fire
"""
from __future__ import annotations

import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler: BackgroundScheduler | None = None
_app_ref = None  # Set in init_scheduler so reschedule_recurring_jobs has app context


def _wrap(app, fn):
    """Run a job inside an app context, catch failures."""
    def runner():
        with app.app_context():
            try:
                result = fn()
                app.logger.info("Job %s OK: %s", fn.__name__, result)
            except Exception as e:
                app.logger.exception("Job %s failed: %s", fn.__name__, e)
    runner.__name__ = f"wrapped_{fn.__name__}"
    return runner


def _parse_hhmm(s: str, default=(6, 30)) -> tuple[int, int]:
    try:
        h, m = s.split(":")
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except Exception:
        return default


def init_scheduler(app):
    global _scheduler, _app_ref
    if app.config.get("TESTING"):
        return None
    if os.environ.get("RUN_SCHEDULER", "1") != "1":
        return None
    if _scheduler is not None:
        return _scheduler

    _app_ref = app
    _scheduler = BackgroundScheduler(
        timezone=app.config.get("APP_TIMEZONE", "America/New_York"),
    )

    # Always-on jobs
    from app.services.backup import run_backup
    _scheduler.add_job(
        _wrap(app, run_backup),
        trigger=CronTrigger(hour=3, minute=0),
        id="nightly_backup", replace_existing=True,
        max_instances=1, coalesce=True,
    )

    # Conditional / configurable jobs (briefings, reminders)
    _add_user_configurable_jobs(app)

    _scheduler.start()
    app.logger.info("Scheduler started with %d job(s)", len(_scheduler.get_jobs()))

    import atexit
    atexit.register(lambda: _scheduler and _scheduler.shutdown(wait=False))
    return _scheduler


def _add_user_configurable_jobs(app):
    """Read settings (where available) and (re)schedule briefings/reminders.

    Tolerant of missing tables — if the settings DB isn't ready (fresh
    deploy mid-migration), we fall back to defaults so startup doesn't crash.
    """
    from app.services.briefing import build_and_send_daily_briefing
    from app.services.reminders import tick_reminders

    daily_enabled = True
    daily_h, daily_m = 6, 30
    try:
        from app.models.setting import get_setting
        daily_enabled = get_setting("notify_daily", "1") == "1"
        daily_h, daily_m = _parse_hhmm(get_setting("notify_daily_time", "06:30"))
    except Exception as e:
        app.logger.warning(
            "Settings table not ready; using defaults for cron schedules (%s)", e
        )

    if daily_enabled:
        _scheduler.add_job(
            _wrap(app, build_and_send_daily_briefing),
            trigger=CronTrigger(hour=daily_h, minute=daily_m),
            id="daily_briefing", replace_existing=True,
            max_instances=1, coalesce=True,
        )

    _scheduler.add_job(
        _wrap(app, tick_reminders),
        trigger=CronTrigger(minute=0),  # hourly
        id="reminders_tick", replace_existing=True,
        max_instances=1, coalesce=True,
    )


def reschedule_recurring_jobs():
    """Called when notification settings change. Drops + re-adds the
    configurable jobs so new times take effect without a restart."""
    global _scheduler, _app_ref
    if _scheduler is None or _app_ref is None:
        return
    for jid in ("daily_briefing", "reminders_tick"):
        try:
            _scheduler.remove_job(jid)
        except Exception:
            pass
    _add_user_configurable_jobs(_app_ref)
