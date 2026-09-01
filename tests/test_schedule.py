from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from podcast_fetcher.schedule import most_recent_due_slot


def utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def test_slot_is_todays_date_once_the_scheduled_time_has_passed() -> None:
    # 2026-08-26 is a Wednesday: a digest day, slot at 22:07 UTC.
    assert most_recent_due_slot(utc(2026, 8, 26, 22, 8)) == date(2026, 8, 26)


def test_slot_is_the_previous_day_before_todays_scheduled_time() -> None:
    assert most_recent_due_slot(utc(2026, 8, 26, 22, 0)) == date(2026, 8, 25)


def test_slot_survives_the_midnight_rollover() -> None:
    """The run that catches a missed Wednesday digest happens on Thursday
    morning UTC, and must still name Wednesday's slot."""
    assert most_recent_due_slot(utc(2026, 8, 27, 0, 25)) == date(2026, 8, 26)


def test_friday_and_saturday_have_no_slot_of_their_own() -> None:
    # cron day-of-week 0-4 is Sun-Thu, so Thursday's is the week's last.
    thursday = date(2026, 8, 27)
    assert most_recent_due_slot(utc(2026, 8, 28, 12, 0)) == thursday  # Friday
    assert most_recent_due_slot(utc(2026, 8, 29, 12, 0)) == thursday  # Saturday
    # Sunday, before 22:07: still Thursday's, not a phantom weekend slot.
    assert most_recent_due_slot(utc(2026, 8, 30, 10, 0)) == thursday
    # Sunday, after 22:07: the new week's first slot.
    assert most_recent_due_slot(utc(2026, 8, 30, 22, 50)) == date(2026, 8, 30)


def test_grace_holds_a_slot_open_so_a_late_digest_is_not_called_missed() -> None:
    just_after = utc(2026, 8, 26, 23, 0)
    assert most_recent_due_slot(just_after) == date(2026, 8, 26)
    # With grace, that same moment still points at the *previous* slot, so
    # a digest running 13 minutes late is not mistaken for a dropped one.
    assert most_recent_due_slot(just_after, grace_minutes=75) == date(2026, 8, 25)
    # Past the grace window, the slot is fair game for a catch-up.
    assert most_recent_due_slot(utc(2026, 8, 27, 0, 5), grace_minutes=75) == date(2026, 8, 26)


def test_grace_clears_the_backup_cron() -> None:
    """The backup fires 60 minutes after the primary (22:07 -> 23:07) and
    needs a few more to install deps and send. The default grace must not
    expire first, or a merely-slow backup would be pre-empted by a catch-up
    brief."""
    backup_still_working = utc(2026, 8, 26, 23, 15)
    assert most_recent_due_slot(backup_still_working, grace_minutes=75) == date(2026, 8, 25)


def test_slot_is_computed_in_utc_whatever_the_input_offset() -> None:
    """22:48 UTC Wednesday is 06:48 Thursday in Hong Kong. The slot is a
    UTC date, so both spellings of that instant must name Wednesday."""
    in_hk = utc(2026, 8, 26, 22, 48).astimezone(timezone(timedelta(hours=8)))
    assert in_hk.date() == date(2026, 8, 27)
    assert most_recent_due_slot(in_hk) == date(2026, 8, 26)
