from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

from podcast_fetcher.articles import article_hash, parse_article_entries, select_articles
from podcast_fetcher.config import Config
from podcast_fetcher.extract import extract_article
from podcast_fetcher.gmail import mint_access_token, require_env, send_email
from podcast_fetcher.ingest import fetch_feed
from podcast_fetcher.llm import ClaudeUnavailableError, check_claude_available
from podcast_fetcher.models import Article, ExtractResult, Feed
from podcast_fetcher.render import render_digest
from podcast_fetcher.schedule import most_recent_due_slot
from podcast_fetcher.store import (
    load_pending,
    load_queued_ids,
    load_settled_slot,
    load_seen_article_hashes,
    load_seen_articles,
    record_digest_slot,
    save_pending,
    save_seen_articles,
)

logger = logging.getLogger(__name__)

MintTokenFn = Callable[[str, str, str], str]
SendFn = Callable[..., None]
FetchFn = Callable[[str], Any]
ExtractArticleFn = Callable[..., ExtractResult]
PreflightFn = Callable[..., None]


def run_digest(
    config: Config,
    env: Mapping[str, str],
    feeds: Sequence[Feed] = (),
    *,
    mint_token: MintTokenFn = mint_access_token,
    send: SendFn = send_email,
    fetch: FetchFn = fetch_feed,
    extract: ExtractArticleFn = extract_article,
    preflight: PreflightFn = check_claude_available,
    today: date | None = None,
    now: datetime | None = None,
) -> None:
    """Read the pending podcast queue, fetch+score today's articles, and
    email one unified card list (highest relevance score first), a
    quiet-day note if nothing qualifies, or a "Claude unavailable" note
    if nothing could be scored because Claude was down (an outage or the
    weekly usage limit) -- the last of which must never be mislabelled as
    a quiet day.

    Podcasts and articles are handled very differently upstream (see
    SPEC.md): podcast episodes were already transcribed and scored by a
    prior `collect` run, so rendering them here makes no LLM call.
    Articles have no such queue -- they're fetched, filtered, and scored
    against Claude right here in the digest run, since there's no
    expensive transcription step to amortise.

    Article failures (a feed fetch/parse error, or a failed Claude
    extraction) are logged and skipped; they must never block podcast
    delivery, so the digest still sends with whatever it has. The
    podcast queue is cleared, and newly-seen article hashes are
    committed, only after a successful send -- if sending fails, the
    exception propagates and both stores are left untouched so the next
    run can retry rather than silently losing that day's content.
    """
    today = today or date.today()
    now = now or datetime.now(tz=timezone.utc)

    # Validate delivery config before doing any scoring work: a misconfigured
    # send should fail fast rather than after spending Claude quota on articles.
    if not config.email_to or not config.email_from:
        raise RuntimeError("EMAIL_TO and EMAIL_FROM must be set to send the digest")
    client_id = require_env(env, "GMAIL_CLIENT_ID")
    client_secret = require_env(env, "GMAIL_CLIENT_SECRET")
    refresh_token = require_env(env, "GMAIL_REFRESH_TOKEN")

    pending = load_pending()
    episode_items = dict(pending.get("queued", {}))

    article_feeds = [feed for feed in feeds if feed.kind == "article"]
    article_items, newly_seen, claude_unavailable = _collect_articles(
        article_feeds, config, fetch=fetch, extract=extract, now=now
    )

    items = {**episode_items, **article_items}

    # An empty digest has two very different causes -- a genuine quiet day, or
    # Claude being down so nothing *could* be scored -- and last night's outage
    # showed the pipeline mislabelling the latter as the former. Article scoring
    # above already reveals the outage when any article was tried; when it
    # wasn't (no new articles selected today), one cheap preflight probe
    # disambiguates so the email is never wrong about which it is. The probe
    # only fires on an otherwise-empty digest, so a normal quiet day costs one
    # trivial call and a busy day costs none.
    if not items and not claude_unavailable:
        try:
            preflight(model=config.claude_model)
        except ClaudeUnavailableError:
            logger.warning("digest: empty digest and Claude preflight failed; reporting unavailable, not quiet day")
            claude_unavailable = True

    if items:
        subject = f"Morning Brief -- {today.isoformat()} ({len(items)} item{'s' if len(items) != 1 else ''})"
        logger.info("digest: rendering %d item(s)%s", len(items), " (Claude unavailable this run)" if claude_unavailable else "")
    elif claude_unavailable:
        subject = f"Podcast Fetcher: Claude unavailable ({today.isoformat()})"
        logger.info("digest: nothing scored because Claude was unavailable, sending unavailable note")
    else:
        subject = f"Podcast Fetcher: quiet day ({today.isoformat()})"
        logger.info("digest: nothing queued or scored, sending quiet-day note")

    html, text = render_digest(items, claude_unavailable=claude_unavailable)

    access_token = mint_token(client_id, client_secret, refresh_token)
    send(
        access_token,
        to_addr=config.email_to,
        from_addr=config.email_from,
        subject=subject,
        text=text,
        html=html,
    )
    logger.info("digest: email sent to %s", config.email_to)

    # Settle the slot before clearing the queue, not after: the thing this
    # guards against is the backup run 54 minutes later re-sending a brief
    # that already went out, and that window opens the moment `send`
    # returns. A crash between here and save_pending() leaves the queue
    # uncleared and so repeats content tomorrow, which is the pre-existing
    # behaviour and much the lesser of the two.
    slot = most_recent_due_slot(now)
    if slot is not None:
        record_digest_slot(slot, sent_at=now)

    save_pending({"queued": {}})
    if newly_seen:
        _mark_articles_seen(newly_seen)


def _collect_articles(
    article_feeds: Sequence[Feed],
    config: Config,
    *,
    fetch: FetchFn,
    extract: ExtractArticleFn,
    now: datetime,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]], bool]:
    """Fetch every article feed, select new-enough/unseen entries (capped
    at MAX_ARTICLES_PER_DIGEST), and extract each via Claude.

    Every successfully-extracted article is marked seen regardless of its
    score, mirroring collect.py's episode handling, so a below-threshold
    article is never re-scored on a later run. An article whose
    extraction fails is *not* marked seen -- unlike a transcribed
    episode, nothing expensive was spent on it, so leaving it eligible
    lets a transient Claude failure be retried on the next digest run
    instead of silently dropping that source forever.

    The third return value reports whether any extraction failed with a
    ClaudeUnavailableError (Claude down / usage limit / bad token) --
    an our-side outage, distinct from an article-side parse failure. The
    caller uses it to say so in the email rather than mislabelling an
    outage as a quiet day.
    """
    if not article_feeds:
        return {}, [], False

    seen_hashes = load_seen_article_hashes()

    articles_by_feed: dict[str, list[Article]] = {}
    for feed in article_feeds:
        try:
            parsed = fetch(feed.url)
            articles_by_feed[feed.name] = parse_article_entries(parsed, feed)
        except Exception:
            logger.exception("Failed to fetch/parse article feed %s (%s); skipping", feed.name, feed.url)
            articles_by_feed[feed.name] = []

    selected = select_articles(
        articles_by_feed,
        seen_hashes,
        now,
        max_recent_days=config.max_recent_days,
        max_articles=config.max_articles_per_digest,
    )
    logger.info("digest: %d article(s) selected across %d feed(s)", len(selected), len(article_feeds))

    records: dict[str, dict[str, Any]] = {}
    newly_seen: list[tuple[str, str]] = []
    claude_unavailable = False
    for article in selected:
        key = article_hash(article.feed_name, article.url)
        try:
            result = extract(article, claude_model=config.claude_model)
        except ClaudeUnavailableError:
            # Our-side outage, not this article's fault: don't mark it seen
            # (so it retries), and remember Claude was down so the digest can
            # report it rather than looking like a quiet day.
            claude_unavailable = True
            logger.exception(
                "Claude unavailable extracting article [%s] %s; skipping, not marked seen so it can retry",
                article.feed_name,
                article.url,
            )
            continue
        except Exception:
            logger.exception(
                "Failed to extract article [%s] %s; skipping, not marked seen so it can retry",
                article.feed_name,
                article.url,
            )
            continue

        newly_seen.append((key, article.feed_name))
        if result.score >= config.min_score:
            records[key] = _article_record(article, result)
        else:
            logger.info("article scored below threshold, not included: [%s] %s", article.feed_name, article.title)

    return records, newly_seen, claude_unavailable


def _article_record(article: Article, extraction: ExtractResult) -> dict[str, Any]:
    return {
        "feed_name": article.feed_name,
        "tier": article.tier,
        "title": article.title,
        "url": article.url,
        "kind": "article",
        "published": article.published.isoformat() if article.published else None,
        "score": extraction.score,
        "one_liner": extraction.one_liner,
        "tags": extraction.tags,
        "recap": extraction.recap,
        "implications": extraction.implications,
        "watch": extraction.watch,
        "terms": extraction.terms,
        "key_claims": extraction.key_claims,
    }


def _mark_articles_seen(newly_seen: list[tuple[str, str]]) -> None:
    seen = load_seen_articles()
    records = seen.setdefault("seen", {})
    for hash_, feed_name in newly_seen:
        records[hash_] = {"feed_name": feed_name}
    save_seen_articles(seen)


def run_digest_if_due(
    config: Config,
    env: Mapping[str, str],
    feeds: Sequence[Feed] = (),
    *,
    now: datetime | None = None,
    run: Callable[..., None] = run_digest,
) -> bool:
    """Entry point for a cron-triggered digest. Sends unless this slot's
    brief has already gone out; returns whether it sent.

    Both digest crons land here, and only one of them should ever deliver.
    The backup exists to cover a primary that failed transiently, but it
    used to call run_digest() unconditionally: after a *successful*
    primary it found the queue already cleared and mailed a quiet-day note
    on top of the real brief, every single weekday. Checking the settled
    slot makes the backup do what it was always meant to do -- retry only
    a primary that did not deliver.
    """
    now = now or datetime.now(tz=timezone.utc)
    slot = most_recent_due_slot(now)
    if slot is not None and load_settled_slot() == slot:
        logger.info("digest: slot %s already settled; skipping (this is the backup run)", slot)
        return False
    run(config, env, feeds, now=now)
    return True


def maybe_send_missed_digest(
    config: Config,
    env: Mapping[str, str],
    feeds: Sequence[Feed] = (),
    *,
    now: datetime | None = None,
    run: Callable[..., None] = run_digest,
) -> bool:
    """Catch up a digest slot that never ran, from inside a collect run.
    Returns whether it sent.

    GitHub Actions makes no delivery guarantee for `schedule`: under load
    it delays runs and drops them outright, and on 2026-08-26 it dropped
    both digest crons, so no brief went out that morning and the queued
    episodes sat undelivered for a day. Moving the crons off the hour
    makes that less likely but cannot make it impossible, so the recovery
    lives here instead: every collect run checks whether a slot went by
    undelivered and, if so, sends the brief it missed. Six collect runs a
    day means six independent chances to notice.

    Two deliberate limits:

    - It only fires when the podcast queue is non-empty. A slot missed on
      a day that would have produced an articles-only digest is settled
      silently rather than caught up, because articles are re-fetched at
      digest time and a stale one is worth less than an unexpected email.
    - With no log at all (the first run after this shipped) it settles the
      current slot without sending, since an absent history is not
      evidence that anything was missed.
    """
    now = now or datetime.now(tz=timezone.utc)
    slot = most_recent_due_slot(now, grace_minutes=config.missed_digest_grace_min)
    if slot is None:
        return False

    settled = load_settled_slot()
    if settled is None:
        logger.info("digest: no delivery log yet; settling slot %s without sending", slot)
        record_digest_slot(slot)
        return False
    if settled >= slot:
        return False

    if not load_queued_ids():
        # Settle it anyway. Otherwise episodes queued *after* the missed
        # slot would look like missed content to the next collect run,
        # which would then mail a brief in the middle of the afternoon.
        logger.info("digest: slot %s was missed but nothing is queued; settling, no catch-up", slot)
        record_digest_slot(slot)
        return False

    logger.warning(
        "digest: slot %s was missed (last settled %s) and %d item(s) are queued; sending catch-up brief",
        slot,
        settled,
        len(load_queued_ids()),
    )
    run(config, env, feeds, now=now)
    return True
