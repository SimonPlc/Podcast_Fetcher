from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from podcast_fetcher.config import load_config
from podcast_fetcher.discover import (
    normalize_name,
    normalize_url,
    parse_itunes_results,
    run_discover,
    select_new_candidates,
)
from podcast_fetcher.models import Candidate, Feed

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
