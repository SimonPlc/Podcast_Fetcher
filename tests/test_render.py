from __future__ import annotations

from podcast_fetcher.models import Candidate, ScoredCandidate
from podcast_fetcher.render import render_digest, render_discovery

ITEMS = {
    "guid-1": {
        "feed_name": "Odd Lots",
        "title": "Repo Market Update",
        "url": "https://example.com/ep1.mp3",
        "score": 5,
        "one_liner": "Reserves are getting scarce.",
        "tags": ["repo", "SOFR"],
        "summary": ["Reserves near $2.9tn.", "SOFR-OIS widening."],
        "key_claims": ["Reserves have fallen to ~$2.9tn (guest estimate)."],
    },
    "guid-2": {
        "feed_name": "Macro Musings",
        "title": "Fed Balance Sheet Deep Dive",
        "url": "https://example.com/ep2.mp3",
        "score": 4,
        "one_liner": "QT is nearing its endgame.",
        "tags": ["Fed", "QT"],
        "summary": ["QT may slow within two meetings."],
        "key_claims": [],
    },
}

MIXED_ITEMS = {
    "guid-1": {
        "feed_name": "Odd Lots",
        "title": "Repo Market Update",
        "url": "https://example.com/ep1.mp3",
        "kind": "podcast",
        "score": 3,
        "one_liner": "x",
        "tags": [],
        "summary": [],
        "key_claims": [],
    },
    "hash-1": {
        "feed_name": "NY Fed Liberty Street Economics",
        "title": "Reserves Are Getting Scarce",
        "url": "https://libertystreeteconomics.newyorkfed.org/some-post",
        "kind": "article",
        "score": 5,
        "one_liner": "x",
        "tags": [],
        "summary": [],
        "key_claims": [],
    },
}


def test_populated_html_contains_each_episode_title_and_link() -> None:
    html, _ = render_digest(ITEMS)
    assert "Repo Market Update" in html
    assert "https://example.com/ep1.mp3" in html
    assert "Fed Balance Sheet Deep Dive" in html
    assert "https://example.com/ep2.mp3" in html


def test_populated_text_contains_each_episode_title_and_link() -> None:
    _, text = render_digest(ITEMS)
    assert "Repo Market Update" in text
    assert "https://example.com/ep1.mp3" in text


def test_populated_html_contains_feed_name_score_and_one_liner() -> None:
    html, _ = render_digest(ITEMS)
    assert "Odd Lots" in html
    assert "5/5" in html
    assert "Reserves are getting scarce." in html


def test_populated_html_contains_tags_summary_and_key_claims() -> None:
    html, _ = render_digest(ITEMS)
    assert "repo" in html
    assert "Reserves near $2.9tn." in html
    assert "Reserves have fallen to ~$2.9tn (guest estimate)." in html


def test_populated_html_sorts_episodes_by_score_descending() -> None:
    html, _ = render_digest(ITEMS)
    assert html.index("Repo Market Update") < html.index("Fed Balance Sheet Deep Dive")


def test_populated_text_sorts_episodes_by_score_descending() -> None:
    _, text = render_digest(ITEMS)
    assert text.index("Repo Market Update") < text.index("Fed Balance Sheet Deep Dive")


def test_episode_with_no_key_claims_does_not_crash() -> None:
    html, text = render_digest(ITEMS)
    assert "Fed Balance Sheet Deep Dive" in html
    assert "Fed Balance Sheet Deep Dive" in text


def test_quiet_day_renders_note_not_empty_shell() -> None:
    html, text = render_digest({})
    assert "nothing" in html.lower() or "quiet" in html.lower()
    assert "nothing" in text.lower() or "quiet" in text.lower()
    assert "PODCAST DIGEST" not in text


def test_quiet_day_html_and_text_are_non_empty() -> None:
    html, text = render_digest({})
    assert len(html.strip()) > 0
    assert len(text.strip()) > 0


# --- unified podcast/article rendering (ticket #7) ---


def test_article_card_links_as_read() -> None:
    html, text = render_digest(MIXED_ITEMS)
    assert ">Read<" in html
    assert "Read: https://libertystreeteconomics.newyorkfed.org/some-post" in text


def test_episode_card_links_as_listen() -> None:
    html, text = render_digest(MIXED_ITEMS)
    assert ">Listen<" in html
    assert "Listen: https://example.com/ep1.mp3" in text


def test_record_with_no_kind_defaults_to_listen() -> None:
    # Podcast records committed to state before articles existed have no
    # "kind" field; they must still render as episodes, not blow up.
    legacy_items = {"guid-1": {**ITEMS["guid-1"]}}
    del legacy_items["guid-1"]["one_liner"]  # unrelated field, just proving no crash on a sparse record
    html, text = render_digest(legacy_items)
    assert ">Listen<" in html
    assert "Listen:" in text


def test_unified_list_sorts_podcast_and_article_by_score_descending() -> None:
    html, _ = render_digest(MIXED_ITEMS)
    # article (score 5) must come before podcast (score 3)
    assert html.index("Reserves Are Getting Scarce") < html.index("Repo Market Update")


# --- render_discovery (ticket #5, extended with scores by ticket #8) ---

CANDIDATES = [
    ScoredCandidate(
        candidate=Candidate(name="New Repo Show", feed_url="https://example.com/newrepo.rss", term="repo market"),
        score=4,
        reason="Repo-focused show squarely on the plumbing/funding beat.",
    ),
    ScoredCandidate(
        candidate=Candidate(
            name="Credit Weekly", feed_url="https://example.com/creditweekly.rss", term="structured credit"
        ),
        score=3,
        reason="Structured credit coverage, worth a look.",
    ),
]


def test_discovery_html_contains_each_candidate_name_url_and_term() -> None:
    html, _ = render_discovery(CANDIDATES)
    assert "New Repo Show" in html
    assert "https://example.com/newrepo.rss" in html
    assert "repo market" in html
    assert "Credit Weekly" in html
    assert "https://example.com/creditweekly.rss" in html
    assert "structured credit" in html


def test_discovery_text_contains_each_candidate_name_url_and_term() -> None:
    _, text = render_discovery(CANDIDATES)
    assert "New Repo Show" in text
    assert "https://example.com/newrepo.rss" in text
    assert "repo market" in text


def test_discovery_html_and_text_contain_score_and_reason() -> None:
    html, text = render_discovery(CANDIDATES)
    assert "4/5" in html
    assert "Repo-focused show squarely on the plumbing/funding beat." in html
    assert "3/5" in text
    assert "Structured credit coverage, worth a look." in text


def test_discovery_states_nothing_added_automatically() -> None:
    html, text = render_discovery(CANDIDATES)
    assert "nothing was added automatically" in html.lower()
    assert "nothing was added automatically" in text.lower()


def test_discovery_empty_renders_no_new_candidates_note() -> None:
    html, text = render_discovery([])
    assert "no new candidate" in html.lower()
    assert "no new candidate" in text.lower()
    assert "nothing was added automatically" in html.lower()


def test_discovery_empty_html_and_text_are_non_empty() -> None:
    html, text = render_discovery([])
    assert len(html.strip()) > 0
    assert len(text.strip()) > 0


def test_discovery_unscored_fallback_marks_candidates_and_omits_fake_scores() -> None:
    unscored_candidates = [
        ScoredCandidate(
            candidate=Candidate(name="New Repo Show", feed_url="https://example.com/newrepo.rss", term="repo market"),
            score=None,
            reason=None,
        )
    ]
    html, text = render_discovery(unscored_candidates, unscored=True)
    assert "New Repo Show" in html
    assert "unscored" in html.lower()
    assert "unscored" in text.lower()
    assert "4/5" not in html
    assert "scoring failed" in html.lower() or "unscored" in html.lower()


def test_discovery_scored_path_does_not_show_unscored_note() -> None:
    html, text = render_discovery(CANDIDATES, unscored=False)
    assert "scoring failed" not in html.lower()
    assert "scoring failed" not in text.lower()
