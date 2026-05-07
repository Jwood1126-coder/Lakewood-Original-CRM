"""Backfill: fix jobs imported from Jobber that have a wrong scheduled_time.

Bug history (fixed in app/services/jobber_sync.py):
  _parse_iso() stripped the timezone from Jobber's UTC timestamps without
  converting to APP_TIMEZONE first. All-day Jobber jobs (midnight in the
  operator's TZ) arrived as 04:00:00 naive (EDT) or 05:00:00 (EST), and
  every other timed job was off by 4-5 hours in the same direction.

What this script does:
  1. Find every Job with a Jobber stamp ([Jobber job #...]) in notes.
  2. Subtract the UTC-vs-local offset that was active on the job's
     scheduled_date — that recovers the operator-local datetime that Jobber
     actually meant.
  3. If the recovered local time lands on midnight, treat it as "all day"
     and clear scheduled_time. Otherwise store the corrected time.
  4. Print a dry-run report by default; pass --apply to commit.

Usage (from Railway shell or local):
    python -m scripts.fix_jobber_job_times              # dry run
    python -m scripts.fix_jobber_job_times --apply      # commit

Idempotent: re-running on already-corrected jobs is a no-op because we
guard against double-correction via a notes stamp.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timezone

from app import create_app
from app.extensions import db
from app.models.job import Job
from app.utils.timezone import app_tz

ALREADY_FIXED_TAG = "[tz-fix v1]"


def main(apply: bool) -> int:
    app = create_app()
    with app.app_context():
        jobs = (
            db.session.query(Job)
            .filter(Job.scheduled_date.is_not(None))
            .filter(Job.notes.like("%[Jobber job #%"))
            .all()
        )

        candidates = [j for j in jobs if not (j.notes and ALREADY_FIXED_TAG in j.notes)]

        print(f"Found {len(jobs)} Jobber-imported jobs with a date.")
        print(f"  Already fixed: {len(jobs) - len(candidates)}")
        print(f"  To process:    {len(candidates)}")
        print()

        cleared = 0
        shifted = 0
        for j in candidates:
            old_time = j.scheduled_time
            old_date = j.scheduled_date
            if old_time is None:
                # Date-only — nothing to shift.
                j.notes = (j.notes or "") + f"\n{ALREADY_FIXED_TAG}"
                continue

            # Reconstruct the UTC-naive instant that was originally stored, then
            # convert to the operator's TZ to recover what Jobber meant.
            utc_naive = datetime.combine(old_date, old_time)
            aware_utc = utc_naive.replace(tzinfo=timezone.utc)
            local_dt = aware_utc.astimezone(app_tz())

            new_date = local_dt.date()
            new_time = local_dt.time()
            if new_time == time(0, 0):
                new_time = None
                cleared += 1
            else:
                shifted += 1

            print(
                f"  Job #{j.id:>5} {j.title[:40]:<40}  "
                f"{old_date} {old_time}  ->  {new_date} {new_time or 'all day'}"
            )

            j.scheduled_date = new_date
            j.scheduled_time = new_time
            j.notes = (j.notes or "") + f"\n{ALREADY_FIXED_TAG}"

        print()
        print(f"Summary: {shifted} time-shifted, {cleared} cleared to all-day.")
        if not apply:
            print("Dry run — no changes committed. Re-run with --apply to commit.")
            db.session.rollback()
            return 0

        db.session.commit()
        print("Committed.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Commit the corrections (otherwise dry-run).")
    args = parser.parse_args()
    sys.exit(main(apply=args.apply))
