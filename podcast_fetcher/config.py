from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

DEFAULT_WHISPER_MODEL = "small"
DEFAULT_MAX_RECENT_DAYS = 3
DEFAULT_EPISODES_PER_FEED = 2
DEFAULT_MIN_SCORE = 3
DEFAULT_MAX_EPISODES_PER_RUN = 20
DEFAULT_MAX_TRANSCRIPT_CHARS = 60_000
DEFAULT_MAX_ARTICLES_PER_DIGEST = 10
DEFAULT_DISCOVERY_LIMIT = 25
# Candidates are scored in independent chunks of this size rather than one
# giant call: a first sweep yields ~225 surviving candidates, and demanding
# one reply covering all of them is fragile (see discover.score_in_batches).
DEFAULT_DISCOVERY_BATCH_SIZE = 25


@dataclass(frozen=True)
class Config:
    run_mode: str
    whisper_model: str
    max_recent_days: int
    episodes_per_feed: int
    max_episodes_per_run: int
    min_score: int
    max_transcript_chars: int
    max_articles_per_digest: int
    discovery_limit: int
    discovery_batch_size: int
    claude_model: str | None
    email_to: str | None
    email_from: str | None


def load_config(env: Mapping[str, str]) -> Config:
    """Build a Config from environment variables, applying documented defaults."""
    return Config(
        run_mode=env.get("RUN_MODE", "collect"),
        whisper_model=env.get("WHISPER_MODEL", DEFAULT_WHISPER_MODEL),
        max_recent_days=int(env.get("MAX_RECENT_DAYS", DEFAULT_MAX_RECENT_DAYS)),
        episodes_per_feed=int(env.get("EPISODES_PER_FEED", DEFAULT_EPISODES_PER_FEED)),
        max_episodes_per_run=int(env.get("MAX_EPISODES_PER_RUN", DEFAULT_MAX_EPISODES_PER_RUN)),
        min_score=int(env.get("MIN_SCORE", DEFAULT_MIN_SCORE)),
        max_transcript_chars=int(env.get("MAX_TRANSCRIPT_CHARS", DEFAULT_MAX_TRANSCRIPT_CHARS)),
        max_articles_per_digest=int(env.get("MAX_ARTICLES_PER_DIGEST", DEFAULT_MAX_ARTICLES_PER_DIGEST)),
        discovery_limit=int(env.get("DISCOVERY_LIMIT", DEFAULT_DISCOVERY_LIMIT)),
        discovery_batch_size=int(env.get("DISCOVERY_BATCH_SIZE", DEFAULT_DISCOVERY_BATCH_SIZE)),
        claude_model=env.get("CLAUDE_MODEL") or None,
        email_to=env.get("EMAIL_TO") or None,
        email_from=env.get("EMAIL_FROM") or None,
    )
