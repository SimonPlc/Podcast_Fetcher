from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from podcast_fetcher.config import load_config
from podcast_fetcher.digest import run_digest
from podcast_fetcher.models import Brief, Theme, ThemePoint

TODAY = date(2026, 8, 18)

FAKE_ENV = {
    "GMAIL_CLIENT_ID": "client-id",
    "GMAIL_CLIENT_SECRET": "client-secret",
    "GMAIL_REFRESH_TOKEN": "refresh-token",
}


def fake_synthesize(pending: dict[str, Any], *, claude_model: str | None = None) -> Brief:
    return Brief(
        headline="Test headline",
        tldr="Test tldr",
        themes=[Theme(name="Repo", points=[ThemePoint(text="point", source_ids=[])])],
        watch=[],
        learned=[],
    )


def fake_mint_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    return "fake-access-token"


def recording_send(calls: list[dict[str, Any]]) -> Any:
    def _send(access_token: str, **kwargs: Any) -> None:
        calls.append({"access_token": access_token, **kwargs})

    return _send


def failing_send(access_token: str, **kwargs: Any) -> None:
    raise RuntimeError("gmail API is down")


def config_with_email() -> Any:
    return load_config({"EMAIL_TO": "simon@example.com", "EMAIL_FROM": "bot@example.com"})


def write_queue(tmp_path: Path, queued: dict[str, Any]) -> None:
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "pending_digest.json").write_text(json.dumps({"queued": queued}), encoding="utf-8")


def read_pending(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "state" / "pending_digest.json").read_text(encoding="utf-8"))


def test_populated_queue_sends_brief_and_clears_queue(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {"a1": {"feed_name": "Odd Lots", "title": "Ep", "url": "https://x/1.mp3"}})
    calls: list[dict[str, Any]] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        synthesize=fake_synthesize,
        mint_token=fake_mint_token,
        send=recording_send(calls),
        today=TODAY,
    )

    assert len(calls) == 1
    assert calls[0]["subject"] == "Test headline"
    assert "Test headline" in calls[0]["html"]
    assert read_pending(tmp_path) == {"queued": {}}


def test_empty_queue_sends_quiet_day_note(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        synthesize=fake_synthesize,
        mint_token=fake_mint_token,
        send=recording_send(calls),
        today=TODAY,
    )

    assert len(calls) == 1
    assert "quiet" in calls[0]["subject"].lower()
    assert "2026-08-18" in calls[0]["subject"]
    assert read_pending(tmp_path) == {"queued": {}}


def test_send_failure_leaves_queue_intact(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {"a1": {"feed_name": "Odd Lots", "title": "Ep", "url": "https://x/1.mp3"}})

    with pytest.raises(RuntimeError, match="gmail API is down"):
        run_digest(
            config_with_email(),
            FAKE_ENV,
            synthesize=fake_synthesize,
            mint_token=fake_mint_token,
            send=failing_send,
            today=TODAY,
        )

    assert "a1" in read_pending(tmp_path)["queued"]


def test_missing_email_to_raises_before_sending(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    with pytest.raises(RuntimeError, match="EMAIL_TO"):
        run_digest(
            load_config({}),  # no EMAIL_TO/EMAIL_FROM
            FAKE_ENV,
            synthesize=fake_synthesize,
            mint_token=fake_mint_token,
            send=recording_send(calls),
            today=TODAY,
        )
    assert calls == []


def test_missing_gmail_secret_raises_before_sending(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []
    incomplete_env = {"GMAIL_CLIENT_ID": "x"}  # missing secret + refresh token

    with pytest.raises(RuntimeError, match="GMAIL_CLIENT_SECRET"):
        run_digest(
            config_with_email(),
            incomplete_env,
            synthesize=fake_synthesize,
            mint_token=fake_mint_token,
            send=recording_send(calls),
            today=TODAY,
        )
    assert calls == []


def test_digest_never_touches_processed_store(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {"a1": {"feed_name": "Odd Lots", "title": "Ep", "url": "https://x/1.mp3"}})
    (tmp_path / "state" / "emailed_episodes.json").write_text(
        json.dumps({"processed": {"old": {"status": "ok"}}}), encoding="utf-8"
    )
    before = (tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8")

    run_digest(
        config_with_email(),
        FAKE_ENV,
        synthesize=fake_synthesize,
        mint_token=fake_mint_token,
        send=recording_send([]),
        today=TODAY,
    )

    after = (tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8")
    assert before == after
