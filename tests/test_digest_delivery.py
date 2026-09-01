"""Delivery-slot behaviour: the backup run's double-send guard, and the
catch-up that recovers a digest cron GitHub dropped.

Both hang off state/digest_log.json, so every test here chdirs into
tmp_path -- the store paths are relative, which is what isolates them.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from podcast_fetcher.config import load_config
from podcast_fetcher.digest import maybe_send_missed_digest, run_digest, run_digest_if_due

WEDNESDAY_SLOT = date(2026, 8, 26)
TUESDAY_SLOT = date(2026, 8, 25)

# Wednesday 23:10 UTC: 3 minutes past the 23:07 backup cron and well inside
# the 75-minute grace on the 22:07 primary slot. This is when the backup
# cron is doing its work.
DURING_BACKUP = datetime(2026, 8, 26, 23, 10, tzinfo=timezone.utc)
# Thursday 00:25 UTC: past the grace, so a slot that never delivered is
# now genuinely missed rather than merely late.
AFTER_GRACE = datetime(2026, 8, 27, 0, 25, tzinfo=timezone.utc)

FAKE_ENV = {
    "GMAIL_CLIENT_ID": "client-id",
    "GMAIL_CLIENT_SECRET": "client-secret",
    "GMAIL_REFRESH_TOKEN": "refresh-token",
}


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    return tmp_path


def config() -> Any:
    return load_config({"EMAIL_TO": "simon@example.com", "EMAIL_FROM": "bot@example.com"})


def write_log(state: Path, slot: date | None) -> None:
    payload = {} if slot is None else {"last_slot": slot.isoformat()}
    (state / "state" / "digest_log.json").write_text(json.dumps(payload), encoding="utf-8")


def read_log(state: Path) -> dict[str, Any]:
    path = state / "state" / "digest_log.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_queue(state: Path, count: int) -> None:
    queued = {f"guid-{i}": {"feed_name": "Odd Lots", "score": 4} for i in range(count)}
    (state / "state" / "pending_digest.json").write_text(json.dumps({"queued": queued}), encoding="utf-8")


def recording_run(calls: list[datetime]) -> Any:
    def _run(cfg: Any, env: Any, feeds: Any = (), *, now: datetime, **kwargs: Any) -> None:
        calls.append(now)

    return _run


# --- the backup run must not send a second time -------------------------


def test_backup_run_skips_once_the_primary_has_settled_the_slot(state: Path) -> None:
    """The bug this fixes: the primary sent the real brief and cleared the
    queue, then the backup ran anyway, found nothing queued, and mailed a
    quiet-day note on top of it -- every weekday.
    """
    write_log(state, WEDNESDAY_SLOT)
    calls: list[datetime] = []

    sent = run_digest_if_due(config(), FAKE_ENV, now=DURING_BACKUP, run=recording_run(calls))

    assert sent is False
    assert calls == []


def test_backup_run_still_delivers_when_the_primary_never_did(state: Path) -> None:
    """The backup's actual job. A primary that failed transiently leaves
    the slot unsettled, and the backup must cover it.
    """
    write_log(state, TUESDAY_SLOT)
    calls: list[datetime] = []

    sent = run_digest_if_due(config(), FAKE_ENV, now=DURING_BACKUP, run=recording_run(calls))

    assert sent is True
    assert calls == [DURING_BACKUP]


def test_primary_run_delivers_with_no_log_at_all(state: Path) -> None:
    calls: list[datetime] = []
    assert run_digest_if_due(config(), FAKE_ENV, now=DURING_BACKUP, run=recording_run(calls)) is True
    assert calls == [DURING_BACKUP]


# --- a successful send settles the slot ---------------------------------


def test_successful_digest_records_the_slot_and_the_send_time(state: Path) -> None:
    write_queue(state, 0)
    run_digest(
        config(),
        FAKE_ENV,
        (),
        mint_token=lambda *a: "token",
        send=lambda *a, **k: None,
        preflight=lambda **k: None,
        today=date(2026, 8, 26),
        now=datetime(2026, 8, 26, 22, 48, tzinfo=timezone.utc),
    )

    log = read_log(state)
    assert log["last_slot"] == WEDNESDAY_SLOT.isoformat()
    assert log["last_sent_at"].startswith("2026-08-26T22:48")


def test_a_failed_send_leaves_the_slot_unsettled_so_the_backup_retries(state: Path) -> None:
    write_queue(state, 0)

    def failing_send(*a: Any, **k: Any) -> None:
        raise RuntimeError("gmail API is down")

    with pytest.raises(RuntimeError):
        run_digest(
            config(),
            FAKE_ENV,
            (),
            mint_token=lambda *a: "token",
            send=failing_send,
            preflight=lambda **k: None,
            today=date(2026, 8, 26),
            now=datetime(2026, 8, 26, 22, 48, tzinfo=timezone.utc),
        )

    assert read_log(state) == {}


# --- catching up a slot GitHub dropped ----------------------------------


def test_missed_slot_with_a_queue_sends_the_catch_up(state: Path) -> None:
    """2026-08-26 in miniature: both digest crons dropped, episodes left
    sitting in the queue, and the next collect run notices.
    """
    write_log(state, TUESDAY_SLOT)
    write_queue(state, 2)
    calls: list[datetime] = []

    sent = maybe_send_missed_digest(config(), FAKE_ENV, now=AFTER_GRACE, run=recording_run(calls))

    assert sent is True
    assert calls == [AFTER_GRACE]


def test_missed_slot_with_an_empty_queue_settles_without_emailing(state: Path) -> None:
    """Nothing was owed, so there is nothing to catch up. Settling it
    anyway is the point: otherwise episodes queued later today would look
    like missed content to the next collect run, which would then mail a
    brief in the middle of the afternoon.
    """
    write_log(state, TUESDAY_SLOT)
    write_queue(state, 0)
    calls: list[datetime] = []

    sent = maybe_send_missed_digest(config(), FAKE_ENV, now=AFTER_GRACE, run=recording_run(calls))

    assert sent is False
    assert calls == []
    assert read_log(state)["last_slot"] == WEDNESDAY_SLOT.isoformat()
    assert "last_sent_at" not in read_log(state)


def test_settled_empty_slot_is_not_reopened_by_a_later_collect(state: Path) -> None:
    write_log(state, TUESDAY_SLOT)
    write_queue(state, 0)
    maybe_send_missed_digest(config(), FAKE_ENV, now=AFTER_GRACE, run=recording_run([]))

    # Later the same day a collect run queues two episodes. They belong to
    # tomorrow's brief, not to the slot that was already settled.
    write_queue(state, 2)
    calls: list[datetime] = []
    later = datetime(2026, 8, 27, 4, 30, tzinfo=timezone.utc)

    assert maybe_send_missed_digest(config(), FAKE_ENV, now=later, run=recording_run(calls)) is False
    assert calls == []


def test_no_catch_up_while_the_slot_is_still_within_grace(state: Path) -> None:
    """A collect run overlapping a slow backup must not pre-empt it."""
    write_log(state, TUESDAY_SLOT)
    write_queue(state, 2)
    calls: list[datetime] = []

    sent = maybe_send_missed_digest(config(), FAKE_ENV, now=DURING_BACKUP, run=recording_run(calls))

    assert sent is False
    assert calls == []


def test_no_catch_up_when_the_slot_was_already_delivered(state: Path) -> None:
    write_log(state, WEDNESDAY_SLOT)
    write_queue(state, 2)
    calls: list[datetime] = []

    assert maybe_send_missed_digest(config(), FAKE_ENV, now=AFTER_GRACE, run=recording_run(calls)) is False
    assert calls == []


def test_bootstrap_with_no_log_settles_silently_instead_of_emailing(state: Path) -> None:
    """First run after this shipped. A queue that happens to be non-empty
    is not evidence that a slot was missed, so settle rather than send.
    """
    write_queue(state, 2)
    calls: list[datetime] = []

    sent = maybe_send_missed_digest(config(), FAKE_ENV, now=AFTER_GRACE, run=recording_run(calls))

    assert sent is False
    assert calls == []
    assert read_log(state)["last_slot"] == WEDNESDAY_SLOT.isoformat()


def test_weekend_collect_runs_never_invent_a_catch_up(state: Path) -> None:
    """Thursday is the week's last slot; Friday and Saturday collect runs
    must stay quiet rather than treating the gap as a missed digest.
    """
    write_log(state, date(2026, 8, 27))
    write_queue(state, 3)
    calls: list[datetime] = []

    for moment in (
        datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc),
    ):
        assert maybe_send_missed_digest(config(), FAKE_ENV, now=moment, run=recording_run(calls)) is False
    assert calls == []
