from __future__ import annotations

import hashlib
import html as html_lib
import re
from collections.abc import Mapping, Sequence, Set as AbstractSet
from datetime import datetime, timedelta
from typing import Any

from podcast_fetcher.ingest import parse_published
from podcast_fetcher.models import Article, Feed

# Full-text feeds default to requiring a substantial body (see feeds.yaml);
# abstract-only research-paper feeds override min_body_chars well below
# this, and that's how we tell the extraction prompt "abstract" vs
# "article" -- see _source_kind below.
DEFAULT_ARTICLE_MIN_BODY_CHARS = 2500
_ABSTRACT_THRESHOLD_CHARS = 1000

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def article_hash(feed_name: str, url: str) -> str:
    """Stable dedup key for an article: a hash of the feed name + url.

    Never the title/body -- SPEC.md deliberately forbids persisting any
    third-party content, only this hash (plus the feed name, which is our
    own config) goes to state/seen_articles.json.
    """
    return hashlib.sha256(f"{feed_name}\n{url}".encode("utf-8")).hexdigest()


def strip_html(raw: str) -> str:
    """Convert an HTML fragment to plain text: drops script/style blocks
    entirely, strips remaining tags, unescapes entities, and collapses
    whitespace. Used both to measure body length against min_body_chars
    and to build the text actually sent to Claude.
    """
    without_blocks = _SCRIPT_STYLE_RE.sub(" ", raw)
    without_tags = _TAG_RE.sub(" ", without_blocks)
    unescaped = html_lib.unescape(without_tags)
    return _WHITESPACE_RE.sub(" ", unescaped).strip()


def parse_article_entries(parsed: Any, feed: Feed) -> list[Article]:
    """Convert a parsed article feed's entries into Articles.

    Body is read from content:encoded / feedparser's entry.content[].value
    first, falling back to summary/description -- full-text RSS only, no
    scraping. Entries whose body (after stripping HTML) is shorter than
    the feed's min_body_chars (or the article default) are skipped: either
    the feed only publishes a teaser, or it's genuinely too short to be
    worth a Claude call. Entries with no usable body or no link are
    skipped outright.
    """
    threshold = feed.min_body_chars if feed.min_body_chars is not None else DEFAULT_ARTICLE_MIN_BODY_CHARS
    source_kind = "abstract" if threshold < _ABSTRACT_THRESHOLD_CHARS else "article"

    articles = []
    for entry in parsed.get("entries", []):
        url = entry.get("link")
        if not url:
            continue
        body = _extract_body(entry)
        if body is None or len(body) < threshold:
            continue
        articles.append(
            Article(
                feed_name=feed.name,
                tier=feed.tier,
                title=entry.get("title", "Untitled article"),
                url=url,
                body=body,
                published=parse_published(entry),
                source_kind=source_kind,
            )
        )
    return articles


def _extract_body(entry: Any) -> str | None:
    content_list = entry.get("content")
    if content_list:
        raw = content_list[0].get("value")
        if raw:
            text = strip_html(raw)
            if text:
                return text

    for key in ("summary", "description"):
        raw = entry.get(key)
        if raw:
            text = strip_html(raw)
            if text:
                return text

    return None


def _sort_key(article: Article) -> tuple[bool, float]:
    """Newest first; articles with no publish date sort after all dated ones."""
    if article.published is None:
        return (True, 0.0)
    return (False, -article.published.timestamp())


def select_articles(
    articles_by_feed: Mapping[str, Sequence[Article]],
    seen_hashes: AbstractSet[str],
    now: datetime,
    *,
    max_recent_days: int,
    max_articles: int,
) -> list[Article]:
    """Pick which articles to extract this digest run.

    Pure function: no I/O. Applies the recency window and dedup against
    already-seen (feed_name, url) hashes, then caps the combined result
    (newest across all feeds first) at max_articles -- articles have no
    per-feed cap, unlike podcast episodes, since there's no expensive
    transcription step to ration.
    """
    cutoff = now - timedelta(days=max_recent_days)

    candidates = [
        article
        for articles in articles_by_feed.values()
        for article in articles
        if article_hash(article.feed_name, article.url) not in seen_hashes
        and (article.published is None or article.published >= cutoff)
    ]
    candidates.sort(key=_sort_key)
    return candidates[:max_articles]
