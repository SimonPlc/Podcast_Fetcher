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
    material rendered into that episode's digest card.
    """

    score: int
    one_liner: str
    tags: list[str]
    summary: list[str]
    key_claims: list[str]
