from __future__ import annotations

from datetime import datetime, timedelta, timezone

from podcast_fetcher.models import Episode
from podcast_fetcher.selection import select_episodes

NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)


def ep(
    feed: str = "Odd Lots",
    tier: str = "plumbing",
    title: str = "Episode",
    guid: str = "guid-1",
    days_ago: float | None = 0,
) -> Episode:
    published = NOW - timedelta(days=days_ago) if days_ago is not None else None
    return Episode(
        feed_name=feed,
        tier=tier,
        title=title,
        url=f"https://example.com/{guid}.mp3",
        guid=guid,
        published=published,
    )


def select(
    episodes_by_feed: dict[str, list[Episode]],
    processed_ids: set[str] | None = None,
    queued_ids: set[str] | None = None,
    max_recent_days: int = 3,
    episodes_per_feed: int = 2,
    max_episodes_per_run: int = 20,
) -> list[Episode]:
    return select_episodes(
        episodes_by_feed,
        processed_ids or set(),
        queued_ids or set(),
        NOW,
        max_recent_days=max_recent_days,
        episodes_per_feed=episodes_per_feed,
        max_episodes_per_run=max_episodes_per_run,
    )


def test_selects_recent_unprocessed_episode() -> None:
    e = ep(guid="a", days_ago=1)
    result = select({"Odd Lots": [e]})
    assert result == [e]


def test_excludes_episode_older_than_recency_window() -> None:
    e = ep(guid="a", days_ago=10)
    result = select({"Odd Lots": [e]}, max_recent_days=3)
    assert result == []


def test_excludes_episode_at_exact_cutoff_boundary_is_included() -> None:
    # published exactly max_recent_days ago should still count as within window
    e = ep(guid="a", days_ago=3)
    result = select({"Odd Lots": [e]}, max_recent_days=3)
    assert result == [e]


def test_excludes_already_processed_episode() -> None:
    e = ep(guid="a", days_ago=1)
    result = select({"Odd Lots": [e]}, processed_ids={"a"})
    assert result == []


def test_excludes_already_queued_episode() -> None:
    e = ep(guid="a", days_ago=1)
    result = select({"Odd Lots": [e]}, queued_ids={"a"})
    assert result == []


def test_per_feed_cap_keeps_newest_first() -> None:
    old = ep(guid="old", days_ago=2)
    newer = ep(guid="newer", days_ago=1)
    newest = ep(guid="newest", days_ago=0)
    result = select({"Odd Lots": [old, newer, newest]}, episodes_per_feed=2)
    assert result == [newest, newer]


def test_per_run_cap_applies_across_feeds() -> None:
    feeds = {
        "Odd Lots": [ep(feed="Odd Lots", guid="a", days_ago=1)],
        "Macro Musings": [ep(feed="Macro Musings", guid="b", days_ago=0.5)],
        "Unhedged": [ep(feed="Unhedged", guid="c", days_ago=0.2)],
    }
    result = select(feeds, max_episodes_per_run=2)
    assert len(result) == 2
    # newest-first across feeds
    assert [e.guid for e in result] == ["c", "b"]


def test_missing_published_date_does_not_crash_and_is_included() -> None:
    e = ep(guid="a", days_ago=None)
    result = select({"Odd Lots": [e]})
    assert result == [e]


def test_missing_published_date_sorts_after_dated_episodes() -> None:
    dated = ep(guid="dated", days_ago=1)
    undated = ep(guid="undated", days_ago=None)
    result = select({"Odd Lots": [undated, dated]}, episodes_per_feed=2)
    assert [e.guid for e in result] == ["dated", "undated"]


def test_multiple_feeds_each_get_their_own_cap() -> None:
    feeds = {
        "Odd Lots": [ep(feed="Odd Lots", guid="a1", days_ago=1), ep(feed="Odd Lots", guid="a2", days_ago=0.5)],
        "Macro Musings": [ep(feed="Macro Musings", guid="b1", days_ago=1)],
    }
    result = select(feeds, episodes_per_feed=2, max_episodes_per_run=20)
    assert {e.guid for e in result} == {"a1", "a2", "b1"}


def test_empty_feeds_returns_empty_list() -> None:
    assert select({}) == []
