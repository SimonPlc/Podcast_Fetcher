from __future__ import annotations

from podcast_fetcher.models import Brief, Theme, ThemePoint
from podcast_fetcher.render import render_digest

SOURCES = {
    "guid-1": {
        "feed_name": "Odd Lots",
        "title": "Repo Market Update",
        "url": "https://example.com/ep1.mp3",
    },
    "guid-2": {
        "feed_name": "Macro Musings",
        "title": "Fed Balance Sheet Deep Dive",
        "url": "https://example.com/ep2.mp3",
    },
}

BRIEF = Brief(
    headline="Fed reserves near $2.9tn, QT endgame in focus.",
    tldr="Multiple shows flagged tightening repo conditions into quarter-end.",
    themes=[
        Theme(
            name="Front-end / repo",
            points=[
                ThemePoint(text="Reserves near $2.9tn; SOFR-OIS widening.", source_ids=["guid-1", "guid-2"]),
            ],
        )
    ],
    watch=["Next FOMC meeting"],
    learned=["SOFR-OIS spread as an early collateral-scarcity signal"],
)


def test_populated_html_contains_headline_and_tldr() -> None:
    html, _ = render_digest(BRIEF, SOURCES)
    assert BRIEF.headline in html
    assert BRIEF.tldr in html


def test_populated_text_contains_headline_and_tldr() -> None:
    _, text = render_digest(BRIEF, SOURCES)
    assert BRIEF.headline in text
    assert BRIEF.tldr in text


def test_populated_html_contains_theme_name_and_point_text() -> None:
    html, _ = render_digest(BRIEF, SOURCES)
    assert "Front-end / repo" in html
    assert "Reserves near $2.9tn; SOFR-OIS widening." in html


def test_populated_html_attributes_points_to_source_titles() -> None:
    html, _ = render_digest(BRIEF, SOURCES)
    assert "Repo Market Update" in html
    assert "Fed Balance Sheet Deep Dive" in html


def test_populated_html_contains_watch_and_learned_sections() -> None:
    html, _ = render_digest(BRIEF, SOURCES)
    assert "Next FOMC meeting" in html
    assert "SOFR-OIS spread as an early collateral-scarcity signal" in html


def test_populated_html_contains_source_index_with_links() -> None:
    html, _ = render_digest(BRIEF, SOURCES)
    assert "https://example.com/ep1.mp3" in html
    assert "https://example.com/ep2.mp3" in html
    assert "Odd Lots" in html
    assert "Macro Musings" in html


def test_populated_text_contains_source_index() -> None:
    _, text = render_digest(BRIEF, SOURCES)
    assert "https://example.com/ep1.mp3" in text
    assert "Odd Lots" in text


def test_theme_with_no_points_does_not_crash() -> None:
    brief = Brief(headline="h", tldr="t", themes=[Theme(name="Empty theme", points=[])], watch=[], learned=[])
    html, text = render_digest(brief, {})
    assert "Empty theme" in html
    assert "Empty theme" in text


def test_quiet_day_renders_note_not_empty_shell() -> None:
    html, text = render_digest(None, {})
    assert "nothing" in html.lower() or "quiet" in html.lower()
    assert "nothing" in text.lower() or "quiet" in text.lower()
    # must not contain leftover structural markers from the populated template
    assert "TL;DR" not in html
    assert "Sources" not in html


def test_quiet_day_html_and_text_are_non_empty() -> None:
    html, text = render_digest(None, {})
    assert len(html.strip()) > 0
    assert len(text.strip()) > 0
