from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    tier: str


@dataclass(frozen=True)
class Episode:
    """A single podcast episode, already parsed from a feed entry.

    `guid` is the stable dedup key: the feed's entry id when present,
    otherwise the audio enclosure url.
    """

    feed_name: str
    tier: str
    title: str
    url: str
    guid: str
    published: datetime | None


@dataclass(frozen=True)
class ExtractResult:
    """The per-episode Claude extraction: a relevance score plus the
    material the digest synthesis pass will read across all episodes.
    """

    score: int
    one_liner: str
    tags: list[str]
    summary: list[str]
    key_claims: list[str]


@dataclass(frozen=True)
class ThemePoint:
    """One synthesized point within a theme, attributed back to the
    episode guid(s) it was drawn from (resolved to real titles/urls at
    render time -- never trusted from the LLM directly).
    """

    text: str
    source_ids: list[str]


@dataclass(frozen=True)
class Theme:
    name: str
    points: list[ThemePoint]


@dataclass(frozen=True)
class Brief:
    """The cross-episode morning synthesis (SPEC.md: "one synthesized
    brief... organized by theme... noting where sources agree or
    disagree").
    """

    headline: str
    tldr: str
    themes: list[Theme]
    watch: list[str]
    learned: list[str]
