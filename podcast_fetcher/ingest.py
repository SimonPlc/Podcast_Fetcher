from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any

import feedparser

from podcast_fetcher.models import Episode, Feed


def fetch_feed(url: str) -> Any:
    """Fetch and parse an RSS feed. The only network I/O in this module."""
    return feedparser.parse(url)


def parse_entries(parsed: Any, feed: Feed) -> list[Episode]:
    """Convert a parsed feed's entries into Episodes.

    Entries with no downloadable audio enclosure are skipped (nothing to
    transcribe). Entries with a missing or unparseable publish date are
    kept with `published=None` rather than dropped or raising -- the
    recency filter in `selection.py` treats that as "can't verify, don't
    exclude".
    """
    episodes = []
    for entry in parsed.get("entries", []):
        audio_url = _find_audio_url(entry)
        if audio_url is None:
            continue
        guid = entry.get("id") or audio_url
        episodes.append(
            Episode(
                feed_name=feed.name,
                tier=feed.tier,
                title=entry.get("title", "Untitled episode"),
                url=audio_url,
                guid=guid,
                published=parse_published(entry),
            )
        )
    return episodes


def _find_audio_url(entry: Any) -> str | None:
    """Prefer an enclosure whose type is audio/*; fall back to any
    enclosure (some feeds omit or misdeclare the type).
    """
    fallback: str | None = None
    for link in entry.get("links", []):
        if link.get("rel") != "enclosure":
            continue
        href = link.get("href")
        if not href:
            continue
        if str(link.get("type", "")).startswith("audio"):
            return str(href)
        if fallback is None:
            fallback = str(href)
    return fallback


def parse_published(entry: Any) -> datetime | None:
    """Parse a feedparser entry's publish date, shared by episode and
    article ingestion. Returns None (rather than raising) on a missing
    or unparseable date -- the recency filters in selection.py/articles.py
    treat that as "can't verify, don't exclude".
    """
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct is None:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
