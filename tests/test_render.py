from __future__ import annotations

from typing import Any

from podcast_fetcher.models import Candidate, ScoredCandidate
from podcast_fetcher.render import render_digest, render_discovery

ITEMS: dict[str, dict[str, Any]] = {
    "guid-1": {
        "feed_name": "Odd Lots",
        "title": "Repo Market Update",
        "url": "https://example.com/ep1.mp3",
        "score": 5,
        "one_liner": "Reserves are getting scarce.",
        "tags": ["repo", "SOFR"],
        "recap": "Reserves near $2.9tn amid persistent SOFR-OIS widening, the guest says.",
        "implications": "Repo desks should watch month-end funding pressure closely.",
        "watch": ["Month-end repo pricing"],
        "terms": ["SOFR -- the Secured Overnight Financing Rate"],
        "key_claims": ["Reserves have fallen to ~$2.9tn (guest estimate)."],
    },
    "guid-2": {
        "feed_name": "Macro Musings",
        "title": "Fed Balance Sheet Deep Dive",
        "url": "https://example.com/ep2.mp3",
        "score": 4,
        "one_liner": "QT is nearing its endgame.",
        "tags": ["Fed", "QT"],
        "recap": "QT may slow within two meetings, the guest argues.",
        "implications": "",
        "watch": [],
        "terms": [],
        "key_claims": [],
    },
}

MIXED_ITEMS: dict[str, dict[str, Any]] = {
    "guid-1": {
        "feed_name": "Odd Lots",
        "title": "Repo Market Update",
        "url": "https://example.com/ep1.mp3",
        "kind": "podcast",
        "score": 3,
        "one_liner": "x",
        "tags": [],
        "recap": "x",
        "implications": "",
        "watch": [],
        "terms": [],
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
        "recap": "x",
        "implications": "",
        "watch": [],
        "terms": [],
        "key_claims": [],
    },
}

# A single fully-populated new-shape record, for tests that need every
# recap-format block (Why it matters/Watch/Terms/Key claims) present at once.
FULL_ITEM: dict[str, Any] = {
    "feed_name": "Odd Lots",
    "title": "Repo Market Update",
    "url": "https://example.com/ep1.mp3",
    "score": 5,
    "one_liner": "Reserves are getting scarce.",
    "tags": ["repo"],
    "recap": "Reserves near $2.9tn amid persistent SOFR-OIS widening, the guest says.",
    "implications": "Repo desks should watch month-end funding pressure closely.",
    "watch": ["Month-end repo pricing"],
    "terms": ["SOFR -- the Secured Overnight Financing Rate"],
    "key_claims": ["Reserves have fallen to ~$2.9tn (guest estimate)."],
}

# A new-shape record with every optional block empty, to prove they're
# omitted rather than rendered as empty headings.
SPARSE_ITEM: dict[str, Any] = {
    "feed_name": "Odd Lots",
    "title": "Repo Market Update",
    "url": "https://example.com/ep1.mp3",
    "score": 5,
    "one_liner": "Reserves are getting scarce.",
    "tags": [],
    "recap": "Reserves near $2.9tn, the guest says.",
    "implications": "",
    "watch": [],
    "terms": [],
    "key_claims": [],
}

# An OLD-shape record: the two episodes already queued in
# state/pending_digest.json when the recap format shipped have `summary`
# (a bullet list) and no `recap` at all, so tomorrow's digest must still
# render them (backward compat).
OLD_SHAPE_ITEM: dict[str, Any] = {
    "feed_name": "Odd Lots",
    "title": "Repo Market Update",
    "url": "https://example.com/ep1.mp3",
    "score": 5,
    "one_liner": "Reserves are getting scarce.",
    "tags": ["repo"],
    "summary": ["Reserves near $2.9tn.", "SOFR-OIS widening."],
    "key_claims": ["Reserves have fallen to ~$2.9tn (guest estimate)."],
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


def test_populated_html_contains_tags_recap_and_key_claims() -> None:
    html, _ = render_digest(ITEMS)
    assert "repo" in html
    assert "Reserves near $2.9tn amid persistent SOFR-OIS widening" in html
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


# --- recap-format card (drops Phase 2 direction: recap/implications/watch/terms) ---


def test_full_new_shape_record_renders_all_recap_blocks() -> None:
    html, text = render_digest({"guid-1": FULL_ITEM})
    assert FULL_ITEM["recap"] in html
    assert FULL_ITEM["recap"] in text
    assert "Why it matters" in html
    assert "Why it matters" in text
    assert FULL_ITEM["implications"] in html
    assert FULL_ITEM["implications"] in text
    assert "Watch" in html
    assert "Watch" in text
    assert FULL_ITEM["watch"][0] in html
    assert FULL_ITEM["watch"][0] in text
    assert "Terms" in html
    assert "Terms" in text
    assert FULL_ITEM["terms"][0] in html
    assert FULL_ITEM["terms"][0] in text
    assert "Key claims" in html
    assert "Key claims" in text


def test_empty_implications_watch_and_terms_omit_their_blocks() -> None:
    html, text = render_digest({"guid-1": SPARSE_ITEM})
    assert SPARSE_ITEM["recap"] in html
    assert "Why it matters" not in html
    assert "Why it matters" not in text
    assert "Watch" not in html
    assert "Watch" not in text
    assert "Terms" not in html
    assert "Terms" not in text
    assert "Key claims" not in html
    assert "Key claims" not in text


def test_old_shape_record_with_summary_list_still_renders_bullets() -> None:
    # Backward compat: the two episodes already queued in
    # state/pending_digest.json have `summary`, not `recap`.
    html, text = render_digest({"guid-1": OLD_SHAPE_ITEM})
    for bullet in OLD_SHAPE_ITEM["summary"]:
        assert bullet in html
        assert bullet in text
    assert "Why it matters" not in html
    assert "Watch" not in html
    assert "Terms" not in html
    assert "Key claims" in html  # unaffected, still renders as before


def test_quiet_day_renders_note_not_empty_shell() -> None:
    html, text = render_digest({})
    assert "nothing" in html.lower() or "quiet" in html.lower()
    assert "nothing" in text.lower() or "quiet" in text.lower()
    assert "PODCAST DIGEST" not in text


def test_quiet_day_html_and_text_are_non_empty() -> None:
    html, text = render_digest({})
    assert len(html.strip()) > 0
    assert len(text.strip()) > 0


# --- Claude-unavailable vs quiet day: an empty digest must say which ---


def test_empty_unavailable_reports_not_a_quiet_day() -> None:
    html, text = render_digest({}, claude_unavailable=True)
    assert "unavailable" in html.lower()
    assert "not a quiet day" in text.lower()
    # It must not be the ordinary quiet-day message, which would hide the outage.
    assert "quiet day, but the pipeline ran" not in text.lower()


def test_empty_without_unavailable_flag_is_still_quiet_day() -> None:
    _, text = render_digest({})
    assert "quiet" in text.lower()
    assert "unavailable" not in text.lower()


def test_items_present_with_unavailable_flag_shows_banner_and_keeps_cards() -> None:
    html, text = render_digest(ITEMS, claude_unavailable=True)
    # The already-scored cards are still delivered...
    assert "Repo Market Update" in html
    assert "Repo Market Update" in text
    # ...with a banner explaining today's articles could not be scored.
    assert "could not be scored" in html.lower()
    assert "could not be scored" in text.lower()


def test_items_present_without_unavailable_flag_has_no_banner() -> None:
    html, text = render_digest(ITEMS)
    assert "could not be scored" not in html.lower()
    assert "could not be scored" not in text.lower()


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


def test_discovery_no_candidates_but_deferrals_reports_scoring_unavailable() -> None:
    # Nothing could be judged, so nothing is proposed. The email has to say
    # that plainly rather than looking like an ordinary quiet month.
    html, text = render_discovery([], deferred_count=225)
    assert "scoring was unavailable" in html.lower()
    assert "scoring was unavailable" in text.lower()
    assert "reconsidered on the next run" in text.lower()


def test_discovery_deferred_count_is_reported_alongside_proposals() -> None:
    html, text = render_discovery(CANDIDATES, deferred_count=3)
    assert "3 further candidate shows could not be scored" in html
    assert "3 further candidate shows could not be scored" in text


def test_discovery_deferred_note_is_singular_for_one() -> None:
    html, _ = render_discovery(CANDIDATES, deferred_count=1)
    assert "1 further candidate show could not be scored" in html


def test_discovery_no_deferrals_shows_no_deferral_note() -> None:
    html, text = render_discovery(CANDIDATES)
    assert "could not be scored" not in html
    assert "could not be scored" not in text


def test_discovery_never_lists_a_deferred_show() -> None:
    # A deferred candidate is unvetted, which is precisely what this email
    # exists to filter out, so only its count is ever reported.
    html, text = render_discovery(CANDIDATES, deferred_count=2)
    assert "Score:" in text
    assert "unscored" not in text.lower()
