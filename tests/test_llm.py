from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from podcast_fetcher.llm import (
    ClaudeUnavailableError,
    LLMParseError,
    check_claude_available,
    parse_json_object,
    run_claude,
)


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


class _FakeCompletedProcess:
    def __init__(self) -> None:
        self.returncode = 0
        self.stdout = '{"ok": true}'
        self.stderr = ""


def test_run_claude_strips_claude_code_session_env_vars(monkeypatch: Any) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "leaked-session-id")
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-should-survive")

    with patch("podcast_fetcher.llm.subprocess.run", return_value=_FakeCompletedProcess()) as mock_run:
        run_claude("instructions", "stdin text")

    passed_env = mock_run.call_args.kwargs["env"]
    assert "CLAUDE_CODE_SESSION_ID" not in passed_env
    assert "CLAUDE_CODE_CHILD_SESSION" not in passed_env
    assert passed_env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-should-survive"
    assert passed_env["PATH"] == "/usr/bin"


def test_run_claude_strips_gmail_send_secrets_from_subprocess_env(monkeypatch: Any) -> None:
    # The extract/score subprocess is fed untrusted transcript text and never
    # sends email, so the Gmail send credentials must not reach it -- only its
    # own auth token should survive.
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-should-survive")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "gmail-client-secret")
    monkeypatch.setenv("GMAIL_REFRESH_TOKEN", "gmail-refresh-token")
    monkeypatch.setenv("EMAIL_TO", "simon@example.com")

    with patch("podcast_fetcher.llm.subprocess.run", return_value=_FakeCompletedProcess()) as mock_run:
        run_claude("instructions", "stdin text")

    passed_env = mock_run.call_args.kwargs["env"]
    assert "GMAIL_CLIENT_SECRET" not in passed_env
    assert "GMAIL_REFRESH_TOKEN" not in passed_env
    assert "EMAIL_TO" not in passed_env
    assert passed_env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-should-survive"


# --- Issue #9: our-side vs episode-side failure ---


class _FakeFailedProcess:
    def __init__(self) -> None:
        self.returncode = 1
        self.stdout = ""
        self.stderr = "error: invalid API key · Please run /login"


def test_run_claude_raises_claude_unavailable_on_nonzero_exit() -> None:
    with patch("podcast_fetcher.llm.subprocess.run", return_value=_FakeFailedProcess()):
        with pytest.raises(ClaudeUnavailableError):
            run_claude("instructions", "stdin text")


def test_run_claude_raises_claude_unavailable_when_executable_missing() -> None:
    with patch("podcast_fetcher.llm.subprocess.run", side_effect=FileNotFoundError("no such file")):
        with pytest.raises(ClaudeUnavailableError):
            run_claude("instructions", "stdin text")


def test_run_claude_raises_claude_unavailable_on_timeout() -> None:
    # A hung CLI is our-side, not the episode's fault: it must raise
    # ClaudeUnavailableError (defer) rather than a bare TimeoutExpired
    # that collect.py would burn as an episode-side failure.
    timeout_exc = subprocess.TimeoutExpired(cmd="claude", timeout=600)
    with patch("podcast_fetcher.llm.subprocess.run", side_effect=timeout_exc):
        with pytest.raises(ClaudeUnavailableError):
            run_claude("instructions", "stdin text")


def test_check_claude_available_makes_one_cheap_run_claude_call() -> None:
    calls: list[tuple[str, str]] = []

    def fake_run(prompt: str, stdin_text: str, *, model: str | None = None, timeout: int = 600) -> str:
        calls.append((prompt, stdin_text))
        return "OK"

    check_claude_available(run=fake_run)
    assert len(calls) == 1


def test_check_claude_available_propagates_claude_unavailable_error() -> None:
    def failing_run(prompt: str, stdin_text: str, *, model: str | None = None, timeout: int = 600) -> str:
        raise ClaudeUnavailableError("claude CLI exited 1: not logged in")

    with pytest.raises(ClaudeUnavailableError):
        check_claude_available(run=failing_run)
