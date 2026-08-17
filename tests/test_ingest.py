from __future__ import annotations

import feedparser

from podcast_fetcher.ingest import parse_entries
from podcast_fetcher.models import Feed

FEED = Feed(name="Odd Lots", url="https://example.com/feed.rss", tier="plumbing")

RSS_WITH_ENCLOSURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Odd Lots</title>
<item>
  <title>Episode One</title>
  <guid>urn:uuid:abc-123</guid>
  <pubDate>Mon, 17 Aug 2026 09:00:00 GMT</pubDate>
  <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="123"/>
</item>
</channel></rss>
"""

RSS_NO_ENCLOSURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Odd Lots</title>
<item>
  <title>Show Notes Only</title>
  <guid>urn:uuid:no-audio</guid>
  <pubDate>Mon, 17 Aug 2026 09:00:00 GMT</pubDate>
</item>
</channel></rss>
"""

RSS_MISSING_DATE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Odd Lots</title>
<item>
  <title>Undated Episode</title>
  <guid>urn:uuid:undated</guid>
  <enclosure url="https://example.com/undated.mp3" type="audio/mpeg" length="123"/>
</item>
</channel></rss>
"""

RSS_NO_GUID = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Odd Lots</title>
<item>
  <title>No Guid Episode</title>
  <pubDate>Mon, 17 Aug 2026 09:00:00 GMT</pubDate>
  <enclosure url="https://example.com/noguid.mp3" type="audio/mpeg" length="123"/>
</item>
</channel></rss>
"""


def test_parses_episode_with_enclosure_and_date() -> None:
    parsed = feedparser.parse(RSS_WITH_ENCLOSURE)
    episodes = parse_entries(parsed, FEED)
    assert len(episodes) == 1
    ep = episodes[0]
    assert ep.feed_name == "Odd Lots"
    assert ep.tier == "plumbing"
    assert ep.title == "Episode One"
    assert ep.url == "https://example.com/ep1.mp3"
    assert ep.guid == "urn:uuid:abc-123"
    assert ep.published is not None
    assert ep.published.year == 2026
    assert ep.published.month == 8
    assert ep.published.day == 17


def test_skips_entry_without_audio_enclosure() -> None:
    parsed = feedparser.parse(RSS_NO_ENCLOSURE)
    episodes = parse_entries(parsed, FEED)
    assert episodes == []


def test_missing_publish_date_does_not_crash() -> None:
    parsed = feedparser.parse(RSS_MISSING_DATE)
    episodes = parse_entries(parsed, FEED)
    assert len(episodes) == 1
    assert episodes[0].published is None


def test_falls_back_to_url_when_no_guid() -> None:
    parsed = feedparser.parse(RSS_NO_GUID)
    episodes = parse_entries(parsed, FEED)
    assert len(episodes) == 1
    assert episodes[0].guid == "https://example.com/noguid.mp3"


def test_empty_feed_returns_empty_list() -> None:
    parsed = feedparser.parse("<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>")
    assert parse_entries(parsed, FEED) == []
