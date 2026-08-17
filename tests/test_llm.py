from __future__ import annotations

import pytest

from podcast_fetcher.llm import LLMParseError, parse_json_object


def test_parses_clean_json_object() -> None:
    assert parse_json_object('{"a": 1, "b": [2, 3]}') == {"a": 1, "b": [2, 3]}


def test_parses_json_wrapped_in_prose() -> None:
    raw = 'Sure, here is the result:\n{"a": 1}\nHope that helps!'
    assert parse_json_object(raw) == {"a": 1}


def test_parses_json_in_markdown_fence() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert parse_json_object(raw) == {"a": 1}


def test_parses_json_in_unlabeled_fence() -> None:
    raw = '```\n{"a": 1}\n```'
    assert parse_json_object(raw) == {"a": 1}


def test_handles_nested_braces() -> None:
    raw = 'blah {"a": {"nested": 1}, "b": 2} blah'
    assert parse_json_object(raw) == {"a": {"nested": 1}, "b": 2}


def test_raises_on_no_json_present() -> None:
    with pytest.raises(LLMParseError):
        parse_json_object("I refuse to answer in JSON today.")


def test_raises_on_json_array_not_object() -> None:
    with pytest.raises(LLMParseError):
        parse_json_object("[1, 2, 3]")


def test_raises_on_truncated_json() -> None:
    with pytest.raises(LLMParseError):
        parse_json_object('{"a": 1, "b":')
