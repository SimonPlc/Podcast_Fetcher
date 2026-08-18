from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from podcast_fetcher.config import load_config
from podcast_fetcher.discover import (
    build_score_stdin,
    filter_by_threshold,
    normalize_name,
    normalize_url,
    parse_itunes_results,
    parse_score_response,
    render_score_prompt,
    run_discover,
    score_candidates,
    select_new_candidates,
)
from podcast_fetcher.llm import LLMParseError
from podcast_fetcher.models import Candidate, Feed, ScoredCandidate

NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

FAKE_ENV = {
    "GMAIL_CLIENT_ID": "client-id",
    "GMAIL_CLIENT_SECRET": "client-secret",
    "GMAIL_REFRESH_TOKEN": "refresh-token",
}

EXISTING_FEED = Feed(name="Odd Lots", url="https://example.com/oddlots.rss", tier="plumbing")
EXISTING_ARTICLE_FEED = Feed(
    name="Net Interest", url="https://example.com/netinterest.rss", tier="credit", kind="article"
)


def config_with_email(**overrides: str) -> Any:
    env = {"EMAIL_TO": "simon@example.com", "EMAIL_FROM": "bot@example.com", **overrides}
    return load_config(env)


def fake_mint_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    return "fake-access-token"


def recording_send(calls: list[dict[str, Any]]) -> Any:
    def _send(access_token: str, **kwargs: Any) -> None:
        calls.append({"access_token": access_token, **kwargs})

    return _send


def failing_send(access_token: str, **kwargs: Any) -> None:
    raise RuntimeError("gmail API is down")


def fake_search(results_by_term: dict[str, list[dict[str, Any]]]) -> Any:
    def _search(term: str, limit: int) -> Any:
        return {"results": results_by_term.get(term, [])}

    return _search


def itunes_result(name: str, feed_url: str) -> dict[str, Any]:
    return {"collectionName": name, "feedUrl": feed_url}


def fake_score(scores_by_name: dict[str, tuple[int, str]] | None = None) -> Any:
    """A stand-in for score_candidates: scores every candidate 5 ("clearly
    relevant") by default, or per-name if scores_by_name overrides it, so
    existing tests that don't care about scoring keep passing without
    touching the network or the Claude CLI.
    """
    overrides = scores_by_name or {}

    def _score(candidates: Sequence[Candidate], **kwargs: Any) -> list[ScoredCandidate]:
        results = []
        for candidate in candidates:
            score, reason = overrides.get(candidate.name, (5, "test: assumed relevant"))
            results.append(ScoredCandidate(candidate=candidate, score=score, reason=reason))
        return results

    return _score


def failing_score(candidates: Sequence[Candidate], **kwargs: Any) -> list[ScoredCandidate]:
    raise RuntimeError("claude CLI exited 1: scoring failed")


ALWAYS_RELEVANT = fake_score()


def read_discovery_seen(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "state" / "discovery_seen.json"
    if not path.exists():
        return {"seen": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_discovery_seen(tmp_path: Path, seen: dict[str, Any]) -> None:
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "discovery_seen.json").write_text(json.dumps({"seen": seen}), encoding="utf-8")


# --- parse_itunes_results ---


def test_parse_itunes_results_skips_entries_missing_name_or_feed_url() -> None:
    raw = {
        "results": [
            {"collectionName": "Good Show", "feedUrl": "https://example.com/good.rss"},
            {"collectionName": "No Feed Url"},
            {"feedUrl": "https://example.com/noname.rss"},
        ]
    }
    candidates = parse_itunes_results(raw, "repo market")
    assert [c.name for c in candidates] == ["Good Show"]
    assert candidates[0].term == "repo market"


def test_parse_itunes_results_handles_no_results_key() -> None:
    assert parse_itunes_results({}, "repo market") == []


# --- normalize_url / normalize_name ---


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("https://example.com/feed.rss", "https://example.com/feed.rss"),
        ("https://example.com/feed.rss/", "https://example.com/feed.rss"),
        ("http://example.com/feed.rss", "https://example.com/feed.rss"),
        ("HTTPS://Example.com/Feed.rss", "https://example.com/feed.rss"),
        ("  https://example.com/feed.rss  ", "https://example.com/feed.rss"),
    ],
)
def test_normalize_url_treats_equivalent_forms_as_equal(left: str, right: str) -> None:
    assert normalize_url(left) == normalize_url(right)


def test_normalize_url_distinguishes_different_urls() -> None:
    assert normalize_url("https://example.com/a.rss") != normalize_url("https://example.com/b.rss")


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Odd Lots", "odd lots"),
        ("  Odd Lots  ", "Odd Lots"),
        ("Odd   Lots", "Odd Lots"),
        ("ODD LOTS", "Odd Lots"),
    ],
)
def test_normalize_name_treats_equivalent_forms_as_equal(left: str, right: str) -> None:
    assert normalize_name(left) == normalize_name(right)


def test_normalize_name_distinguishes_different_names() -> None:
    assert normalize_name("Odd Lots") != normalize_name("Unhedged")


# --- select_new_candidates ---


def test_select_new_candidates_excludes_match_by_url() -> None:
    candidates = [Candidate(name="Different Name", feed_url="https://example.com/oddlots.rss/", term="repo")]
    assert select_new_candidates(candidates, [EXISTING_FEED], {}) == []


def test_select_new_candidates_excludes_match_by_name() -> None:
    candidates = [Candidate(name="odd lots", feed_url="https://example.com/some-other-url.rss", term="repo")]
    assert select_new_candidates(candidates, [EXISTING_FEED], {}) == []


def test_select_new_candidates_ignores_article_feeds_when_matching_existing() -> None:
    # A candidate that happens to share a URL/name with an *article* feed
    # is not excluded -- discovery only proposes podcasts and only dedupes
    # against the existing podcast list (see SPEC.md).
    candidates = [Candidate(name="Net Interest", feed_url=EXISTING_ARTICLE_FEED.url, term="credit")]
    result = select_new_candidates(candidates, [EXISTING_ARTICLE_FEED], {})
    assert result == candidates


def test_select_new_candidates_keeps_genuinely_new_show() -> None:
    candidates = [Candidate(name="New Repo Show", feed_url="https://example.com/newrepo.rss", term="repo")]
    assert select_new_candidates(candidates, [EXISTING_FEED], {}) == candidates


def test_select_new_candidates_excludes_previously_proposed_by_url() -> None:
    candidates = [Candidate(name="Different Name", feed_url="https://example.com/newrepo.rss/", term="repo")]
    seen = {"https://example.com/newrepo.rss": {"name": "New Repo Show", "feed_url": "https://example.com/newrepo.rss", "term": "repo"}}
    assert select_new_candidates(candidates, [], seen) == []


def test_select_new_candidates_excludes_previously_proposed_by_name() -> None:
    candidates = [Candidate(name="new repo show", feed_url="https://example.com/a-different-url.rss", term="repo")]
    seen = {"x": {"name": "New Repo Show", "feed_url": "https://example.com/newrepo.rss", "term": "repo"}}
    assert select_new_candidates(candidates, [], seen) == []


def test_select_new_candidates_dedupes_within_the_same_batch() -> None:
    candidates = [
        Candidate(name="New Repo Show", feed_url="https://example.com/newrepo.rss", term="repo market"),
        Candidate(name="New Repo Show", feed_url="https://example.com/newrepo.rss", term="funding markets"),
    ]
    result = select_new_candidates(candidates, [], {})
    assert len(result) == 1


# --- run_discover ---


def test_run_discover_emails_new_candidates_and_records_them(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({"repo market": [itunes_result("New Repo Show", "https://example.com/newrepo.rss")]}),
        score=ALWAYS_RELEVANT,
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "New Repo Show" in calls[0]["html"]
    assert "https://example.com/newrepo.rss" in calls[0]["html"]
    assert "repo market" in calls[0]["html"]
    assert "1 new show candidate" in calls[0]["subject"]

    seen = read_discovery_seen(tmp_path)["seen"]
    assert normalize_url("https://example.com/newrepo.rss") in seen
    assert seen[normalize_url("https://example.com/newrepo.rss")] == {
        "name": "New Repo Show",
        "feed_url": "https://example.com/newrepo.rss",
        "term": "repo market",
    }


def test_run_discover_excludes_already_existing_feed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({"repo market": [itunes_result("Odd Lots", EXISTING_FEED.url)]}),
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "no new candidates" in calls[0]["subject"].lower()
    assert "Odd Lots" not in calls[0]["html"]


def test_run_discover_no_candidates_sends_quiet_note(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({}),
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "no new candidates" in calls[0]["subject"].lower()
    assert "no new candidate" in calls[0]["html"].lower()
    assert not (tmp_path / "state" / "discovery_seen.json").exists()


def test_run_discover_empty_discovery_terms_sends_quiet_note(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [],
        [],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({}),
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "no new candidates" in calls[0]["subject"].lower()


def test_run_discover_failing_search_term_does_not_abort_run(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    def flaky_search(term: str, limit: int) -> Any:
        if term == "SOFR":
            raise ConnectionError("itunes is down")
        return {"results": [itunes_result("New Repo Show", "https://example.com/newrepo.rss")]}

    run_discover(
        [EXISTING_FEED],
        ["SOFR", "repo market"],
        config_with_email(),
        FAKE_ENV,
        search=flaky_search,
        score=ALWAYS_RELEVANT,
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "New Repo Show" in calls[0]["html"]


def test_run_discover_never_adds_a_feed(tmp_path: Path, monkeypatch: Any) -> None:
    # There is no feeds.yaml write path anywhere in discover.py/run_discover;
    # this asserts the repo's feeds.yaml (if present in cwd) is untouched.
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({"repo market": [itunes_result("New Repo Show", "https://example.com/newrepo.rss")]}),
        score=ALWAYS_RELEVANT,
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert not (tmp_path / "feeds.yaml").exists()


def test_run_discover_records_candidates_only_after_successful_send(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RuntimeError, match="gmail API is down"):
        run_discover(
            [EXISTING_FEED],
            ["repo market"],
            config_with_email(),
            FAKE_ENV,
            search=fake_search({"repo market": [itunes_result("New Repo Show", "https://example.com/newrepo.rss")]}),
            score=ALWAYS_RELEVANT,
            mint_token=fake_mint_token,
            send=failing_send,
            now=NOW,
        )

    assert not (tmp_path / "state" / "discovery_seen.json").exists()


def test_run_discover_already_proposed_candidate_is_not_reproposed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    write_discovery_seen(
        tmp_path,
        {
            normalize_url("https://example.com/newrepo.rss"): {
                "name": "New Repo Show",
                "feed_url": "https://example.com/newrepo.rss",
                "term": "repo market",
            }
        },
    )
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({"repo market": [itunes_result("New Repo Show", "https://example.com/newrepo.rss")]}),
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert "New Repo Show" not in calls[0]["html"]
    assert "no new candidates" in calls[0]["subject"].lower()


def test_run_discover_missing_email_to_raises_before_sending(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    with pytest.raises(RuntimeError, match="EMAIL_TO"):
        run_discover(
            [],
            [],
            load_config({}),
            FAKE_ENV,
            search=fake_search({}),
            mint_token=fake_mint_token,
            send=recording_send(calls),
            now=NOW,
        )
    assert calls == []


def test_run_discover_missing_gmail_secret_raises_before_sending(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []
    incomplete_env = {"GMAIL_CLIENT_ID": "x"}

    with pytest.raises(RuntimeError, match="GMAIL_CLIENT_SECRET"):
        run_discover(
            [],
            [],
            config_with_email(),
            incomplete_env,
            search=fake_search({}),
            mint_token=fake_mint_token,
            send=recording_send(calls),
            now=NOW,
        )
    assert calls == []


# --- Claude scoring pass (ticket #8) ---

SCORE_CANDIDATES = [
    Candidate(name="Odd Lots", feed_url="https://example.com/oddlots.rss", term="repo", artist_name="Bloomberg", genres=("Business", "News")),
    Candidate(name="Bankless", feed_url="https://example.com/bankless.rss", term="repo", artist_name="Bankless LLC", genres=("Business",)),
]


def test_build_score_stdin_includes_id_name_artist_and_genres() -> None:
    stdin_text = build_score_stdin(SCORE_CANDIDATES)
    payload = json.loads(stdin_text)
    assert payload == [
        {"id": 0, "name": "Odd Lots", "artist": "Bloomberg", "genres": ["Business", "News"]},
        {"id": 1, "name": "Bankless", "artist": "Bankless LLC", "genres": ["Business"]},
    ]


def test_render_score_prompt_shares_persona_text_with_extract_prompt() -> None:
    # Regression guard for issue #8: the show-scoring prompt must pull the
    # same priorities as prompts/extract.txt from the shared persona file,
    # not a hand-copied duplicate that can drift.
    prompt = render_score_prompt()
    assert "{{PERSONA}}" not in prompt
    assert "Money-market plumbing" in prompt
    assert "structured credit" in prompt.lower()


def test_render_score_prompt_states_it_judges_a_show_not_an_episode() -> None:
    prompt = render_score_prompt()
    assert "SHOW" in prompt
    assert "transcript" in prompt.lower()
    assert "not" in prompt.lower()


def test_render_score_prompt_instructs_low_score_for_unrecognised_shows() -> None:
    prompt = render_score_prompt()
    assert "do not recognise" in prompt.lower() or "don't recognise" in prompt.lower()
    assert "score it low" in prompt.lower()


def test_parse_score_response_valid() -> None:
    raw = json.dumps(
        {
            "scores": [
                {"id": 0, "score": 2, "reason": "Crypto-adjacent, not our beat."},
                {"id": 1, "score": 5, "reason": "Directly on repo/plumbing."},
            ]
        }
    )
    result = parse_score_response(raw, expected_count=2)
    assert result == {0: (2, "Crypto-adjacent, not our beat."), 1: (5, "Directly on repo/plumbing.")}


def test_parse_score_response_tolerates_prose_wrapped_json() -> None:
    raw = 'Here you go:\n{"scores": [{"id": 0, "score": 3, "reason": "ok"}]}\nDone.'
    result = parse_score_response(raw, expected_count=1)
    assert result == {0: (3, "ok")}


def test_parse_score_response_missing_scores_key_raises() -> None:
    with pytest.raises(LLMParseError):
        parse_score_response("{}", expected_count=1)


def test_parse_score_response_incomplete_coverage_raises() -> None:
    raw = json.dumps({"scores": [{"id": 0, "score": 3, "reason": "ok"}]})
    with pytest.raises(LLMParseError):
        parse_score_response(raw, expected_count=2)


def test_parse_score_response_out_of_range_score_raises() -> None:
    raw = json.dumps({"scores": [{"id": 0, "score": 9, "reason": "ok"}]})
    with pytest.raises(LLMParseError):
        parse_score_response(raw, expected_count=1)


def test_parse_score_response_out_of_range_id_raises() -> None:
    raw = json.dumps({"scores": [{"id": 5, "score": 3, "reason": "ok"}]})
    with pytest.raises(LLMParseError):
        parse_score_response(raw, expected_count=1)


def test_parse_score_response_missing_reason_raises() -> None:
    raw = json.dumps({"scores": [{"id": 0, "score": 3}]})
    with pytest.raises(LLMParseError):
        parse_score_response(raw, expected_count=1)


def test_score_candidates_empty_list_returns_empty_without_calling_run() -> None:
    def unreachable_run(*args: Any, **kwargs: Any) -> str:
        raise AssertionError("run_claude should not be called for an empty candidate list")

    assert score_candidates([], run=unreachable_run) == []


def test_score_candidates_builds_prompt_and_stdin_and_parses_response() -> None:
    captured: dict[str, Any] = {}

    def fake_run(instructions: str, stdin_text: str, *, model: str | None = None) -> str:
        captured["instructions"] = instructions
        captured["stdin_text"] = stdin_text
        captured["model"] = model
        return json.dumps({"scores": [{"id": 0, "score": 2, "reason": "crypto"}, {"id": 1, "score": 5, "reason": "repo"}]})

    result = score_candidates(SCORE_CANDIDATES, claude_model="claude-x", run=fake_run)

    assert captured["model"] == "claude-x"
    assert "Money-market plumbing" in captured["instructions"]
    payload = json.loads(captured["stdin_text"])
    assert [entry["name"] for entry in payload] == ["Odd Lots", "Bankless"]

    assert result == [
        ScoredCandidate(candidate=SCORE_CANDIDATES[0], score=2, reason="crypto"),
        ScoredCandidate(candidate=SCORE_CANDIDATES[1], score=5, reason="repo"),
    ]


def test_score_candidates_propagates_malformed_response_as_llmparseerror() -> None:
    def bad_run(instructions: str, stdin_text: str, *, model: str | None = None) -> str:
        return "not json at all"

    with pytest.raises(LLMParseError):
        score_candidates(SCORE_CANDIDATES, run=bad_run)


# --- filter_by_threshold ---


def test_filter_by_threshold_keeps_at_or_above_and_drops_below() -> None:
    scored = [
        ScoredCandidate(candidate=SCORE_CANDIDATES[0], score=2, reason="no"),
        ScoredCandidate(candidate=SCORE_CANDIDATES[1], score=3, reason="borderline"),
    ]
    result = filter_by_threshold(scored, threshold=3)
    assert [item.candidate.name for item in result] == ["Bankless"]


def test_filter_by_threshold_drops_none_scores() -> None:
    scored = [ScoredCandidate(candidate=SCORE_CANDIDATES[0], score=None, reason=None)]
    assert filter_by_threshold(scored, threshold=1) == []


# --- run_discover: scoring integration (ticket #8) ---


def test_run_discover_below_threshold_candidate_is_not_emailed_and_not_marked_seen(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # The subtlest rule in the ticket: a candidate filtered out by scoring
    # must NOT be recorded in discovery_seen.json, so a future, better
    # prompt can still surface it -- unlike a candidate that is emailed.
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["crypto"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({"crypto": [itunes_result("Bankless", "https://example.com/bankless.rss")]}),
        score=fake_score({"Bankless": (2, "Crypto show, off our beat.")}),
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "Bankless" not in calls[0]["html"]
    assert "no new candidates" in calls[0]["subject"].lower()

    seen = read_discovery_seen(tmp_path)["seen"]
    assert normalize_url("https://example.com/bankless.rss") not in seen


def test_run_discover_mixed_scores_emails_and_records_only_those_above_threshold(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search(
            {
                "repo market": [
                    itunes_result("New Repo Show", "https://example.com/newrepo.rss"),
                    itunes_result("Bankless", "https://example.com/bankless.rss"),
                ]
            }
        ),
        score=fake_score({"New Repo Show": (5, "on-topic"), "Bankless": (1, "crypto, off-topic")}),
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "New Repo Show" in calls[0]["html"]
    assert "Bankless" not in calls[0]["html"]

    seen = read_discovery_seen(tmp_path)["seen"]
    assert normalize_url("https://example.com/newrepo.rss") in seen
    assert normalize_url("https://example.com/bankless.rss") not in seen


def test_run_discover_scoring_failure_falls_back_to_unscored_list_and_marks_all_seen(
    tmp_path: Path, monkeypatch: Any
) -> None:
    # Scoring failure is non-fatal: log it and email the unscored
    # candidate list rather than sending nothing. Unlike the
    # below-threshold case, everything emailed here IS marked seen,
    # since Simon did see the whole list.
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({"repo market": [itunes_result("New Repo Show", "https://example.com/newrepo.rss")]}),
        score=failing_score,
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "New Repo Show" in calls[0]["html"]
    assert "unscored" in calls[0]["html"].lower()
    assert "1 new show candidate" in calls[0]["subject"]

    seen = read_discovery_seen(tmp_path)["seen"]
    assert normalize_url("https://example.com/newrepo.rss") in seen


def test_run_discover_scoring_never_invoked_when_no_new_candidates(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    run_discover(
        [EXISTING_FEED],
        ["repo market"],
        config_with_email(),
        FAKE_ENV,
        search=fake_search({"repo market": [itunes_result("Odd Lots", EXISTING_FEED.url)]}),
        score=failing_score,
        mint_token=fake_mint_token,
        send=recording_send(calls),
        now=NOW,
    )

    assert len(calls) == 1
    assert "no new candidates" in calls[0]["subject"].lower()
