from __future__ import annotations

from pathlib import Path

import pytest

from podcast_fetcher.feeds import FeedsConfigError, load_feeds
from podcast_fetcher.models import Feed


def test_loads_valid_feeds(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text(
        """
feeds:
  - name: "Odd Lots"
    url: "https://example.com/oddlots.rss"
    tier: "plumbing"
  - name: "Unhedged"
    url: "https://example.com/unhedged.rss"
    tier: "credit"
""",
        encoding="utf-8",
    )
    feeds = load_feeds(path)
    assert feeds == [
        Feed(name="Odd Lots", url="https://example.com/oddlots.rss", tier="plumbing"),
        Feed(name="Unhedged", url="https://example.com/unhedged.rss", tier="credit"),
    ]


def test_loads_the_real_repo_feeds_yaml() -> None:
    repo_feeds = Path(__file__).resolve().parent.parent / "feeds.yaml"
    feeds = load_feeds(repo_feeds)
    assert len(feeds) >= 20
    names = {f.name for f in feeds}
    assert "Odd Lots" in names
    assert all(f.url.startswith("https://") for f in feeds)
    assert all(f.tier for f in feeds)


def test_missing_top_level_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text("not_feeds: []\n", encoding="utf-8")
    with pytest.raises(FeedsConfigError):
        load_feeds(path)


def test_empty_feeds_list_raises(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text("feeds: []\n", encoding="utf-8")
    with pytest.raises(FeedsConfigError):
        load_feeds(path)


def test_entry_missing_required_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text(
        """
feeds:
  - name: "Odd Lots"
    url: "https://example.com/oddlots.rss"
""",
        encoding="utf-8",
    )
    with pytest.raises(FeedsConfigError, match="tier"):
        load_feeds(path)
