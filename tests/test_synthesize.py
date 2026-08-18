from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from podcast_fetcher.llm import LLMParseError
from podcast_fetcher.models import Brief, Theme, ThemePoint
from podcast_fetcher.synthesize import (
    _MAX_RESHAPE_ATTEMPTS,
    _parse_strict,
    _reshape_to_brief,
    build_queue_payload,
    parse_brief,
)

CLEAN_JSON = """{
  "headline": "Fed reserves near $2.9tn, QT endgame in focus.",
  "tldr": "Multiple shows flagged tightening repo conditions into quarter-end.",
  "themes": [
    {
      "name": "Front-end / repo",
      "points": [
        {"text": "Reserves near $2.9tn; SOFR-OIS widening.", "source_ids": ["a1", "b2"]}
      ]
    }
  ],
  "watch": ["Next FOMC meeting"],
  "learned": ["SOFR-OIS spread as an early collateral-scarcity signal"]
}"""


def test_parses_clean_brief() -> None:
    brief = parse_brief(CLEAN_JSON)
    assert brief == Brief(
        headline="Fed reserves near $2.9tn, QT endgame in focus.",
        tldr="Multiple shows flagged tightening repo conditions into quarter-end.",
        themes=[
            Theme(
                name="Front-end / repo",
                points=[ThemePoint(text="Reserves near $2.9tn; SOFR-OIS widening.", source_ids=["a1", "b2"])],
            )
        ],
        watch=["Next FOMC meeting"],
        learned=["SOFR-OIS spread as an early collateral-scarcity signal"],
    )


def test_parses_brief_wrapped_in_prose() -> None:
    raw = f"Here you go:\n{CLEAN_JSON}\nLet me know if you need changes."
    brief = parse_brief(raw)
    assert brief.headline == "Fed reserves near $2.9tn, QT endgame in focus."


def test_raises_on_malformed_output() -> None:
    with pytest.raises(LLMParseError):
        parse_brief("Sorry, I can't do that.")


def test_strict_parser_rejects_missing_headline() -> None:
    with pytest.raises(LLMParseError):
        _parse_strict({"tldr": "x", "themes": [], "watch": [], "learned": []})


def test_strict_parser_rejects_theme_missing_points() -> None:
    with pytest.raises(LLMParseError):
        _parse_strict({"headline": "h", "tldr": "t", "themes": [{"name": "x"}], "watch": [], "learned": []})


def test_strict_parser_rejects_point_missing_source_ids() -> None:
    with pytest.raises(LLMParseError):
        _parse_strict(
            {
                "headline": "h",
                "tldr": "t",
                "themes": [{"name": "x", "points": [{"text": "y"}]}],
                "watch": [],
                "learned": [],
            }
        )


def test_parse_brief_rescues_non_strict_shapes_via_lenient_fallback() -> None:
    # parse_brief (the public entrypoint) is deliberately lenient even
    # though _parse_strict rejects this same shape -- confirms the
    # fallback actually engages rather than the whole thing raising.
    data = {
        "main_point": "the headline text",
        "themes": [{"name": "x", "points": [{"text": "point", "source_ids": []}]}],
        "watch": [],
        "learned": [],
    }
    brief = parse_brief(json.dumps(data))
    assert brief.headline == "the headline text"


def test_lenient_fallback_does_not_let_headline_steal_a_hint_matched_tldr() -> None:
    # regression: a hint-matchable "tldr" key must not be stolen by
    # headline's fallback-grab before tldr gets a chance to hint-match it.
    data = {
        "tldr": "the tldr text",
        "themes": [{"name": "x", "points": [{"text": "point", "source_ids": []}]}],
        "watch": [],
        "learned": [],
    }
    brief = parse_brief(json.dumps(data))
    assert brief.tldr == "the tldr text"


def test_empty_themes_list_is_valid() -> None:
    minimal = """{"headline": "h", "tldr": "t", "themes": [], "watch": [], "learned": []}"""
    brief = parse_brief(minimal)
    assert brief.themes == []


def test_build_queue_payload_produces_json_and_lookup() -> None:
    pending = {
        "queued": {
            "guid-1": {
                "feed_name": "Odd Lots",
                "title": "Repo Market Update",
                "url": "https://example.com/ep1.mp3",
                "tags": ["repo"],
                "one_liner": "Repo tightening.",
                "summary": ["bullet"],
                "key_claims": ["claim"],
                "score": 5,
            }
        }
    }
    payload_json, lookup = build_queue_payload(pending)
    assert '"id": "guid-1"' in payload_json
    assert '"feed_name": "Odd Lots"' in payload_json
    assert lookup == {"guid-1": pending["queued"]["guid-1"]}


def test_reshape_retries_after_rejected_response_and_succeeds() -> None:
    with patch(
        "podcast_fetcher.synthesize.run_claude",
        side_effect=["I wrote a markdown digest instead of JSON", CLEAN_JSON],
    ) as mock_run_claude:
        brief = _reshape_to_brief("some analysis text", "reshape instructions", claude_model=None)

    assert brief.headline == "Fed reserves near $2.9tn, QT endgame in focus."
    assert mock_run_claude.call_count == 2
    # the retry's stdin must include the rejected output and why it was rejected
    second_call_stdin = mock_run_claude.call_args_list[1].args[1]
    assert "YOUR PREVIOUS RESPONSE WAS REJECTED" in second_call_stdin
    assert "I wrote a markdown digest instead of JSON" in second_call_stdin


def test_reshape_gives_up_after_max_attempts() -> None:
    with patch(
        "podcast_fetcher.synthesize.run_claude",
        side_effect=["not json"] * _MAX_RESHAPE_ATTEMPTS,
    ) as mock_run_claude:
        with pytest.raises(LLMParseError):
            _reshape_to_brief("some analysis text", "reshape instructions", claude_model=None)

    assert mock_run_claude.call_count == _MAX_RESHAPE_ATTEMPTS


def test_reshape_succeeds_first_try_without_retry() -> None:
    with patch("podcast_fetcher.synthesize.run_claude", side_effect=[CLEAN_JSON]) as mock_run_claude:
        brief = _reshape_to_brief("some analysis text", "reshape instructions", claude_model=None)

    assert brief.headline == "Fed reserves near $2.9tn, QT endgame in focus."
    assert mock_run_claude.call_count == 1


# --- Lenient fallback: real invented schemas captured during live testing ---
#
# These are the ACTUAL alternate shapes Claude returned across several
# real (unmocked) test runs when asked for the canonical schema -- kept
# verbatim as regression fixtures so the lenient parser is proven
# against reality, not just hand-built examples.

REAL_VARIANT_1 = {
    "digest_title": "Liquidity and Spread Dynamics Across Rates and Structured Credit",
    "episode_count": 2,
    "episodes": [
        {"id": "smoke-1", "feed_name": "Eurodollar University", "title": "Reserves, QT, and the Repo Market"},
        {"id": "smoke-2", "feed_name": "Cloud 9fin", "title": "CLO Equity Returns in a Tightening Market"},
    ],
    "cross_episode_summary": (
        "Both episodes examine how shifting liquidity conditions are reshaping credit and funding markets."
    ),
    "themes": [
        {
            "theme": "Spread compression vs. funding stress",
            "description": "A tension between tightening risk spreads and widening funding-market spreads.",
            "episodes": ["smoke-1", "smoke-2"],
        },
        {
            "theme": "Fed policy transmission to credit",
            "description": "QT and the reserve path set the funding backdrop against which credit returns are earned.",
            "episodes": ["smoke-1", "smoke-2"],
        },
    ],
    "connections": [{"from": "smoke-1", "to": "smoke-2", "relationship": "Funding tightening conditions credit."}],
    "watch_items": ["SOFR-OIS spread as an early signal of collateral scarcity."],
    "combined_tags": ["repo", "SOFR", "QT", "CLO"],
}

REAL_VARIANT_2 = {
    "headline": "Podcast Digest — Funding & Financing Desk",
    "bottom_line": "Collateral and balance sheet are getting scarce while credit risk is getting cheap.",
    "items": [
        {
            "number": 1,
            "topic": "Reserves, QT, and repo",
            "relevance": "on-book",
            "source": "Eurodollar University",
            "signal": "Reserves pegged at ~$2.9tn; the Fed must slow or stop QT within ~2 FOMC meetings.",
            "actions": [
                "Treat SOFR-OIS widening as the leading indicator, not the reserve level.",
                "Lock term funding across the turn early.",
            ],
            "caveat": "The standing repo facility changes the 2019 analogy.",
            "confidence": "Directionally credible.",
        },
        {
            "number": 2,
            "topic": "CLO equity / loan spreads",
            "relevance": "adjacent",
            "source": "Cloud 9fin",
            "signal": "CLO equity arb is compressing as loan spreads tighten.",
            "actions": ["Recognize the same divergence as item 1."],
            "caveat": None,
            "confidence": "Lower direct relevance.",
        },
    ],
    "desk_takeaways": ["Be paid to provide funding into quarter-ends.", "Do not chase carry in structured credit."],
    "tail_risk": "A funding-led event forcing deleveraging through the currently-calm credit books.",
    "disclaimer": "Every quantitative claim is sourced to podcast guests and flagged as estimate/opinion.",
}


def test_lenient_fallback_handles_real_variant_1() -> None:
    brief = parse_brief(json.dumps(REAL_VARIANT_1))

    assert brief.headline == REAL_VARIANT_1["digest_title"]
    assert brief.tldr == REAL_VARIANT_1["cross_episode_summary"]
    assert len(brief.themes) == 2
    assert brief.themes[0].name == "Spread compression vs. funding stress"
    assert len(brief.themes[0].points) == 1
    assert brief.themes[0].points[0].text == REAL_VARIANT_1["themes"][0]["description"]
    assert brief.themes[0].points[0].source_ids == ["smoke-1", "smoke-2"]
    assert brief.watch == REAL_VARIANT_1["watch_items"]


def test_lenient_fallback_handles_real_variant_2() -> None:
    brief = parse_brief(json.dumps(REAL_VARIANT_2))

    assert brief.headline == REAL_VARIANT_2["headline"]
    assert len(brief.themes) == 2
    assert brief.themes[0].name == "Reserves, QT, and repo"
    assert brief.themes[0].points[0].text == "Treat SOFR-OIS widening as the leading indicator, not the reserve level."
    assert brief.learned == REAL_VARIANT_2["desk_takeaways"]


def test_lenient_fallback_never_treats_source_id_list_as_point_text() -> None:
    # regression: the "episodes": ["smoke-1", "smoke-2"] list in variant 1's
    # themes must become source_ids, never two fake points reading
    # "smoke-1" / "smoke-2".
    brief = parse_brief(json.dumps(REAL_VARIANT_1))
    all_point_texts = [p.text for theme in brief.themes for p in theme.points]
    assert "smoke-1" not in all_point_texts
    assert "smoke-2" not in all_point_texts


def test_completely_unusable_response_still_raises() -> None:
    with pytest.raises(LLMParseError):
        parse_brief(json.dumps({"unrelated_key": 42, "another": [1, 2, 3]}))


def test_lenient_fallback_never_crashes_on_odd_shapes() -> None:
    odd_shapes = [
        {},
        {"a": None},
        {"themes": "not a list"},
        {"themes": [1, 2, 3]},
        {"headline": 123, "themes": [{"name": "x", "points": "not a list"}]},
    ]
    for shape in odd_shapes:
        try:
            parse_brief(json.dumps(shape))
        except LLMParseError:
            pass  # acceptable -- must not raise anything else (e.g. KeyError, TypeError)
