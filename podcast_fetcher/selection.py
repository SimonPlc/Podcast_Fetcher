from __future__ import annotations

from collections.abc import Mapping, Sequence, Set as AbstractSet
from datetime import datetime, timedelta

from podcast_fetcher.models import Episode


def _sort_key(episode: Episode) -> tuple[bool, float]:
    """Newest first; episodes with no publish date sort after all dated ones."""
    if episode.published is None:
        return (True, 0.0)
    return (False, -episode.published.timestamp())


def select_episodes(
    episodes_by_feed: Mapping[str, Sequence[Episode]],
    processed_ids: AbstractSet[str],
    queued_ids: AbstractSet[str],
    now: datetime,
    *,
    max_recent_days: int,
    episodes_per_feed: int,
    max_episodes_per_run: int,
) -> list[Episode]:
    """Pick which episodes to process this run.

    Pure function: no I/O. Applies, per feed, a recency window and dedup
    against already-processed/queued episodes, keeps the newest
    `episodes_per_feed` per feed, then caps the combined result at
    `max_episodes_per_run` (newest across all feeds first).

    Episodes with an unparseable/missing publish date are not excluded by
    the recency window (we can't verify their age) but sort after every
    dated episode, so a feed's cap is never "wasted" on an undated entry
    when dated ones are available.
    """
    already_seen = processed_ids | queued_ids
    cutoff = now - timedelta(days=max_recent_days)

    selected: list[Episode] = []
    for episodes in episodes_by_feed.values():
        candidates = [
            episode
            for episode in episodes
            if episode.guid not in already_seen
            and (episode.published is None or episode.published >= cutoff)
        ]
        candidates.sort(key=_sort_key)
        selected.extend(candidates[:episodes_per_feed])

    selected.sort(key=_sort_key)
    return selected[:max_episodes_per_run]
