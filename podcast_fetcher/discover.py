from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

import requests

from podcast_fetcher.config import Config
from podcast_fetcher.gmail import mint_access_token, require_env, send_email
from podcast_fetcher.models import Candidate, Feed
from podcast_fetcher.render import render_discovery
from podcast_fetcher.store import load_seen_candidates, save_seen_candidates

logger = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

# Same reasoning as transcribe.py's _REQUEST_HEADERS: an honest,
# identifying User-Agent, not the default python-requests string.
_REQUEST_HEADERS = {"User-Agent": "Podcast_Fetcher/1.0 (+https://github.com/SimonPlc/Podcast_Fetcher)"}

MintTokenFn = Callable[[str, str, str], str]
SendFn = Callable[..., None]
SearchFn = Callable[[str, int], Any]


def search_itunes(term: str, limit: int, *, timeout: int = 30) -> Any:
    """Query the free, keyless iTunes Search API for podcasts matching
    `term`. The only network I/O in this module.
    """
    response = requests.get(
        ITUNES_SEARCH_URL,
        params={"term": term, "entity": "podcast", "limit": str(limit)},
        headers=_REQUEST_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def parse_itunes_results(raw: Any, term: str) -> list[Candidate]:
    """Convert a raw iTunes Search API response into Candidates. A result
    missing a show name or feed URL (both required to email/dedupe a
    candidate) is skipped rather than raising.
    """
    results = raw.get("results", []) if isinstance(raw, dict) else []
    candidates = []
    for result in results:
        name = result.get("collectionName")
        feed_url = result.get("feedUrl")
        if not name or not feed_url:
            continue
        candidates.append(Candidate(name=name, feed_url=feed_url, term=term))
    return candidates


def normalize_url(url: str) -> str:
    """Normalise a feed URL for dedupe comparison: case-fold, strip
    surrounding whitespace, drop a trailing slash, and collapse an
    http/https difference -- the same show is often listed under either
    scheme in different directories.
    """
    normalized = url.strip().casefold()
    if normalized.startswith("http://"):
        normalized = "https://" + normalized[len("http://") :]
    if normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def normalize_name(name: str) -> str:
    """Normalise a show name for dedupe comparison: case-fold and
    collapse internal whitespace runs down to single spaces.
    """
    return " ".join(name.strip().casefold().split())


def select_new_candidates(
    candidates: Sequence[Candidate],
    existing_feeds: Sequence[Feed],
    seen: Mapping[str, Any],
) -> list[Candidate]:
    """Filter iTunes results down to genuinely new candidates. Pure
    function: no I/O.

    A candidate is excluded if it matches an existing `kind: podcast`
    feed, or a previously-proposed candidate recorded in
    state/discovery_seen.json, by EITHER its normalised feed URL OR its
    normalised name (SPEC.md) -- directory data can list the same show
    under a slightly different URL, or two different shows can
    coincidentally share a URL host, so either signal alone is enough to
    treat it as already known. Article feeds are ignored entirely:
    discovery only ever proposes podcasts (see SPEC.md, "Article-feed
    discovery is out of scope").

    Candidates are also deduped against each other within this same
    batch, since the same show can surface under more than one search
    term in one run.
    """
    existing_urls = {normalize_url(feed.url) for feed in existing_feeds if feed.kind == "podcast"}
    existing_names = {normalize_name(feed.name) for feed in existing_feeds if feed.kind == "podcast"}

    seen_urls = {normalize_url(record["feed_url"]) for record in seen.values()}
    seen_names = {normalize_name(record["name"]) for record in seen.values()}

    excluded_urls = existing_urls | seen_urls
    excluded_names = existing_names | seen_names

    selected: list[Candidate] = []
    batch_urls: set[str] = set()
    batch_names: set[str] = set()
    for candidate in candidates:
        url_key = normalize_url(candidate.feed_url)
        name_key = normalize_name(candidate.name)
        if url_key in excluded_urls or name_key in excluded_names:
            continue
        if url_key in batch_urls or name_key in batch_names:
            continue
        selected.append(candidate)
        batch_urls.add(url_key)
        batch_names.add(name_key)
    return selected


def run_discover(
    feeds: Sequence[Feed],
    discovery_terms: Sequence[str],
    config: Config,
    env: Mapping[str, str],
    *,
    search: SearchFn = search_itunes,
    mint_token: MintTokenFn = mint_access_token,
    send: SendFn = send_email,
    now: datetime | None = None,
) -> None:
    """Query the iTunes Search API for each configured discovery term
    (feeds.yaml's `discovery_terms`), dedupe the results against the
    current feed list and previously-proposed candidates, and email
    whatever is new for manual approval -- or a no-new-candidates note.
    This never adds a feed automatically; see SPEC.md.

    A search term that fails (network error, bad response) is logged and
    skipped so one flaky term never aborts the sweep, mirroring
    collect.py's per-feed handling. New candidates are recorded as
    proposed in state/discovery_seen.json only after the email sends
    successfully, matching digest.py's queue/hash-commit-after-send
    ordering: a failed send must not silently burn that month's
    candidates by marking them seen before Simon ever saw them.
    """
    now = now or datetime.now(tz=timezone.utc)

    seen = load_seen_candidates()

    raw_candidates: list[Candidate] = []
    for term in discovery_terms:
        try:
            raw = search(term, config.discovery_limit)
            raw_candidates.extend(parse_itunes_results(raw, term))
        except Exception:
            logger.exception("discover: search failed for term %r; skipping", term)
            continue

    new_candidates = select_new_candidates(raw_candidates, feeds, seen.get("seen", {}))
    logger.info(
        "discover: %d new candidate(s) found across %d search term(s)", len(new_candidates), len(discovery_terms)
    )

    month_label = now.strftime("%Y-%m")
    if new_candidates:
        count = len(new_candidates)
        subject = f"Podcast Fetcher: {count} new show candidate{'s' if count != 1 else ''} ({month_label})"
    else:
        subject = f"Podcast Fetcher: discovery sweep, no new candidates ({month_label})"

    html, text = render_discovery(new_candidates)

    if not config.email_to or not config.email_from:
        raise RuntimeError("EMAIL_TO and EMAIL_FROM must be set to send the discovery email")

    client_id = require_env(env, "GMAIL_CLIENT_ID")
    client_secret = require_env(env, "GMAIL_CLIENT_SECRET")
    refresh_token = require_env(env, "GMAIL_REFRESH_TOKEN")

    access_token = mint_token(client_id, client_secret, refresh_token)
    send(
        access_token,
        to_addr=config.email_to,
        from_addr=config.email_from,
        subject=subject,
        text=text,
        html=html,
    )
    logger.info("discover: email sent to %s", config.email_to)

    if new_candidates:
        _mark_candidates_seen(new_candidates)


def _mark_candidates_seen(candidates: Sequence[Candidate]) -> None:
    seen = load_seen_candidates()
    records = seen.setdefault("seen", {})
    for candidate in candidates:
        key = normalize_url(candidate.feed_url)
        records[key] = {"name": candidate.name, "feed_url": candidate.feed_url, "term": candidate.term}
    save_seen_candidates(seen)
