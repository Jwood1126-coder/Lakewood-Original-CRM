"""Timezone helpers.

Storage convention: every stored datetime is UTC-naive (datetime.utcnow()).
Display + "today"-semantics convention: convert to APP_TIMEZONE for the
operator's wall-clock view. Never mix.

The bug we fix: the scheduler runs cron jobs in APP_TIMEZONE
(America/New_York), but routes calling `date.today()` get the *server's*
local date (UTC on Railway). Around midnight Eastern, that disagrees by
4–5 hours, which made `_already_sent_today` either falsely re-fire
notifications or falsely block them.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app


def app_tz() -> ZoneInfo:
    """The operator's local time zone (from APP_TIMEZONE env)."""
    try:
        name = current_app.config.get("APP_TIMEZONE", "America/New_York")
    except RuntimeError:
        # Outside an app context (e.g. tests, scheduler init) — fall back
        name = "America/New_York"
    return ZoneInfo(name)


def now_local() -> datetime:
    """Current wall-clock time in the operator's TZ (TZ-aware)."""
    return datetime.now(app_tz())


def today_local() -> date:
    """Today, per the operator's local TZ — what the operator considers 'today'.

    Use this anywhere the user-visible "today" matters: dashboard tiles,
    overdue checks, daily-briefing assembly, reminder dedup, A/R aging.
    """
    return now_local().date()


def utc_to_local(dt: datetime) -> datetime:
    """Convert a UTC-naive (or UTC-aware) datetime to operator's local TZ."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(app_tz())
