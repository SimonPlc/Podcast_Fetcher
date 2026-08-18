from __future__ import annotations

import pytest

from podcast_fetcher.extract import parse_extraction, render_extract_prompt
from podcast_fetcher.llm import LLMParseError
from podcast_fetcher.models import ExtractResult

CLEAN_JSON = """{
  "score": 4,
  "one_liner": "Fed balance sheet runoff discussion, directly relevant to repo.",
  "tags": ["repo", "Fed", "QT"],
  "summary": ["Point one.", "Point two."],
  "key_claims": ["Reserves are approaching $2.9tn per the guest."]
}"""

PROSE_WRAPPED_JSON = f"""Here is my analysis of the episode:

{CLEAN_JSON}

Let me know if you need anything else!"""

FENCED_JSON = f"""```json
{CLEAN_JSON}
```"""

MALFORMED = "I couldn't parse this episode, sorry."

MISSING_FIELD_JSON = """{"score": 4, "one_liner": "x", "tags": [], "summary": []}"""

WRONG_TYPE_JSON = """{"score": "high", "one_liner": "x", "tags": [], "summary": [], "key_claims": []}"""

SCORE_OUT_OF_RANGE_JSON = """{"score": 9, "one_liner": "x", "tags": [], "summary": [], "key_claims": []}"""


def test_parses_clean_json() -> None:
    result = parse_extraction(CLEAN_JSON)
    assert result == ExtractResult(
        score=4,
        one_liner="Fed balance sheet runoff discussion, directly relevant to repo.",
        tags=["repo", "Fed", "QT"],
        summary=["Point one.", "Point two."],
        key_claims=["Reserves are approaching $2.9tn per the guest."],
    )


def test_parses_json_wrapped_in_prose() -> None:
    result = parse_extraction(PROSE_WRAPPED_JSON)
    assert result.score == 4


def test_parses_json_in_markdown_fence() -> None:
    result = parse_extraction(FENCED_JSON)
    assert result.score == 4


def test_raises_on_malformed_output() -> None:
    with pytest.raises(LLMParseError):
        parse_extraction(MALFORMED)


def test_raises_on_missing_required_field() -> None:
    with pytest.raises(LLMParseError):
        parse_extraction(MISSING_FIELD_JSON)


def test_raises_on_wrong_field_type() -> None:
    with pytest.raises(LLMParseError):
        parse_extraction(WRONG_TYPE_JSON)


def test_raises_on_score_out_of_range() -> None:
    with pytest.raises(LLMParseError):
        parse_extraction(SCORE_OUT_OF_RANGE_JSON)


# --- render_extract_prompt: the shared prompt tells the model which kind of
# source item it's reading (transcript, article, or abstract) -- ticket #7.


def test_render_extract_prompt_fills_transcript_kind() -> None:
    prompt = render_extract_prompt("transcript", prompt="You are reading {{KIND}}.")
    assert prompt == "You are reading a transcript of one podcast episode."


def test_render_extract_prompt_fills_article_kind() -> None:
    prompt = render_extract_prompt("article", prompt="You are reading {{KIND}}.")
    assert "full text of one written article" in prompt


def test_render_extract_prompt_fills_abstract_kind_and_notes_it_is_not_the_full_paper() -> None:
    prompt = render_extract_prompt("abstract", prompt="You are reading {{KIND}}.")
    assert "abstract" in prompt
    assert "not the full paper" in prompt


def test_render_extract_prompt_leaves_json_braces_untouched() -> None:
    # Regression guard: this must be a plain string replace, not str.format --
    # the real prompt's JSON example is full of literal `{`/`}` characters
    # that .format would try (and fail) to interpret as fields.
    template = 'kind={{KIND}}, example={"score": 4}'
    prompt = render_extract_prompt("transcript", prompt=template)
    assert '{"score": 4}' in prompt


def test_render_extract_prompt_reads_the_real_prompt_file() -> None:
    prompt = render_extract_prompt("abstract")
    assert "{{KIND}}" not in prompt
    assert "STRICT JSON" in prompt
