from __future__ import annotations

from collections.abc import Mapping, Sequence, Set as AbstractSet
from datetime import datetime, timedelta

from podcast_fetcher.models import Episode


def _newest_first_key(episode: Episode) -> tuple[bool, float]:
    """Newest first; episodes with no publish date sort after all dated ones.

    Used for the per-feed cap only (issue #9 keeps that half newest-first
    -- a feed's `episodes_per_feed` slots should go to its latest
    releases, not its oldest-still-in-window ones).
    """
    if episode.published is None:
        return (True, 0.0)
    return (False, -episode.published.timestamp())


def _oldest_first_key(episode: Episode) -> tuple[bool, float]:
    """Oldest-in-window first (FIFO); undated episodes still sort last.

    Used for the cross-feed processing order (issue #9): with limited
    per-run capacity and a recency window, newest-first ordering let an
    older-but-in-window episode keep getting bumped by newer arrivals
    across runs until it aged out of the window unprocessed. Working the
    pool oldest-first means an episode nearest the cutoff is always
    processed before it can age out.
    """
    if episode.published is None:
        return (True, 0.0)
    return (False, episode.published.timestamp())


def select_episodes(
    episodes_by_feed: Mapping[str, Sequence[Episode]],
    excluded_ids: AbstractSet[str],
    queued_ids: AbstractSet[str],
    now: datetime,
    *,
    max_recent_days: int,
    episodes_per_feed: int,
    max_episodes_per_run: int,
) -> list[Episode]:
    """Pick which episodes to process this run.

    Pure function: no I/O. Applies, per feed, a recency window and dedup
    against `excluded_ids` (terminal -- ok/failed -- episode ids; a
    caller may also have deferred episodes still under the retry cap,
    which must NOT be included here so they stay eligible) and
    `queued_ids`, keeps the newest `episodes_per_feed` per feed, then
    caps the combined result at `max_episodes_per_run`, taking the
    oldest-in-window episodes first across feeds (issue #9) so episodes
    nearest the `max_recent_days` cutoff are processed before they age
    out.

    Episodes with an unparseable/missing publish date are not excluded by
    the recency window (we can't verify their age) but sort after every
    dated episode in both orderings, so a feed's cap is never "wasted" on
    an undated entry when dated ones are available, and the run cap never
    prefers an undated entry over a dated one nearing its cutoff.
    """
    already_seen = excluded_ids | queued_ids
    cutoff = now - timedelta(days=max_recent_days)

    selected: list[Episode] = []
    for episodes in episodes_by_feed.values():
        candidates = [
            episode
            for episode in episodes
            if episode.guid not in already_seen
            and (episode.published is None or episode.published >= cutoff)
        ]
        candidates.sort(key=_newest_first_key)
        selected.extend(candidates[:episodes_per_feed])

    selected.sort(key=_oldest_first_key)
    return selected[:max_episodes_per_run]
