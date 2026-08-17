from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from podcast_fetcher.config import Config
from podcast_fetcher.ingest import fetch_feed, parse_entries
from podcast_fetcher.models import Episode, Feed
from podcast_fetcher.selection import select_episodes
from podcast_fetcher.store import (
    load_pending,
    load_processed,
    load_queued_ids,
    save_pending,
    save_processed,
)

logger = logging.getLogger(__name__)


def run_collect(
    feeds: list[Feed],
    config: Config,
    *,
    fetch: Callable[[str], Any] = fetch_feed,
    now: datetime | None = None,
) -> list[Episode]:
    """Fetch every feed, then select which new episodes this run should
    process. Ticket #1 scope: selection only, no download/transcription/
    scoring (that lands in the next ticket) -- but the state files are
    still read and written back on every run, so the atomic read/write
    path is exercised end to end rather than only by its own unit test.
    """
    now = now or datetime.now(tz=timezone.utc)

    episodes_by_feed: dict[str, list[Episode]] = {}
    for feed in feeds:
        try:
            parsed = fetch(feed.url)
            episodes_by_feed[feed.name] = parse_entries(parsed, feed)
        except Exception:
            logger.exception("Failed to fetch/parse feed %s (%s); skipping", feed.name, feed.url)
            episodes_by_feed[feed.name] = []

    processed = load_processed()
    pending = load_pending()

    selected = select_episodes(
        episodes_by_feed,
        set(processed.get("processed", {}).keys()),
        load_queued_ids(),
        now,
        max_recent_days=config.max_recent_days,
        episodes_per_feed=config.episodes_per_feed,
        max_episodes_per_run=config.max_episodes_per_run,
    )

    for episode in selected:
        logger.info("selected: [%s] %s (%s)", episode.feed_name, episode.title, episode.guid)
    logger.info("collect: %d episode(s) selected across %d feed(s)", len(selected), len(feeds))

    # Round-trip state on every run (even with nothing new to record yet):
    # proves the atomic write path is actually wired into collect, not
    # just exercised in isolation by test_state.py. Transcription/scoring
    # (which will add real entries here) lands in the next ticket.
    save_processed(processed)
    save_pending(pending)

    return selected
