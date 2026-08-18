from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    tier: str
    kind: str = "podcast"
    min_body_chars: int | None = None


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
class Article:
    """A single written article, already parsed from a feed entry and
    body-extracted (full-text RSS only -- see feeds.yaml).

    Unlike Episode there is no `guid` field: articles are deliberately
    never persisted (title/body/summary), so the dedup key used by
    articles.py/store.py is a hash of (feed_name, url) computed on
    demand rather than a stored id. `source_kind` tells the extraction
    prompt whether `body` is a full article or a paper abstract, so it
    can calibrate (see extract.render_extract_prompt).
    """

    feed_name: str
    tier: str
    title: str
    url: str
    body: str
    published: datetime | None
    source_kind: str


@dataclass(frozen=True)
class Candidate:
    """A podcast show surfaced by the monthly `discover` sweep (see
    discover.py), from the free iTunes Search API. Unlike Article, this
    data (a show's name and public feed URL) is directory metadata, not
    third-party content, so it's fine to persist -- see
    state/discovery_seen.json.

    `artist_name`/`genres` (ticket #8) carry the iTunes
    `artistName`/`genres` fields -- the only extra material the show-level
    relevance scoring pass has to go on, since there is no transcript at
    this stage. They default empty so any code that only knows about
    name/feed_url/term (e.g. state/discovery_seen.json records, which
    never carried these) keeps working unchanged.
    """

    name: str
    feed_url: str
    term: str
    artist_name: str = ""
    genres: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoredCandidate:
    """A Candidate paired with its Claude relevance score and one-line
    reason from the batched discovery-scoring pass (ticket #8).

    `score`/`reason` are None only along the scoring-failure fallback
    path, where run_discover emails the unscored candidate list rather
    than sending nothing (SPEC.md) -- render.py uses that to label those
    rows "unscored" instead of showing a fabricated score.
    """

    candidate: Candidate
    score: int | None
    reason: str | None


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
