from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from podcast_fetcher.config import Config
from podcast_fetcher.ingest import fetch_feed, parse_entries
from podcast_fetcher.models import Episode, Feed
from podcast_fetcher.selection import select_episodes
from podcast_fetcher.store import load_pending, load_processed_ids

logger = logging.getLogger(__name__)


def run_collect(
    feeds: list[Feed],
    config: Config,
    *,
    fetch: Callable[[str], Any] = fetch_feed,
    now: datetime | None = None,
) -> list[Episode]:
    """Fetch every feed, then select which new episodes this run should
    process. Ticket #1 scope: selection only, no download/transcription
    (that lands in the next ticket) -- this proves the ingestion +
    dedup + state round-trip end to end.
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

    processed_ids = load_processed_ids()
    pending = load_pending()
    queued_ids = set(pending.get("queued", {}).keys())

    selected = select_episodes(
        episodes_by_feed,
        processed_ids,
        queued_ids,
        now,
        max_recent_days=config.max_recent_days,
        episodes_per_feed=config.episodes_per_feed,
        max_episodes_per_run=config.max_episodes_per_run,
    )

    for episode in selected:
        logger.info("selected: [%s] %s (%s)", episode.feed_name, episode.title, episode.guid)
    logger.info("collect: %d episode(s) selected across %d feed(s)", len(selected), len(feeds))

    return selected
