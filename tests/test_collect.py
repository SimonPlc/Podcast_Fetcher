from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Iterator

import feedparser

from podcast_fetcher.collect import run_collect
from podcast_fetcher.config import load_config
from podcast_fetcher.llm import ClaudeUnavailableError, LLMParseError
from podcast_fetcher.models import Episode, ExtractResult, Feed

NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)

FEED_A = Feed(name="Odd Lots", url="https://example.com/oddlots.rss", tier="plumbing")
FEED_B = Feed(name="Unhedged", url="https://example.com/unhedged.rss", tier="credit")
FEED_C = Feed(name="Macro Musings", url="https://example.com/macromusings.rss", tier="macro")
ARTICLE_FEED = Feed(
    name="Concoda",
    url="https://example.com/concoda.rss",
    tier="plumbing",
    kind="article",
)


def rss(guid: str, title: str, pub_date: str) -> str:
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Feed</title>
<item>
  <title>{title}</title>
  <guid>{guid}</guid>
  <pubDate>{pub_date}</pubDate>
  <enclosure url="https://example.com/{guid}.mp3" type="audio/mpeg" length="1"/>
</item>
</channel></rss>
"""


RECENT_PUBDATE = "Sun, 16 Aug 2026 09:00:00 GMT"  # 1 day before NOW
OLD_PUBDATE = "Mon, 01 Jun 2026 09:00:00 GMT"  # weeks before NOW


def pubdate(days_ago: float) -> str:
    """An RFC 2822 pubDate `days_ago` before NOW, for tests (issue #9)
    that need several distinct-but-recent episodes in a controlled
    oldest/newest order.
    """
    return format_datetime(NOW - timedelta(days=days_ago))


def fake_fetch(feed_xml_by_url: dict[str, str]) -> Any:
    def _fetch(url: str) -> Any:
        return feedparser.parse(feed_xml_by_url[url])

    return _fetch


@contextmanager
def fake_download(url: str) -> Iterator[Path]:
    # Path reflects the source url so per-episode fakes can discriminate.
    yield Path(f"/fake/{url.rsplit('/', 1)[-1]}")


def fake_transcribe(path: Path, model: str) -> str:
    return "fake transcript text"


def fake_extract(score: int = 4) -> Any:
    def _extract(episode: Episode, transcript: str, *, claude_model: str | None = None) -> ExtractResult:
        return ExtractResult(
            score=score,
            one_liner=f"one-liner for {episode.title}",
            tags=["repo"],
            summary=["bullet one"],
            key_claims=["claim one"],
        )

    return _extract


def fake_preflight(*, model: str | None = None) -> None:
    """Default preflight fake: the Claude CLI is "up". Tests about
    selection/state/timing override extract/download/transcribe but
    never want a real subprocess call from the preflight check either,
    so this is wired in as run()'s default alongside the other fakes.
    """
    return None


def fixed_elapsed_clock(jump_seconds: float) -> Callable[[], float]:
    """A synthetic monotonic clock for testing the time budget (issue
    #9). Returns 0.0 on the first call -- run_collect's `started =
    clock()` capture -- and `jump_seconds` on every call after, so every
    in-loop elapsed check reports the same fixed elapsed duration
    without a real sleep. Callers pick `jump_seconds` past whatever
    COLLECT_TIME_BUDGET_MIN the test configures.
    """
    calls = {"n": 0}

    def _clock() -> float:
        value = 0.0 if calls["n"] == 0 else jump_seconds
        calls["n"] += 1
        return value

    return _clock


def run(feeds: list[Feed], config: Any, **overrides: Any) -> Any:
    """run_collect with harmless fakes for the whole processing pipeline
    by default, so tests about selection/state don't need real network,
    Whisper, or the Claude CLI. Pass e.g. extract=... to override.
    """
    kwargs: dict[str, Any] = dict(
        download=fake_download,
        transcribe=fake_transcribe,
        extract=fake_extract(),
        preflight=fake_preflight,
        now=NOW,
    )
    kwargs.update(overrides)
    return run_collect(feeds, config, **kwargs)


def test_run_collect_selects_new_recent_episodes(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE),
        FEED_B.url: rss("b1", "Unhedged Ep", RECENT_PUBDATE),
    }
    config = load_config({})
    result = run([FEED_A, FEED_B], config, fetch=fake_fetch(xml_by_url))
    assert {e.guid for e in result} == {"a1", "b1"}


def test_run_collect_excludes_old_episodes(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Old Ep", OLD_PUBDATE)}
    config = load_config({})
    result = run([FEED_A], config, fetch=fake_fetch(xml_by_url))
    assert result == []


def test_run_collect_excludes_already_processed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    # status=ok, matching every real processed record (issue #9: only a
    # terminal -- ok/failed -- record excludes; see store.terminal_ids).
    (tmp_path / "state" / "emailed_episodes.json").write_text(
        '{"processed": {"a1": {"feed": "Odd Lots", "title": "Old", "status": "ok"}}}', encoding="utf-8"
    )
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({})
    result = run([FEED_A], config, fetch=fake_fetch(xml_by_url))
    assert result == []


def test_run_collect_excludes_already_queued(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "pending_digest.json").write_text(
        '{"queued": {"a1": {"feed": "Odd Lots", "title": "Queued"}}}', encoding="utf-8"
    )
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({})
    result = run([FEED_A], config, fetch=fake_fetch(xml_by_url))
    assert result == []


def test_run_collect_survives_one_feed_failing(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)

    def flaky_fetch(url: str) -> Any:
        if url == FEED_A.url:
            raise ConnectionError("boom")
        return feedparser.parse(rss("b1", "Unhedged Ep", RECENT_PUBDATE))

    config = load_config({})
    result = run([FEED_A, FEED_B], config, fetch=flaky_fetch)
    assert {e.guid for e in result} == {"b1"}


def test_run_collect_with_no_new_episodes_returns_empty_list_and_exits_cleanly(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Old Ep", OLD_PUBDATE)}
    config = load_config({})
    result = run([FEED_A], config, fetch=fake_fetch(xml_by_url))
    assert result == []


def test_run_collect_round_trips_state_files_to_disk(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Old Ep", OLD_PUBDATE)}
    config = load_config({})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url))
    assert (tmp_path / "state" / "emailed_episodes.json").exists()
    assert (tmp_path / "state" / "pending_digest.json").exists()


def test_run_collect_preserves_existing_state_contents_on_round_trip(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "emailed_episodes.json").write_text(
        '{"processed": {"old-guid": {"feed": "Odd Lots", "title": "Old"}}}', encoding="utf-8"
    )
    xml_by_url = {FEED_A.url: rss("a1", "Old Ep", OLD_PUBDATE)}  # filtered out by recency, nothing new
    config = load_config({})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url))

    on_disk = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert on_disk == {"processed": {"old-guid": {"feed": "Odd Lots", "title": "Old"}}}


# --- Ticket #2: per-episode processing (download, transcribe, extract) ---


def test_episode_scoring_at_or_above_threshold_is_queued(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({"MIN_SCORE": "3"})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url), extract=fake_extract(score=4))

    pending = json.loads((tmp_path / "state" / "pending_digest.json").read_text(encoding="utf-8"))
    assert "a1" in pending["queued"]
    assert pending["queued"]["a1"]["score"] == 4
    assert pending["queued"]["a1"]["one_liner"] == "one-liner for Odd Lots Ep"


def test_episode_scoring_below_threshold_is_processed_but_not_queued(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({"MIN_SCORE": "3"})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url), extract=fake_extract(score=2))

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    pending = json.loads((tmp_path / "state" / "pending_digest.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["score"] == 2
    assert processed["processed"]["a1"]["status"] == "ok"
    assert "a1" not in pending["queued"]


def test_every_attempted_episode_is_recorded_as_processed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    config = load_config({})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url))

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert "a1" in processed["processed"]


def test_transcription_failure_is_recorded_not_fatal(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE),
        FEED_B.url: rss("b1", "Unhedged Ep", RECENT_PUBDATE),
    }

    def flaky_transcribe(path: Path, model: str) -> str:
        raise RuntimeError("whisper blew up")

    config = load_config({})
    result = run(
        [FEED_A, FEED_B],
        config,
        fetch=fake_fetch(xml_by_url),
        transcribe=flaky_transcribe,
    )
    assert {e.guid for e in result} == {"a1", "b1"}  # both still selected

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    pending = json.loads((tmp_path / "state" / "pending_digest.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "failed"
    assert processed["processed"]["b1"]["status"] == "failed"
    assert pending["queued"] == {}


def test_one_episode_failing_does_not_block_the_next(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE),
        FEED_B.url: rss("b1", "Unhedged Ep", RECENT_PUBDATE),
    }

    def transcribe_fails_only_for_a1(path: Path, model: str) -> str:
        if path.name.startswith("a1"):
            raise RuntimeError("boom")
        return "fake transcript text"

    config = load_config({})
    run([FEED_A, FEED_B], config, fetch=fake_fetch(xml_by_url), transcribe=transcribe_fails_only_for_a1)

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "failed"
    assert processed["processed"]["b1"]["status"] == "ok"
    assert "score" not in processed["processed"]["a1"]
    assert processed["processed"]["b1"]["score"] == 4


def test_transcript_longer_than_max_chars_is_truncated_before_extraction(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}
    seen_transcripts: list[str] = []

    def long_transcribe(path: Path, model: str) -> str:
        return "x" * 1000

    def capturing_extract(episode: Episode, transcript: str, *, claude_model: str | None = None) -> ExtractResult:
        seen_transcripts.append(transcript)
        return ExtractResult(score=4, one_liner="x", tags=[], summary=[], key_claims=[])

    config = load_config({"MAX_TRANSCRIPT_CHARS": "100"})
    run(
        [FEED_A],
        config,
        fetch=fake_fetch(xml_by_url),
        transcribe=long_transcribe,
        extract=capturing_extract,
    )
    assert len(seen_transcripts) == 1
    assert len(seen_transcripts[0]) == 100


def test_download_failure_is_recorded_not_fatal(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}

    @contextmanager
    def flaky_download(url: str) -> Iterator[Path]:
        raise ConnectionError("404")
        yield Path("/unused")  # pragma: no cover

    config = load_config({})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url), download=flaky_download)

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "failed"


def test_run_collect_ignores_article_feeds_carrying_audio(tmp_path: Path, monkeypatch: Any) -> None:
    """An article feed must never be processed as a podcast, even when its
    entries do carry an audio enclosure -- Substack can attach a
    text-to-speech voiceover to any post at any time. Without the kind
    filter, such a post would be transcribed and its summary committed to
    the public repo, which SPEC.md forbids for article content.
    """
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE),
        ARTICLE_FEED.url: rss("art1", "Newsletter post with voiceover", RECENT_PUBDATE),
    }
    inner = fake_fetch(xml_by_url)
    fetched: list[str] = []

    def tracking_fetch(url: str) -> Any:
        fetched.append(url)
        return inner(url)

    config = load_config({})
    result = run([FEED_A, ARTICLE_FEED], config, fetch=tracking_fetch)

    assert [episode.guid for episode in result] == ["a1"]
    assert ARTICLE_FEED.url not in fetched

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert set(processed["processed"]) == {"a1"}


# --- Ticket #9: bound run length, our-side vs episode-side failure, fair selection ---


def test_malformed_llm_output_is_recorded_failed_not_retried(tmp_path: Path, monkeypatch: Any) -> None:
    """LLMParseError is episode-side (the call succeeded, the reply was
    junk): current behaviour -- recorded failed, excluded next run --
    is unchanged.
    """
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}

    def malformed_extract(episode: Episode, transcript: str, *, claude_model: str | None = None) -> ExtractResult:
        raise LLMParseError("no JSON object found in model output")

    config = load_config({})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url), extract=malformed_extract)

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "failed"


def test_preflight_failure_aborts_before_any_download_or_transcribe_and_records_nothing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}

    def failing_preflight(*, model: str | None = None) -> None:
        raise ClaudeUnavailableError("claude CLI exited 1: not logged in")

    called: list[str] = []

    @contextmanager
    def tracking_download(url: str) -> Iterator[Path]:
        called.append(url)
        yield Path("/unused")  # pragma: no cover

    def tracking_transcribe(path: Path, model: str) -> str:
        called.append(str(path))  # pragma: no cover
        return "fake transcript text"  # pragma: no cover

    config = load_config({})
    run(
        [FEED_A],
        config,
        fetch=fake_fetch(xml_by_url),
        preflight=failing_preflight,
        download=tracking_download,
        transcribe=tracking_transcribe,
    )

    assert called == []
    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    pending = json.loads((tmp_path / "state" / "pending_digest.json").read_text(encoding="utf-8"))
    assert processed["processed"] == {}
    assert pending["queued"] == {}


def test_our_side_failure_at_extraction_leaves_episode_eligible_and_aborts_the_run(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """ClaudeUnavailableError raised mid-loop (as opposed to at
    preflight) is our-side, not the episode's: it must not be recorded
    `failed` (which would permanently exclude it), and since it means
    the CLI is now known-bad, the rest of the run must be aborted rather
    than wasting Whisper transcoding on episodes that can't be scored
    either.
    """
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", pubdate(1.5)),  # oldest-in-window -> processed first
        FEED_B.url: rss("b1", "Unhedged Ep", pubdate(0.5)),
    }

    def unavailable_extract(episode: Episode, transcript: str, *, claude_model: str | None = None) -> ExtractResult:
        raise ClaudeUnavailableError("claude CLI exited 1: rate limited")

    config = load_config({})
    result = run([FEED_A, FEED_B], config, fetch=fake_fetch(xml_by_url), extract=unavailable_extract)

    assert {e.guid for e in result} == {"a1", "b1"}  # selection itself is unaffected

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "deferred"
    assert processed["processed"]["a1"]["attempts"] == 1
    assert "b1" not in processed["processed"]  # aborted before ever attempting b1


def test_deferred_episode_reaching_the_retry_cap_becomes_failed(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "emailed_episodes.json").write_text(
        json.dumps({"processed": {"a1": {"feed_name": "Odd Lots", "status": "deferred", "attempts": 2}}}),
        encoding="utf-8",
    )
    xml_by_url = {FEED_A.url: rss("a1", "Odd Lots Ep", RECENT_PUBDATE)}

    def unavailable_extract(episode: Episode, transcript: str, *, claude_model: str | None = None) -> ExtractResult:
        raise ClaudeUnavailableError("claude CLI exited 1: rate limited")

    config = load_config({"MAX_EPISODE_ATTEMPTS": "3"})
    run([FEED_A], config, fetch=fake_fetch(xml_by_url), extract=unavailable_extract)

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "failed"
    assert processed["processed"]["a1"]["attempts"] == 3


def test_time_budget_stops_starting_new_episodes_once_elapsed_and_floor_are_met(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", pubdate(1.5)),  # oldest -> processed 1st
        FEED_B.url: rss("b1", "Unhedged Ep", pubdate(1.0)),  # processed 2nd
        FEED_C.url: rss("c1", "Macro Musings Ep", pubdate(0.5)),  # newest -> deferred
    }
    # Elapsed reports 60 min on every check after the first, past the
    # default 50-minute budget, from the very first in-loop check.
    config = load_config({})  # COLLECT_TIME_BUDGET_MIN=50, MIN_EPISODES_PER_RUN=2 defaults
    result = run(
        [FEED_A, FEED_B, FEED_C],
        config,
        fetch=fake_fetch(xml_by_url),
        clock=fixed_elapsed_clock(3600.0),
    )

    assert {e.guid for e in result} == {"a1", "b1", "c1"}  # selection itself is unaffected

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "ok"  # floor of 2 attempted...
    assert processed["processed"]["b1"]["status"] == "ok"
    assert "c1" not in processed["processed"]  # ...then the budget deferred the rest, unrecorded


def test_floor_guarantees_min_episodes_attempted_even_over_budget_from_the_first_check(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    xml_by_url = {
        FEED_A.url: rss("a1", "Odd Lots Ep", pubdate(1.0)),  # oldest -> the one attempt the floor forces
        FEED_B.url: rss("b1", "Unhedged Ep", pubdate(0.5)),
    }
    config = load_config({"MIN_EPISODES_PER_RUN": "1"})
    run(
        [FEED_A, FEED_B],
        config,
        fetch=fake_fetch(xml_by_url),
        # Over budget (60 min > default 50) at the very first elapsed
        # check, before a single episode has been attempted.
        clock=fixed_elapsed_clock(3600.0),
    )

    processed = json.loads((tmp_path / "state" / "emailed_episodes.json").read_text(encoding="utf-8"))
    assert processed["processed"]["a1"]["status"] == "ok"  # the floor-guaranteed attempt
    assert "b1" not in processed["processed"]  # budget already exceeded -> deferred, unrecorded
