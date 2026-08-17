from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser

from podcast_fetcher.collect import run_collect
from podcast_fetcher.config import load_config
from podcast_fetcher.models import Feed

NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)

FEED_A = Feed(name="Odd Lots", url="https://example.com/oddlots.rss", tier="plumbing")
FEED_B = Feed(name="Unhedged", url="https://example.com/unhedged.rss", tier="credit")


def rss(guid: str, title: str, pub_date: str) -> str:
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Feed</title>
<item>
  <title>{title}</title>
  <guid>{guid}</guid>
  <pubDate>{pub_date}</pubDate>
  <enclosure url="https://example.com/{guid}.mp3" type="audio/mpeg" length="1"/>
</item>
</channel></rss>
"""


RECENT_PUBDATE = "Sun, 16 Aug 2026 09:00:00 GMT"  # 1 day before NOW
OLD_PUBDATE = "Mon, 01 Jun 2026 09:00:00 GMT"  # weeks before NOW


def fake_fetch(feed_xml_by_url: dict[str, str]) -> Any:
    def _fetch(url: str) -> Any:
        return feedparser.parse(feed_xml_by_url[url])

    return _fetch


def test_run_collect_selects_new_recent_episodes(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE),
        FEED_B.url: rss("b1", "Unhedged Ep", RECENT_PUBDATE),
    }
    config = load_config({})
    result = run_collect([FEED_A, FEED_B], config, fetch=fake_fetch(xml_by_url), now=NOW)
    assert {e.guid for e in result} == {"a1", "b1"}


def test_run_collect_excludes_old_episodes(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Old Ep", OLD_PUBDATE)}
    config = load_config({})
    result = run_collect([FEED_A], config, fetch=fake_fetch(xml_by_url), now=NOW)
    assert result == []


def test_run_collect_excludes_already_processed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "emailed_episodes.json").write_text(
        '{"processed": {"a1": {"feed": "Odd Lots", "title": "Old"}}}', encoding="utf-8"
    )
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({})
    result = run_collect([FEED_A], config, fetch=fake_fetch(xml_by_url), now=NOW)
    assert result == []


def test_run_collect_excludes_already_queued(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "pending_digest.json").write_text(
        '{"queued": {"a1": {"feed": "Odd Lots", "title": "Queued"}}}', encoding="utf-8"
    )
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({})
    result = run_collect([FEED_A], config, fetch=fake_fetch(xml_by_url), now=NOW)
    assert result == []


def test_run_collect_survives_one_feed_failing(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    def flaky_fetch(url: str) -> Any:
        if url == FEED_A.url:
            raise ConnectionError("boom")
        return feedparser.parse(rss("b1", "Unhedged Ep", RECENT_PUBDATE))

    config = load_config({})
    result = run_collect([FEED_A, FEED_B], config, fetch=flaky_fetch, now=NOW)
    assert {e.guid for e in result} == {"b1"}


def test_run_collect_with_no_new_episodes_returns_empty_list_and_exits_cleanly(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Old Ep", OLD_PUBDATE)}
    config = load_config({})
    result = run_collect([FEED_A], config, fetch=fake_fetch(xml_by_url), now=NOW)
    assert result == []


def test_run_collect_round_trips_state_files_to_disk(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({})
    run_collect([FEED_A], config, fetch=fake_fetch(xml_by_url), now=NOW)
    assert (tmp_path / "state" / "emailed_episodes.json").exists()
    assert (tmp_path / "state" / "pending_digest.json").exists()


def test_run_collect_preserves_existing_state_contents_on_round_trip(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "emailed_episodes.json").write_text(
        '{"processed": {"old-guid": {"feed": "Odd Lots", "title": "Old"}}}', encoding="utf-8"
    )
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({})
    run_collect([FEED_A], config, fetch=fake_fetch(xml_by_url), now=NOW)

    on_disk = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert on_disk == {"processed": {"old-guid": {"feed": "Odd Lots", "title": "Old"}}}
