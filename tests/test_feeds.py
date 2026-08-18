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


def test_entry_without_kind_defaults_to_podcast(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text(
        """
feeds:
  - name: "Odd Lots"
    url: "https://example.com/oddlots.rss"
    tier: "plumbing"
""",
        encoding="utf-8",
    )
    feeds = load_feeds(path)
    assert feeds[0].kind == "podcast"
    assert feeds[0].min_body_chars is None


def test_entry_with_article_kind_and_min_body_chars(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text(
        """
feeds:
  - name: "BIS working papers"
    url: "https://example.com/bis.rss"
    tier: "macro"
    kind: "article"
    min_body_chars: 400
""",
        encoding="utf-8",
    )
    feeds = load_feeds(path)
    assert feeds == [
        Feed(
            name="BIS working papers",
            url="https://example.com/bis.rss",
            tier="macro",
            kind="article",
            min_body_chars=400,
        )
    ]


def test_entry_with_invalid_kind_raises(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text(
        """
feeds:
  - name: "Odd Lots"
    url: "https://example.com/oddlots.rss"
    tier: "plumbing"
    kind: "video"
""",
        encoding="utf-8",
    )
    with pytest.raises(FeedsConfigError, match="kind"):
        load_feeds(path)


def test_entry_with_non_integer_min_body_chars_raises(tmp_path: Path) -> None:
    path = tmp_path / "feeds.yaml"
    path.write_text(
        """
feeds:
  - name: "Odd Lots"
    url: "https://example.com/oddlots.rss"
    tier: "plumbing"
    kind: "article"
    min_body_chars: "a lot"
""",
        encoding="utf-8",
    )
    with pytest.raises(FeedsConfigError, match="min_body_chars"):
        load_feeds(path)


def test_loads_the_real_repo_feeds_yaml() -> None:
    repo_feeds = Path(__file__).resolve().parent.parent / "feeds.yaml"
    feeds = load_feeds(repo_feeds)
    assert len(feeds) >= 20
    names = {f.name for f in feeds}
    assert "Odd Lots" in names
    assert all(f.url.startswith("https://") for f in feeds)
    assert all(f.tier for f in feeds)

    articles = [f for f in feeds if f.kind == "article"]
    assert len(articles) >= 10
    assert {"NY Fed Liberty Street Economics", "Fed FEDS Notes"} <= {f.name for f in articles}
    assert "FT" not in names  # excluded on T&C/robots.txt grounds, see feeds.yaml
    abstract_feeds = [f for f in articles if f.min_body_chars is not None and f.min_body_chars < 1000]
    assert {"BIS working papers", "Fed FEDS Notes"} <= {f.name for f in abstract_feeds}
    assert all(f.kind == "podcast" for f in feeds if f.name == "Odd Lots")


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
