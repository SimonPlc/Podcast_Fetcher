from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from podcast_fetcher.config import Config
from podcast_fetcher.extract import extract_episode
from podcast_fetcher.ingest import fetch_feed, parse_entries
from podcast_fetcher.llm import ClaudeUnavailableError, check_claude_available
from podcast_fetcher.models import Episode, ExtractResult, Feed
from podcast_fetcher.selection import select_episodes
from podcast_fetcher.store import (
    load_pending,
    load_processed,
    load_queued_ids,
    save_pending,
    save_processed,
    terminal_ids,
)
from podcast_fetcher.transcribe import downloaded_audio, transcribe_audio

logger = logging.getLogger(__name__)

ExtractFn = Callable[..., ExtractResult]
PreflightFn = Callable[..., None]


def run_collect(
    feeds: list[Feed],
    config: Config,
    *,
    fetch: Callable[[str], Any] = fetch_feed,
    download: Callable[[str], Any] = downloaded_audio,
    transcribe: Callable[[Any, str], str] = transcribe_audio,
    extract: ExtractFn = extract_episode,
    preflight: PreflightFn = check_claude_available,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[Episode]:
    """Fetch every podcast feed, select which new episodes to process,
    then for each: download its audio, transcribe it, run the extraction
    prompt, and record the result. Only episodes scoring >= config.min_score
    are added to the pending digest queue.

    Two different kinds of per-episode failure are told apart (issue #9),
    because only one of them says anything about the episode itself:

    - Episode-side (bad audio, a transcription error, or a malformed-but
      -successful LLM reply -- LLMParseError): recorded `failed`, and so
      excluded from selection forever. The episode really is the
      problem, and every other selected episode is still attempted.
    - Our-side (ClaudeUnavailableError -- the Claude CLI missing/expired
      token, rate-limited, or crashing): recorded `deferred` with an
      incremented attempt counter instead, so it stays eligible for a
      later run rather than being burned by a problem that had nothing
      to do with it. Since this means the CLI is now known-bad, the rest
      of the run is aborted too -- there's no point burning Whisper CPU
      transcribing further episodes a broken CLI can't score either. A
      `preflight` check runs before any transcription starts for the
      same reason, one cheap call up front instead of discovering the
      outage after the first (or several) full download+transcribe
      cycle. Once a deferred episode's attempt count would reach
      config.max_episode_attempts, it is recorded `failed` instead --
      terminal, so a persistently broken CLI doesn't retry the same
      episode forever.

    The run is also bounded in wall-clock time (issue #9): once elapsed
    time (measured via `clock`, monotonic seconds -- NOT `now`, which is
    only for the recency-window logic below) reaches
    config.collect_time_budget_min and at least config.min_episodes_per_run
    episodes have been attempted, no further episodes are started; the
    remainder of `selected` are simply left unrecorded so they stay
    eligible next run. The floor is checked first and always wins: a run
    never does zero work just because a prior run left the clock already
    past budget.

    Article feeds are filtered out here rather than by the caller. They
    are handled entirely by the digest run, and their content must never
    reach the committed state files (SPEC.md). The filter matters even
    though article feeds rarely carry audio: Substack can attach a
    text-to-speech enclosure to any post at any time, and without this
    guard such a post would be transcribed as an episode and its summary
    committed to the public repo.
    """
    now = now or datetime.now(tz=timezone.utc)

    podcast_feeds = [feed for feed in feeds if feed.kind == "podcast"]
    skipped = len(feeds) - len(podcast_feeds)
    if skipped:
        logger.info("collect: ignoring %d article feed(s); those run in the digest", skipped)

    episodes_by_feed: dict[str, list[Episode]] = {}
    for feed in podcast_feeds:
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
        terminal_ids(processed),
        load_queued_ids(),
        now,
        max_recent_days=config.max_recent_days,
        episodes_per_feed=config.episodes_per_feed,
        max_episodes_per_run=config.max_episodes_per_run,
    )
    logger.info("collect: %d episode(s) selected across %d feed(s)", len(selected), len(podcast_feeds))

    try:
        preflight(model=config.claude_model)
    except ClaudeUnavailableError:
        logger.exception("collect: Claude CLI preflight check failed; aborting run without transcribing anything")
        save_processed(processed)
        save_pending(pending)
        return selected

    started = clock()
    attempted = 0
    for episode in selected:
        elapsed_min = (clock() - started) / 60
        if attempted >= config.min_episodes_per_run and elapsed_min >= config.collect_time_budget_min:
            logger.info(
                "collect: time budget (%d min) reached after %d episode(s); deferring the remaining %d to "
                "the next run",
                config.collect_time_budget_min,
                attempted,
                len(selected) - attempted,
            )
            break
        attempted += 1

        try:
            with download(episode.url) as audio_path:
                transcript = transcribe(audio_path, config.whisper_model)
            if len(transcript) > config.max_transcript_chars:
                transcript = transcript[: config.max_transcript_chars]
            result = extract(episode, transcript, claude_model=config.claude_model)
        except ClaudeUnavailableError:
            _defer_episode(episode, processed, config)
            logger.exception(
                "Our-side failure extracting episode [%s] %s (%s); deferring it (not recording as failed) "
                "and aborting the rest of this run -- a now-known-bad CLI can't score the remaining "
                "episodes either",
                episode.feed_name,
                episode.title,
                episode.guid,
            )
            break
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


def _episode_record(
    episode: Episode,
    *,
    status: str,
    extraction: ExtractResult | None = None,
    attempts: int | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "feed_name": episode.feed_name,
        "tier": episode.tier,
        "title": episode.title,
        "url": episode.url,
        "kind": "podcast",
        "published": episode.published.isoformat() if episode.published else None,
        "status": status,
    }
    if attempts is not None:
        record["attempts"] = attempts
    if extraction is not None:
        record.update(
            score=extraction.score,
            one_liner=extraction.one_liner,
            tags=extraction.tags,
            summary=extraction.summary,
            key_claims=extraction.key_claims,
        )
    return record


def _defer_episode(episode: Episode, processed: dict[str, Any], config: Config) -> None:
    """Record an our-side (ClaudeUnavailableError) failure for `episode`,
    mutating `processed` in place. Reads any prior record for this guid
    to carry its attempt count forward; once incrementing it would reach
    config.max_episode_attempts the record is `failed` (terminal)
    instead of `deferred`, so a persistently broken CLI can't retry the
    same episode forever.
    """
    prior_attempts = processed["processed"].get(episode.guid, {}).get("attempts", 0)
    attempts = prior_attempts + 1
    if attempts >= config.max_episode_attempts:
        logger.warning(
            "collect: [%s] %s (%s) hit the retry cap (%d attempts); recording failed, will not be retried again",
            episode.feed_name,
            episode.title,
            episode.guid,
            attempts,
        )
        processed["processed"][episode.guid] = _episode_record(episode, status="failed", attempts=attempts)
    else:
        processed["processed"][episode.guid] = _episode_record(episode, status="deferred", attempts=attempts)
