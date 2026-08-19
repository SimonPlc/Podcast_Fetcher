from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import pytest

from podcast_fetcher.articles import article_hash
from podcast_fetcher.config import load_config
from podcast_fetcher.digest import run_digest
from podcast_fetcher.models import Article, ExtractResult, Feed

TODAY = date(2026, 8, 18)
NOW = datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)  # 1 day after the fixture articles' pubDate

FAKE_ENV = {
    "GMAIL_CLIENT_ID": "client-id",
    "GMAIL_CLIENT_SECRET": "client-secret",
    "GMAIL_REFRESH_TOKEN": "refresh-token",
}

ARTICLE_FEED = Feed(
    name="NY Fed Liberty Street Economics",
    url="https://example.com/lse.rss",
    tier="plumbing",
    kind="article",
)
ARTICLE_URL = "https://example.com/article-1"
_LONG_BODY = "Reserves are getting scarce in the repo market. " * 60  # well over the article default threshold


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


def read_seen_articles(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "state" / "seen_articles.json"
    if not path.exists():
        return {"seen": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_seen_articles(tmp_path: Path, seen: dict[str, Any]) -> None:
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "seen_articles.json").write_text(json.dumps({"seen": seen}), encoding="utf-8")


def article_rss(*, link: str = ARTICLE_URL, pub_date: str = "Sun, 17 Aug 2026 09:00:00 GMT", body: str = _LONG_BODY) -> str:
    return f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Feed</title>
<item>
  <title>Reserves Are Getting Scarce</title>
  <link>{link}</link>
  <pubDate>{pub_date}</pubDate>
  <content:encoded><![CDATA[<p>{body}</p>]]></content:encoded>
</item>
</channel></rss>
"""


def fake_fetch(xml_by_url: dict[str, str]) -> Any:
    def _fetch(url: str) -> Any:
        return feedparser.parse(xml_by_url[url])

    return _fetch


def fake_extract_article(score: int = 4, calls: list[Article] | None = None) -> Any:
    def _extract(article: Article, *, claude_model: str | None = None) -> ExtractResult:
        if calls is not None:
            calls.append(article)
        return ExtractResult(
            score=score,
            one_liner=f"one-liner for {article.title}",
            tags=["repo"],
            recap="recap paragraph",
            implications="implications sentence",
            watch=["watch item"],
            terms=["term -- definition"],
            key_claims=["claim one"],
        )

    return _extract


def test_populated_queue_sends_cards_and_clears_queue(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(
        tmp_path,
        {"a1": {"feed_name": "Odd Lots", "title": "Repo Market Update", "url": "https://x/1.mp3", "score": 5}},
    )
    calls: list[dict[str, Any]] = []

    run_digest(config_with_email(), FAKE_ENV, mint_token=fake_mint_token, send=recording_send(calls), today=TODAY)

    assert len(calls) == 1
    assert "2026-08-18" in calls[0]["subject"]
    assert "1 item" in calls[0]["subject"]
    assert "Repo Market Update" in calls[0]["html"]
    assert read_pending(tmp_path) == {"queued": {}}


def test_subject_pluralizes_item_count(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(
        tmp_path,
        {
            "a1": {"feed_name": "Odd Lots", "title": "Ep 1", "url": "https://x/1.mp3", "score": 5},
            "a2": {"feed_name": "Unhedged", "title": "Ep 2", "url": "https://x/2.mp3", "score": 4},
        },
    )
    calls: list[dict[str, Any]] = []

    run_digest(config_with_email(), FAKE_ENV, mint_token=fake_mint_token, send=recording_send(calls), today=TODAY)

    assert "2 items" in calls[0]["subject"]


def test_empty_queue_sends_quiet_day_note(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    run_digest(config_with_email(), FAKE_ENV, mint_token=fake_mint_token, send=recording_send(calls), today=TODAY)

    assert len(calls) == 1
    assert "quiet" in calls[0]["subject"].lower()
    assert "2026-08-18" in calls[0]["subject"]
    assert read_pending(tmp_path) == {"queued": {}}


def test_send_failure_leaves_queue_intact(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {"a1": {"feed_name": "Odd Lots", "title": "Ep", "url": "https://x/1.mp3", "score": 5}})

    with pytest.raises(RuntimeError, match="gmail API is down"):
        run_digest(config_with_email(), FAKE_ENV, mint_token=fake_mint_token, send=failing_send, today=TODAY)

    assert "a1" in read_pending(tmp_path)["queued"]


def test_missing_email_to_raises_before_sending(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    with pytest.raises(RuntimeError, match="EMAIL_TO"):
        run_digest(
            load_config({}),  # no EMAIL_TO/EMAIL_FROM
            FAKE_ENV,
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
            mint_token=fake_mint_token,
            send=recording_send(calls),
            today=TODAY,
        )
    assert calls == []


def test_digest_never_touches_processed_store(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {"a1": {"feed_name": "Odd Lots", "title": "Ep", "url": "https://x/1.mp3", "score": 5}})
    (tmp_path / "state" / "emailed_episodes.json").write_text(
        json.dumps({"processed": {"old": {"status": "ok"}}}), encoding="utf-8"
    )
    before = (tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8")

    run_digest(config_with_email(), FAKE_ENV, mint_token=fake_mint_token, send=recording_send([]), today=TODAY)

    after = (tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8")
    assert before == after


# --- Ticket #7: written articles fetched, scored, and merged in the digest run ---


def test_article_is_fetched_scored_and_merged_into_digest(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
        extract=fake_extract_article(score=4),
        today=TODAY,
        now=NOW,
    )

    assert len(calls) == 1
    assert "1 item" in calls[0]["subject"]
    assert "Reserves Are Getting Scarce" in calls[0]["html"]
    assert ">Read<" in calls[0]["html"]


def test_unified_score_sort_across_podcast_and_article(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(
        tmp_path,
        {"e1": {"feed_name": "Odd Lots", "title": "Low Score Episode", "url": "https://x/1.mp3", "score": 3}},
    )
    calls: list[dict[str, Any]] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
        extract=fake_extract_article(score=5),
        today=TODAY,
        now=NOW,
    )

    html = calls[0]["html"]
    assert html.index("Reserves Are Getting Scarce") < html.index("Low Score Episode")


def test_article_below_min_score_is_excluded_but_marked_seen(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
        extract=fake_extract_article(score=2),  # below default MIN_SCORE (3)
        today=TODAY,
        now=NOW,
    )

    assert "Reserves Are Getting Scarce" not in calls[0]["html"]
    key = article_hash(ARTICLE_FEED.name, ARTICLE_URL)
    assert key in read_seen_articles(tmp_path)["seen"]


def test_already_seen_article_is_not_rescored_or_reincluded(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    key = article_hash(ARTICLE_FEED.name, ARTICLE_URL)
    write_seen_articles(tmp_path, {key: {"feed_name": ARTICLE_FEED.name}})
    calls: list[dict[str, Any]] = []
    extract_calls: list[Article] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
        extract=fake_extract_article(score=5, calls=extract_calls),
        today=TODAY,
        now=NOW,
    )

    assert extract_calls == []
    assert "Reserves Are Getting Scarce" not in calls[0]["html"]


def test_article_feed_fetch_failure_is_non_fatal_podcast_still_sends(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(
        tmp_path,
        {"e1": {"feed_name": "Odd Lots", "title": "Repo Market Update", "url": "https://x/1.mp3", "score": 5}},
    )
    calls: list[dict[str, Any]] = []

    def flaky_fetch(url: str) -> Any:
        raise ConnectionError("404")

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=flaky_fetch,
        extract=fake_extract_article(),
        today=TODAY,
        now=NOW,
    )

    assert len(calls) == 1
    assert "Repo Market Update" in calls[0]["html"]


def test_article_extraction_failure_is_non_fatal_and_not_marked_seen(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(
        tmp_path,
        {"e1": {"feed_name": "Odd Lots", "title": "Repo Market Update", "url": "https://x/1.mp3", "score": 5}},
    )
    calls: list[dict[str, Any]] = []

    def flaky_extract(article: Article, *, claude_model: str | None = None) -> ExtractResult:
        raise RuntimeError("claude CLI blew up")

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
        extract=flaky_extract,
        today=TODAY,
        now=NOW,
    )

    assert len(calls) == 1  # podcast delivery unaffected
    assert "Repo Market Update" in calls[0]["html"]
    key = article_hash(ARTICLE_FEED.name, ARTICLE_URL)
    assert key not in read_seen_articles(tmp_path)["seen"]  # eligible for retry next run


def test_article_hash_committed_only_after_successful_send(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})

    with pytest.raises(RuntimeError, match="gmail API is down"):
        run_digest(
            config_with_email(),
            FAKE_ENV,
            [ARTICLE_FEED],
            mint_token=fake_mint_token,
            send=failing_send,
            fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
            extract=fake_extract_article(score=5),
            today=TODAY,
            now=NOW,
        )

    key = article_hash(ARTICLE_FEED.name, ARTICLE_URL)
    assert key not in read_seen_articles(tmp_path)["seen"]


def test_article_hash_committed_after_successful_send(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
        extract=fake_extract_article(score=5),
        today=TODAY,
        now=NOW,
    )

    key = article_hash(ARTICLE_FEED.name, ARTICLE_URL)
    assert key in read_seen_articles(tmp_path)["seen"]


def test_seen_article_record_never_contains_title_body_or_summary(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_queue(tmp_path, {})
    calls: list[dict[str, Any]] = []

    run_digest(
        config_with_email(),
        FAKE_ENV,
        [ARTICLE_FEED],
        mint_token=fake_mint_token,
        send=recording_send(calls),
        fetch=fake_fetch({ARTICLE_FEED.url: article_rss()}),
        extract=fake_extract_article(score=5),
        today=TODAY,
        now=NOW,
    )

    key = article_hash(ARTICLE_FEED.name, ARTICLE_URL)
    record = read_seen_articles(tmp_path)["seen"][key]
    forbidden = {"title", "body", "recap", "implications", "watch", "terms", "one_liner", "key_claims", "url"}
    assert not (forbidden & record.keys())
    assert record == {"feed_name": ARTICLE_FEED.name}


def test_podcast_only_feeds_are_untouched_by_article_pipeline(tmp_path: Path, monkeypatch: Any) -> None:
    # No article feeds passed at all -- must behave exactly as before ticket #7.
    monkeypatch.chdir(tmp_path)
    write_queue(
        tmp_path,
        {"a1": {"feed_name": "Odd Lots", "title": "Repo Market Update", "url": "https://x/1.mp3", "score": 5}},
    )
    calls: list[dict[str, Any]] = []

    run_digest(config_with_email(), FAKE_ENV, [], mint_token=fake_mint_token, send=recording_send(calls), today=TODAY, now=NOW)

    assert len(calls) == 1
    assert "Repo Market Update" in calls[0]["html"]
    assert not (tmp_path / "state" / "seen_articles.json").exists()
