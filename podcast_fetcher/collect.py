from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from podcast_fetcher.config import Config
from podcast_fetcher.extract import extract_episode
from podcast_fetcher.ingest import fetch_feed, parse_entries
from podcast_fetcher.models import Episode, ExtractResult, Feed
from podcast_fetcher.selection import select_episodes
from podcast_fetcher.store import (
    load_pending,
    load_processed,
    load_queued_ids,
    save_pending,
    save_processed,
)
from podcast_fetcher.transcribe import downloaded_audio, transcribe_audio

logger = logging.getLogger(__name__)

ExtractFn = Callable[..., ExtractResult]


def run_collect(
    feeds: list[Feed],
    config: Config,
    *,
    fetch: Callable[[str], Any] = fetch_feed,
    download: Callable[[str], Any] = downloaded_audio,
    transcribe: Callable[[Any, str], str] = transcribe_audio,
    extract: ExtractFn = extract_episode,
    now: datetime | None = None,
) -> list[Episode]:
    """Fetch every feed, select which new episodes to process, then for
    each: download its audio, transcribe it, run the extraction prompt,
    and record the result. Every attempted episode is recorded in the
    processed/dedup store (so it's never retried); only episodes scoring
    >= config.min_score are also added to the pending digest queue. A
    single episode's failure (bad audio, transcription error, malformed
    LLM output) is logged and recorded as failed -- it does not abort
    the run for the other episodes, nor fail to persist state.
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
    logger.info("collect: %d episode(s) selected across %d feed(s)", len(selected), len(feeds))

    for episode in selected:
        try:
            with download(episode.url) as audio_path:
                transcript = transcribe(audio_path, config.whisper_model)
            if len(transcript) > config.max_transcript_chars:
                transcript = transcript[: config.max_transcript_chars]
            result = extract(episode, transcript, claude_model=config.claude_model)
        except Exception:
            logger.exception(
                "Failed to process episode [%s] %s (%s); recording as failed, not queued",
                episode.feed_name,
                episode.title,
                episode.guid,
            )
            processed["processed"][episode.guid] = _episode_record(episode, status="failed")
            continue

        queued = result.score >= config.min_score
        record = _episode_record(episode, status="ok", extraction=result)
        processed["processed"][episode.guid] = record
        if queued:
            pending["queued"][episode.guid] = record
        logger.info(
            "processed: [%s] %s score=%d queued=%s",
            episode.feed_name,
            episode.title,
            result.score,
            queued,
        )

    # State is written back on every run, even with nothing new (e.g. all
    # episodes filtered out), so the atomic write path is always
    # exercised end to end rather than only reachable when there's new
    # data to record.
    save_processed(processed)
    save_pending(pending)

    return selected


def _episode_record(episode: Episode, *, status: str, extraction: ExtractResult | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "feed_name": episode.feed_name,
        "tier": episode.tier,
        "title": episode.title,
        "url": episode.url,
        "published": episode.published.isoformat() if episode.published else None,
        "status": status,
    }
    if extraction is not None:
        record.update(
            score=extraction.score,
            one_liner=extraction.one_liner,
            tags=extraction.tags,
            summary=extraction.summary,
            key_claims=extraction.key_claims,
        )
    return record
