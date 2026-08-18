from __future__ import annotations

from datetime import datetime, timedelta, timezone

import feedparser

from podcast_fetcher.articles import article_hash, parse_article_entries, select_articles, strip_html
from podcast_fetcher.models import Article, Feed

NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)

ARTICLE_FEED = Feed(name="NY Fed Liberty Street Economics", url="https://example.com/feed.rss", tier="plumbing", kind="article")
ABSTRACT_FEED = Feed(
    name="BIS working papers",
    url="https://example.com/bis.rss",
    tier="macro",
    kind="article",
    min_body_chars=400,
)

_LONG_BODY = "Reserves are getting scarce in the repo market. " * 60  # well over 2500 chars
_SHORT_TEASER = "Read more on our site."


def rss(*, link: str = "https://example.com/a1", body: str | None = _LONG_BODY, summary: str | None = None) -> str:
    content_tag = f"<content:encoded><![CDATA[<p>{body}</p>]]></content:encoded>" if body is not None else ""
    summary_tag = f"<description>{summary}</description>" if summary is not None else ""
    return f"""<?xml version="1.0"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
<title>Feed</title>
<item>
  <title>Reserves Update</title>
  <link>{link}</link>
  <pubDate>Mon, 17 Aug 2026 09:00:00 GMT</pubDate>
  {content_tag}
  {summary_tag}
</item>
</channel></rss>
"""


def art(
    feed: str = "NY Fed Liberty Street Economics",
    url: str = "https://example.com/a1",
    source_kind: str = "article",
    days_ago: float | None = 0,
) -> Article:
    published = NOW - timedelta(days=days_ago) if days_ago is not None else None
    return Article(
        feed_name=feed,
        tier="plumbing",
        title="Reserves Update",
        url=url,
        body="body",
        published=published,
        source_kind=source_kind,
    )


# --- strip_html ---


def test_strip_html_removes_tags_and_unescapes_entities() -> None:
    assert strip_html("<p>Repo &amp; SOFR &mdash; up 5bp.</p>") == "Repo & SOFR — up 5bp."


def test_strip_html_drops_script_and_style_blocks_entirely() -> None:
    raw = "<p>Visible</p><script>evil()</script><style>.x{color:red}</style>"
    assert strip_html(raw) == "Visible"


def test_strip_html_collapses_whitespace() -> None:
    assert strip_html("<p>a</p>\n\n<p>b</p>") == "a b"


# --- article_hash ---


def test_article_hash_is_stable_for_same_inputs() -> None:
    assert article_hash("Odd Lots", "https://x/1") == article_hash("Odd Lots", "https://x/1")


def test_article_hash_differs_by_feed_name() -> None:
    assert article_hash("Odd Lots", "https://x/1") != article_hash("Unhedged", "https://x/1")


def test_article_hash_differs_by_url() -> None:
    assert article_hash("Odd Lots", "https://x/1") != article_hash("Odd Lots", "https://x/2")


# --- parse_article_entries ---


def test_parses_article_body_from_content_encoded() -> None:
    parsed = feedparser.parse(rss())
    articles = parse_article_entries(parsed, ARTICLE_FEED)
    assert len(articles) == 1
    assert articles[0].title == "Reserves Update"
    assert articles[0].url == "https://example.com/a1"
    assert "Reserves are getting scarce" in articles[0].body
    assert "<p>" not in articles[0].body
    assert articles[0].source_kind == "article"


def test_falls_back_to_summary_when_no_content_encoded() -> None:
    parsed = feedparser.parse(rss(body=None, summary=_LONG_BODY))
    articles = parse_article_entries(parsed, ARTICLE_FEED)
    assert len(articles) == 1
    assert "Reserves are getting scarce" in articles[0].body


def test_entry_below_min_body_chars_is_skipped() -> None:
    parsed = feedparser.parse(rss(body=_SHORT_TEASER))
    articles = parse_article_entries(parsed, ARTICLE_FEED)
    assert articles == []


def test_entry_without_link_is_skipped() -> None:
    xml = rss().replace("<link>https://example.com/a1</link>", "")
    parsed = feedparser.parse(xml)
    assert parse_article_entries(parsed, ARTICLE_FEED) == []


def test_entry_with_no_body_at_all_is_skipped() -> None:
    parsed = feedparser.parse(rss(body=None, summary=None))
    assert parse_article_entries(parsed, ARTICLE_FEED) == []


def test_low_min_body_chars_override_admits_short_abstract() -> None:
    abstract_body = "This paper studies repo market functioning during stress. " * 8  # >400, <2500 chars
    assert len(abstract_body) > 400
    assert len(abstract_body) < 2500
    parsed = feedparser.parse(rss(body=abstract_body))
    articles = parse_article_entries(parsed, ABSTRACT_FEED)
    assert len(articles) == 1
    assert articles[0].source_kind == "abstract"


def test_default_threshold_rejects_what_a_low_override_would_admit() -> None:
    abstract_body = "This paper studies repo market functioning during stress. " * 8
    parsed = feedparser.parse(rss(body=abstract_body))
    assert parse_article_entries(parsed, ARTICLE_FEED) == []


def test_empty_feed_returns_empty_list() -> None:
    parsed = feedparser.parse("<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>")
    assert parse_article_entries(parsed, ARTICLE_FEED) == []


# --- select_articles ---


def test_selects_recent_unseen_article() -> None:
    a = art(url="https://x/1", days_ago=1)
    result = select_articles({"Feed": [a]}, set(), NOW, max_recent_days=3, max_articles=10)
    assert result == [a]


def test_excludes_article_older_than_recency_window() -> None:
    a = art(url="https://x/1", days_ago=10)
    result = select_articles({"Feed": [a]}, set(), NOW, max_recent_days=3, max_articles=10)
    assert result == []


def test_excludes_already_seen_article_by_hash() -> None:
    a = art(feed="Feed", url="https://x/1", days_ago=1)
    seen = {article_hash("Feed", "https://x/1")}
    result = select_articles({"Feed": [a]}, seen, NOW, max_recent_days=3, max_articles=10)
    assert result == []


def test_missing_published_date_does_not_crash_and_is_included() -> None:
    a = art(url="https://x/1", days_ago=None)
    result = select_articles({"Feed": [a]}, set(), NOW, max_recent_days=3, max_articles=10)
    assert result == [a]


def test_cap_keeps_newest_across_feeds() -> None:
    feeds = {
        "A": [art(feed="A", url="https://x/a", days_ago=1)],
        "B": [art(feed="B", url="https://x/b", days_ago=0.5)],
        "C": [art(feed="C", url="https://x/c", days_ago=0.1)],
    }
    result = select_articles(feeds, set(), NOW, max_recent_days=3, max_articles=2)
    assert len(result) == 2
    assert [a.url for a in result] == ["https://x/c", "https://x/b"]


def test_empty_feeds_returns_empty_list() -> None:
    assert select_articles({}, set(), NOW, max_recent_days=3, max_articles=10) == []
