from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from podcast_fetcher.config import Config
from podcast_fetcher.gmail import mint_access_token, require_env, send_email
from podcast_fetcher.llm import LLMParseError, parse_json_object, run_claude
from podcast_fetcher.models import Candidate, Feed, ScoredCandidate
from podcast_fetcher.persona import render_with_persona
from podcast_fetcher.render import render_discovery
from podcast_fetcher.store import load_seen_candidates, save_seen_candidates

logger = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

# Same reasoning as transcribe.py's _REQUEST_HEADERS: an honest,
# identifying User-Agent, not the default python-requests string.
_REQUEST_HEADERS = {"User-Agent": "Podcast_Fetcher/1.0 (+https://github.com/SimonPlc/Podcast_Fetcher)"}

SCORE_PROMPT_PATH = "prompts/score_candidates.txt"

MintTokenFn = Callable[[str, str, str], str]
SendFn = Callable[..., None]
SearchFn = Callable[[str, int], Any]
RunClaudeFn = Callable[..., str]
ScoreFn = Callable[..., tuple[list[ScoredCandidate], list[Candidate]]]


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

    `artistName` and `genres` are carried along too (defaulting to
    empty/unknown when absent) -- the only extra material available to
    the ticket #8 show-scoring pass, per SPEC.md/the iTunes Search API's
    documented fields.
    """
    results = raw.get("results", []) if isinstance(raw, dict) else []
    candidates = []
    for result in results:
        name = result.get("collectionName")
        feed_url = result.get("feedUrl")
        if not name or not feed_url:
            continue
        genres = result.get("genres")
        candidates.append(
            Candidate(
                name=name,
                feed_url=feed_url,
                term=term,
                artist_name=result.get("artistName") or "",
                genres=tuple(genres) if isinstance(genres, list) else (),
            )
        )
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


# --- Claude scoring pass (ticket #8) ---
#
# Candidates surviving select_new_candidates are scored in ONE batched
# Claude call (never one call per candidate -- see SPEC.md/issue #8),
# against the same relevance persona prompts/extract.txt uses, factored
# out to prompts/persona.txt (see podcast_fetcher.persona) so the two
# prompts state the priorities once rather than as two copies that can
# drift. The prompt is explicit that it's judging a SHOW (name, artist,
# genres only -- no transcript exists at this stage), and that an
# unrecognised show should score low rather than be guessed at
# generously.


def load_score_prompt(path: str | Path = SCORE_PROMPT_PATH) -> str:
    return Path(path).read_text(encoding="utf-8")


def render_score_prompt(*, prompt: str | None = None) -> str:
    """Fill the show-scoring prompt's {{PERSONA}} placeholder."""
    instructions = prompt if prompt is not None else load_score_prompt()
    return render_with_persona(instructions)


def build_score_stdin(candidates: Sequence[Candidate]) -> str:
    """Serialize the whole batch of surviving candidates to score as one
    JSON array on stdin: an "id" (the candidate's index, used to match
    the response back up), plus the only material available at this
    stage -- name, artist/publisher, and genres. No transcript, no
    description: this is a show-level judgement (SPEC.md/issue #8).
    """
    payload = [
        {
            "id": index,
            "name": candidate.name,
            "artist": candidate.artist_name,
            "genres": list(candidate.genres),
        }
        for index, candidate in enumerate(candidates)
    ]
    return json.dumps(payload)


def parse_score_response(raw: str, expected_count: int) -> dict[int, tuple[int, str]]:
    """Parse and validate a raw Claude response to the batched scoring
    prompt into {id: (score, reason)}. Tolerant about *how* the JSON is
    wrapped (parse_json_object) but strict about the shape of what it
    does contain, mirroring extract.parse_extraction: a malformed entry,
    an out-of-range id, a duplicated id, or a bad score/reason raises
    LLMParseError.

    An *incomplete* reply is deliberately NOT an error. Ids missing from
    an otherwise valid response are simply absent from the returned dict,
    and the caller defers those candidates to the next run. Requiring
    full coverage instead would mean one dropped entry invalidated the
    whole chunk, which at real batch sizes turned a partial success into
    a total failure.
    """
    data = parse_json_object(raw)

    if "scores" not in data or not isinstance(data["scores"], list):
        raise LLMParseError(f"score response missing 'scores' list: {data!r}")

    results: dict[int, tuple[int, str]] = {}
    for entry in data["scores"]:
        if not isinstance(entry, dict):
            raise LLMParseError(f"score entry must be an object: {entry!r}")

        candidate_id = entry.get("id")
        if not isinstance(candidate_id, int) or isinstance(candidate_id, bool):
            raise LLMParseError(f"score entry missing/invalid 'id': {entry!r}")
        if not 0 <= candidate_id < expected_count:
            raise LLMParseError(f"score entry 'id' {candidate_id!r} out of range for {expected_count} candidate(s)")

        score = entry.get("score")
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            raise LLMParseError(f"score entry 'score' must be an integer 1-5: {entry!r}")

        reason = entry.get("reason")
        if not isinstance(reason, str):
            raise LLMParseError(f"score entry missing/invalid 'reason': {entry!r}")

        if candidate_id in results:
            raise LLMParseError(f"score response repeats id {candidate_id}")

        results[candidate_id] = (score, reason)

    return results


def score_candidates(
    candidates: Sequence[Candidate],
    *,
    claude_model: str | None = None,
    prompt: str | None = None,
    run: RunClaudeFn = run_claude,
) -> tuple[list[ScoredCandidate], list[Candidate]]:
    """Score ONE chunk of candidates in a single Claude call, returning
    (scored, missing).

    `missing` holds candidates the model left out of an otherwise valid
    reply; they are deferred rather than guessed at. Raises only when the
    call or the parse failed outright -- score_in_batches turns that into
    a deferral for the whole chunk.
    """
    if not candidates:
        return [], []
    instructions = render_score_prompt(prompt=prompt)
    stdin_text = build_score_stdin(candidates)
    raw = run(instructions, stdin_text, model=claude_model)
    parsed = parse_score_response(raw, len(candidates))

    scored = [
        ScoredCandidate(candidate=candidates[index], score=score, reason=reason)
        for index, (score, reason) in sorted(parsed.items())
    ]
    missing = [candidate for index, candidate in enumerate(candidates) if index not in parsed]
    return scored, missing


def score_in_batches(
    candidates: Sequence[Candidate],
    *,
    batch_size: int,
    claude_model: str | None = None,
    prompt: str | None = None,
    run: RunClaudeFn = run_claude,
) -> tuple[list[ScoredCandidate], list[Candidate]]:
    """Score every candidate in independent chunks, returning
    (scored, deferred).

    Chunking exists because a first sweep produces ~225 surviving
    candidates. Scoring those in one call means ~33k chars of stdin and a
    reply that has to carry a score and a sentence for all 225, which
    invites truncation; and because a chunk is all-or-nothing, one bad
    entry would otherwise discard every good score alongside it.

    A chunk whose call or parse fails is logged and deferred whole. Other
    chunks are unaffected. Deferred candidates are never emailed and never
    marked seen, so they are simply reconsidered next month.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")

    scored: list[ScoredCandidate] = []
    deferred: list[Candidate] = []

    for start in range(0, len(candidates), batch_size):
        chunk = list(candidates[start : start + batch_size])
        try:
            chunk_scored, chunk_missing = score_candidates(
                chunk, claude_model=claude_model, prompt=prompt, run=run
            )
        except Exception:
            logger.exception(
                "discover: scoring failed for chunk of %d candidate(s); deferring them to the next run",
                len(chunk),
            )
            deferred.extend(chunk)
            continue

        scored.extend(chunk_scored)
        if chunk_missing:
            logger.warning(
                "discover: %d candidate(s) missing from an otherwise valid reply; deferring them",
                len(chunk_missing),
            )
            deferred.extend(chunk_missing)

    return scored, deferred


def filter_by_threshold(scored: Sequence[ScoredCandidate], threshold: int) -> list[ScoredCandidate]:
    """Keep only candidates whose Claude score meets the configured
    threshold (SPEC.md/issue #8: defaults to MIN_SCORE). Pure function,
    no I/O -- directly testable without a fake Claude call.
    """
    return [item for item in scored if item.score >= threshold]


def run_discover(
    feeds: Sequence[Feed],
    discovery_terms: Sequence[str],
    config: Config,
    env: Mapping[str, str],
    *,
    search: SearchFn = search_itunes,
    score: ScoreFn = score_in_batches,
    mint_token: MintTokenFn = mint_access_token,
    send: SendFn = send_email,
    now: datetime | None = None,
) -> None:
    """Query the iTunes Search API for each configured discovery term
    (feeds.yaml's `discovery_terms`), dedupe the results against the
    current feed list and previously-proposed candidates, score the
    survivors against the relevance persona in one batched Claude call,
    and email whatever clears the threshold for manual approval -- or a
    no-new-candidates note. This never adds a feed automatically; see
    SPEC.md.

    A search term that fails (network error, bad response) is logged and
    skipped so one flaky term never aborts the sweep, mirroring
    collect.py's per-feed handling. Scoring failures are likewise
    non-fatal but are handled per chunk (see score_in_batches): whatever
    could be scored is used, and the rest is *deferred* to the next run.
    If nothing could be scored at all, the email says exactly that
    instead of dumping the unscored list -- emailing a couple of hundred
    unvetted shows and then suppressing them forever is strictly worse
    than reporting that scoring is broken.

    Candidates are recorded as proposed in state/discovery_seen.json only
    after the email sends successfully, matching digest.py's
    queue/hash-commit-after-send ordering: a failed send must not
    silently burn that month's candidates by marking them seen before
    Simon ever saw them. Only candidates actually emailed are recorded.
    Anything scored below threshold, or deferred, stays unrecorded and so
    remains eligible for a later sweep.
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

    to_email: list[ScoredCandidate] = []
    deferred: list[Candidate] = []
    if new_candidates:
        scored, deferred = score(
            new_candidates,
            batch_size=config.discovery_batch_size,
            claude_model=config.claude_model,
        )
        to_email = filter_by_threshold(scored, config.min_score)
        logger.info(
            "discover: %d of %d candidate(s) cleared the score threshold (>= %d); %d deferred",
            len(to_email),
            len(new_candidates),
            config.min_score,
            len(deferred),
        )

    month_label = now.strftime("%Y-%m")
    if to_email:
        count = len(to_email)
        subject = f"Podcast Fetcher: {count} new show candidate{'s' if count != 1 else ''} ({month_label})"
    elif new_candidates and len(deferred) == len(new_candidates):
        subject = f"Podcast Fetcher: discovery scoring unavailable ({month_label})"
    else:
        subject = f"Podcast Fetcher: discovery sweep, no new candidates ({month_label})"

    html, text = render_discovery(to_email, deferred_count=len(deferred))

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

    if to_email:
        _mark_candidates_seen([item.candidate for item in to_email])


def _mark_candidates_seen(candidates: Sequence[Candidate]) -> None:
    seen = load_seen_candidates()
    records = seen.setdefault("seen", {})
    for candidate in candidates:
        key = normalize_url(candidate.feed_url)
        records[key] = {"name": candidate.name, "feed_url": candidate.feed_url, "term": candidate.term}
    save_seen_candidates(seen)
