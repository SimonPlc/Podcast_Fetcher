from __future__ import annotations

from podcast_fetcher.config import load_config


def test_defaults_applied_when_env_empty() -> None:
    config = load_config({})
    assert config.run_mode == "collect"
    assert config.whisper_model == "small"
    assert config.max_recent_days == 3
    assert config.episodes_per_feed == 2
    assert config.max_episodes_per_run == 20
    assert config.min_score == 3
    assert config.max_transcript_chars == 60_000
    assert config.max_articles_per_digest == 10
    assert config.discovery_limit == 25
    assert config.claude_model is None
    assert config.email_to is None
    assert config.email_from is None


def test_env_values_override_defaults() -> None:
    config = load_config(
        {
            "RUN_MODE": "digest",
            "WHISPER_MODEL": "base",
            "MAX_RECENT_DAYS": "5",
            "EPISODES_PER_FEED": "1",
            "MAX_EPISODES_PER_RUN": "40",
            "MIN_SCORE": "4",
            "MAX_TRANSCRIPT_CHARS": "10000",
            "MAX_ARTICLES_PER_DIGEST": "5",
            "DISCOVERY_LIMIT": "50",
            "CLAUDE_MODEL": "claude-opus-5",
            "EMAIL_TO": "simon@example.com",
            "EMAIL_FROM": "bot@example.com",
        }
    )
    assert config.run_mode == "digest"
    assert config.whisper_model == "base"
    assert config.max_recent_days == 5
    assert config.episodes_per_feed == 1
    assert config.max_episodes_per_run == 40
    assert config.min_score == 4
    assert config.max_transcript_chars == 10_000
    assert config.max_articles_per_digest == 5
    assert config.discovery_limit == 50
    assert config.claude_model == "claude-opus-5"
    assert config.email_to == "simon@example.com"
    assert config.email_from == "bot@example.com"


def test_empty_string_env_values_treated_as_unset() -> None:
    config = load_config({"CLAUDE_MODEL": "", "EMAIL_TO": ""})
    assert config.claude_model is None
    assert config.email_to is None
