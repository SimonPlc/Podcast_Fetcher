from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from podcast_fetcher.models import Feed


_VALID_KINDS = ("podcast", "article")


class FeedsConfigError(ValueError):
    """Raised when feeds.yaml is missing required structure."""


def load_feeds(path: str | Path) -> list[Feed]:
    """Load and validate the curated feed list from a feeds.yaml file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "feeds" not in raw:
        raise FeedsConfigError(f"{path}: expected a top-level 'feeds' list")

    entries = raw["feeds"]
    if not isinstance(entries, list) or not entries:
        raise FeedsConfigError(f"{path}: 'feeds' must be a non-empty list")

    feeds: list[Feed] = []
    for index, entry in enumerate(entries):
        feeds.append(_parse_entry(entry, index, path))
    return feeds


def _parse_entry(entry: Any, index: int, path: str | Path) -> Feed:
    if not isinstance(entry, dict):
        raise FeedsConfigError(f"{path}: feeds[{index}] must be a mapping")
    missing = [key for key in ("name", "url", "tier") if not entry.get(key)]
    if missing:
        raise FeedsConfigError(f"{path}: feeds[{index}] missing required key(s): {', '.join(missing)}")

    kind = entry.get("kind", "podcast")
    if kind not in _VALID_KINDS:
        raise FeedsConfigError(f"{path}: feeds[{index}] has invalid kind {kind!r}, expected one of {_VALID_KINDS}")

    min_body_chars = entry.get("min_body_chars")
    if min_body_chars is not None and not isinstance(min_body_chars, int):
        raise FeedsConfigError(f"{path}: feeds[{index}] min_body_chars must be an integer, got {min_body_chars!r}")

    return Feed(
        name=entry["name"],
        url=entry["url"],
        tier=entry["tier"],
        kind=kind,
        min_body_chars=min_body_chars,
    )
