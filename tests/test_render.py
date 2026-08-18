from __future__ import annotations

from podcast_fetcher.render import render_digest

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
