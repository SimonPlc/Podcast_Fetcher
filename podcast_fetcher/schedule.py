from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

# The digest's scheduled slot, in UTC, mirroring the two digest crons in
# .github/workflows/pipeline.yml. Kept as one primary time rather than one
# entry per cron because the backup run is not a second digest -- it is a
# retry of the same logical slot, and the missed-digest logic reasons about
# slots, not about which cron happened to fire.
#
# 22:07 UTC = 06:07 HK. Deliberately off the hour and off the half hour:
# GitHub delays scheduled workflows under load and drops them outright when
# the delay runs past the next window, and :00/:30 are the most congested
# minutes there are. This is the same reasoning already applied to the
# collect crons; the digest slot was left on :00 and got dropped on
# 2026-08-26, taking the backup at :30 down with it. Pulled 40 min earlier
# than the original 22:47 so GitHub's scheduling drift lands the brief
# before the morning read rather than mid-morning.
DIGEST_TIME_UTC = time(22, 7)

# Python's date.weekday(): Mon=0 ... Sun=6. Cron's day-of-week 0-4 is
# Sun-Thu, which is Sun,Mon,Tue,Wed,Thu = {6, 0, 1, 2, 3}. Sun-Thu at
# 22:07 UTC is Mon-Fri at 06:07 HK; Sunday's run sweeps the weekend.
DIGEST_WEEKDAYS = frozenset({6, 0, 1, 2, 3})

# How far back to walk looking for the last scheduled slot. The longest
# gap between digests is Thu -> Sun (Fri and Sat have none), so three days
# would do; eight leaves room to change the schedule without silently
# breaking the search.
_MAX_LOOKBACK_DAYS = 8


def most_recent_due_slot(now: datetime, grace_minutes: int = 0) -> date | None:
    """The UTC date of the latest scheduled digest whose send window has
    fully passed, or None if no digest has ever been due.

    A "slot" is a date rather than a timestamp on purpose: the primary and
    backup crons are two attempts at one day's brief, so both settle the
    same slot, and moving either cron's minute cannot desynchronise the
    stored history from the code.

    `grace_minutes` holds a slot open past its scheduled time so a digest
    that is merely running late is not mistaken for one that was dropped.
    """
    cutoff = now.astimezone(timezone.utc) - timedelta(minutes=grace_minutes)
    day = cutoff.date()
    for _ in range(_MAX_LOOKBACK_DAYS):
        if day.weekday() in DIGEST_WEEKDAYS:
            slot_at = datetime.combine(day, DIGEST_TIME_UTC, tzinfo=timezone.utc)
            if slot_at <= cutoff:
                return day
        day -= timedelta(days=1)
    return None
