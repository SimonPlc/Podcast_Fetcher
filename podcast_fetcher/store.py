from __future__ import annotations

from pathlib import Path

from podcast_fetcher.state import read_json, write_json_atomic

PROCESSED_PATH = "state/emailed_episodes.json"
PENDING_PATH = "state/pending_digest.json"
SEEN_ARTICLES_PATH = "state/seen_articles.json"
DISCOVERY_SEEN_PATH = "state/discovery_seen.json"


def load_processed(path: str | Path = PROCESSED_PATH) -> dict:
    return read_json(path, default={"processed": {}})


def load_processed_ids(path: str | Path = PROCESSED_PATH) -> set[str]:
    return set(load_processed(path).get("processed", {}).keys())


# Terminal statuses (issue #9): a record in either state is permanently
# excluded from selection and never retried. `deferred` (an our-side
# ClaudeUnavailableError, still under the retry cap) is deliberately
# NOT terminal -- see terminal_ids below and collect.run_collect.
_TERMINAL_STATUSES = {"ok", "failed"}


def terminal_ids(processed: dict) -> set[str]:
    """The subset of an already-loaded `processed` record whose episode
    is terminal (status ok or failed). Pure: takes the dict collect.py
    already has in hand rather than re-reading it from disk, and keeps
    the ok/failed/deferred status vocabulary out of selection.py, which
    only ever sees a plain set of ids to exclude.
    """
    return {
        guid
        for guid, record in processed.get("processed", {}).items()
        if record.get("status") in _TERMINAL_STATUSES
    }


def save_processed(processed: dict, path: str | Path = PROCESSED_PATH) -> None:
    write_json_atomic(path, processed)


def load_pending(path: str | Path = PENDING_PATH) -> dict:
    return read_json(path, default={"queued": {}})


def load_queued_ids(path: str | Path = PENDING_PATH) -> set[str]:
    return set(load_pending(path).get("queued", {}).keys())


def save_pending(pending: dict, path: str | Path = PENDING_PATH) -> None:
    write_json_atomic(path, pending)


def load_seen_articles(path: str | Path = SEEN_ARTICLES_PATH) -> dict:
    """The article dedup record. Per SPEC.md, a record holds only the
    article's (feed_name, url) hash as its key plus the feed_name (our own
    config, safe to store) for debuggability -- never a title, body, or
    summary.
    """
    return read_json(path, default={"seen": {}})


def load_seen_article_hashes(path: str | Path = SEEN_ARTICLES_PATH) -> set[str]:
    return set(load_seen_articles(path).get("seen", {}).keys())


def save_seen_articles(seen: dict, path: str | Path = SEEN_ARTICLES_PATH) -> None:
    write_json_atomic(path, seen)


def load_seen_candidates(path: str | Path = DISCOVERY_SEEN_PATH) -> dict:
    """The discovery dedup record: podcast candidates already proposed by
    a prior monthly sweep, keyed by normalised feed URL, so the same show
    is never re-proposed after Simon has seen (and implicitly declined,
    by not adding it) it once. Unlike state/seen_articles.json, a show's
    name and public feed URL are directory metadata, not third-party
    content, so persisting them in full is fine (see SPEC.md).
    """
    return read_json(path, default={"seen": {}})


def save_seen_candidates(seen: dict, path: str | Path = DISCOVERY_SEEN_PATH) -> None:
    write_json_atomic(path, seen)
