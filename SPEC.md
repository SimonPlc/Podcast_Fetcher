# Spec: Podcast Fetcher — Macro/Rates/Credit morning brief

> Status: ready to implement. Tracker issue + `ready-for-agent` label to be
> applied once the GitHub repo exists (see setup task). This file is the source
> of truth until then.

## Problem Statement

I am a Hong Kong-based bank financing / repo trader. My core asset classes are
credit and rates, and I need to stay on top of money-market plumbing (repo,
funding, SOFR, collateral), central-bank policy, credit and structured credit
(CLO/ABS/TRS/CDS), and anything else that moves the financing world. The signal
lives across a dozen-plus finance podcasts, but I don't have time to listen to
hours of audio every day, and the useful minutes are scattered across shows and
buried in off-topic segments. I want the insight without the listening time, and
I want to keep expanding my knowledge of these markets.

## Solution

An unattended pipeline that, for free, watches a curated set of finance podcast
RSS feeds, transcribes new episodes, scores each for relevance to my desk, and
emails me a single **cross-episode thematic synthesis** each weekday morning
(~07:00 Hong Kong time) — organized by theme (front-end/repo, rates & central
banks, credit & structured credit, Asia, market structure), noting where sources
agree or disagree, written for a financing/repo trader. A monthly sweep proposes
new relevant shows for me to approve. A later phase turns each brief into a
spoken "podcast of podcasts" I can subscribe to.

## User Stories

1. As a financing/repo trader, I want a curated set of finance podcasts watched
   automatically, so that I don't have to check each show for new episodes.
2. As a trader, I want only episodes relevant to credit/rates/financing to reach
   me, so that off-topic segments (equities, crypto, politics) don't waste my time.
3. As a trader, I want each new episode scored 1-5 for relevance to my desk, so
   that a transparent threshold decides what feeds my brief.
4. As a trader, I want the relevance judgement to explicitly cover money-market
   plumbing, repo, SOFR/collateral/funding, central banks, IG/HY credit, credit
   derivatives (CDS/CDX/iTraxx), and structured credit (CLO/CLO-equity/ABS/RMBS/
   CMBS/securitization) and total return swaps, so that nothing in my asset class
   is missed.
5. As a trader who wants to grow, I want genuinely educational/explainer episodes
   to score well even when not immediately actionable, so that the brief also
   expands my knowledge.
6. As a trader, I want one synthesized brief across all episodes rather than a
   pile of per-episode summaries, so that I get a coherent read of the day.
7. As a trader, I want the brief organized by theme with agreement/disagreement
   between sources noted and views attributed, so that it reads like a strat's
   morning note.
8. As a trader, I want each point traceable back to its source episode, so that I
   can go listen to the full segment when something matters.
9. As a trader, I want the brief to lead with a headline and a short TL;DR, so
   that I get the gist in under two minutes.
10. As a trader, I want the email delivered ~07:00 HK on weekdays (Mon-Fri), so
    that it's waiting before my desk gets going; markets are shut on weekends.
11. As a trader, I want Monday's edition to sweep up everything that dropped over
    the weekend, so that I don't miss weekend content.
12. As a trader, I want the same episode never processed or emailed twice, so that
    the brief has no duplicates and I don't waste compute re-transcribing.
13. As a trader, I want the whole system to run for free, so that there's no
    ongoing cost.
14. As a trader, I want the system to run unattended in the cloud, so that there's
    no machine of mine to keep on or babysit.
15. As a trader, I want transcription accurate enough to handle rates/credit
    jargon (SOFR, OIS, basis, CLO tranches), so that summaries aren't garbled.
16. As a trader, I want a monthly sweep that proposes new relevant shows for me to
    approve manually, so that my source list stays current without silently
    pulling in marketing or off-topic feeds.
17. As a trader, I want to add or remove a source by editing a simple list, so
    that I can tune coverage without touching code.
18. As a trader, I want a quiet-day note when there is nothing relevant, so that I
    know the system ran rather than silently failed.
19. As a trader, I want to trigger a run manually on demand, so that I can
    smoke-test or catch up outside the schedule.
20. As a trader, I want my email and API credentials kept secret even though the
    code is public, so that nothing sensitive is exposed.
21. As a trader, I want the brief sent from and to my own Gmail, so that it lands
    in my normal inbox and I can file/search it.
22. As a trader (future phase), I want each morning brief turned into a natural
    spoken audio recap, so that I can listen on my commute.
23. As a trader (future phase), I want that audio published as a private podcast
    feed I subscribe to, so that new recaps appear automatically in my podcast app.

## Implementation Decisions

**Runtime & hosting**
- Runs entirely on **GitHub Actions** (no server). The repo is **public**, giving
  unlimited free Actions minutes. Secrets live in encrypted GitHub Secrets, never
  in the repo.
- State is persisted as **JSON files committed back to the repo** after each run
  (the repo is the database). Two files: a permanent processed/dedup record and a
  pending-digest queue.

**Pipeline shape** — two decoupled modes plus a monthly mode:
- **Collect** (several times per day): for each feed, take the newest N episodes
  within a recency window, skip already-processed, download audio, transcribe,
  run a per-episode LLM extraction (relevance score, one-liner, tags, summary
  bullets, key claims). Record every processed episode in the dedup record so it
  is never re-transcribed; queue only episodes scoring >= threshold.
- **Digest** (once each weekday morning + a backup run): read the queue, run a
  second LLM pass that synthesizes across all queued episodes into a themed brief,
  render HTML + plain-text email, send it, then clear the queue.
- **Discover** (monthly): query podcast directories for domain terms, dedupe
  against the current feed list, email a candidate-shows list for manual approval.

**Ingestion**
- Pure **RSS** via feedparser; download the episode's audio enclosure like any
  podcast app. No scraping, no auth. Paywalled/Spotify-exclusive shows are out of
  scope because they expose no open audio feed.
- Source list lives in `feeds.yaml` (name + url + tier). ~24 feeds at launch
  spanning plumbing/repo, macro/policy, credit & structured credit, quant, broad
  spillover, and an Asia bonus.

**Transcription**
- Local **Whisper**, model `small` by default (better on jargon than the
  reference's `base`), running on Actions CPU. Model size is an env knob.

**LLM**
- Both passes call **Claude via the Claude Code CLI** using a long-lived
  subscription OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`), i.e. zero marginal cost.
  Instructions passed as the prompt; episode transcript / day's items passed via
  stdin. Model overridable via env.
- Both prompts demand **strict JSON output** so downstream rendering is simple
  templating, with a tolerant parser that extracts the JSON object if the model
  wraps it in prose.

**Relevance persona** — HK financing/repo trader; priorities in order: (1)
money-market plumbing/repo/funding/front-end, (2) rates & central banks, (3)
credit & structured credit incl. CLO/ABS/CMBS/RMBS/CDS/CDX/TRS/private credit,
(4) financing-relevant equity & market structure, (5) rates/credit-adjacent quant;
plus an explicit knowledge-expansion dimension. Default queue threshold: score
>= 3.

**Delivery**
- Email via the **Gmail API** from the cloud, reusing the existing Gmail OAuth app
  credentials (`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`,
  scope `gmail.modify` which permits send) as GitHub Secrets. Recipient in
  `EMAIL_TO`. A refresh token is exchanged for an access token per send; message
  is a multipart/alternative MIME (text + HTML) posted to messages.send.

**Scheduling (UTC)** — collect every few hours on a staggered minute; digest at
23:00 UTC Sun-Thu (= 07:00 HK Mon-Fri) with a 23:30 backup; discover monthly.
Concurrency is serialized (queue, do not cancel) so runs don't race on the
committed JSON state. `workflow_dispatch` allows manual runs with a mode override.

**Config knobs (env):** `RUN_MODE`, `WHISPER_MODEL`, `MAX_RECENT_DAYS` (3),
`EPISODES_PER_FEED` (2), `MIN_SCORE` (3), `MAX_EPISODES_PER_RUN` (cap per collect),
`MAX_TRANSCRIPT_CHARS`, `CLAUDE_MODEL`, `EMAIL_TO`, `EMAIL_FROM`.

## Testing Decisions

A good test here exercises **external behavior of the pure logic** — given inputs,
assert outputs — and never reaches the network, Whisper, the Claude CLI, or Gmail.
The I/O wrappers are thin and verified by a manual `workflow_dispatch` smoke run,
not by unit tests. Three seams are tested:

1. **Episode selection** — given synthetic feed entries, a state record, and a
   fixed "now", assert the exact set of episodes chosen: respects the recency
   window, excludes already-processed URLs, applies the per-feed and per-run caps,
   and handles entries with missing/unparseable dates.
2. **LLM output parsing** — given representative raw model outputs (clean JSON;
   JSON wrapped in prose/markdown fences; malformed), assert a validated dict or a
   clean failure. Pins the tolerant-extraction behavior.
3. **Email rendering** — given a brief object plus items, assert the HTML and text
   contain the headline, TL;DR, each theme with its points and source
   attributions, the watch/learned sections, and the source index; and that the
   empty/quiet-day case renders the quiet note rather than an empty shell.

No prior art in-repo (greenfield). Tests use plain `pytest` with hand-built
fixtures; no network or model access. The pipeline is structured so these three
functions are importable without triggering any I/O at import time.

## Out of Scope

- **Phase 2 audio** ("podcast of podcasts"): TTS of the brief, audio assembly, MP3
  hosting, and generating a subscribable RSS feed. Deferred until the email digest
  is working well; captured as user stories 22-23 for later.
- Auto-discovery that silently adds shows (discovery only *proposes*; humans
  approve).
- Paywalled or Spotify-exclusive shows (no open audio feed).
- Per-segment timestamped chapterization of episodes.
- A web UI / archive site.
- Multi-user support; this serves one recipient.

## Further Notes

- Reference implementation studied: `TillAlexanderHani/livescript-shared` — same
  core idea (RSS → Whisper → Claude → email on GitHub Actions with git-committed
  JSON state). Key divergences here: cross-episode **synthesis** rather than
  per-episode cards; broadened credit/structured-credit persona; Gmail **API**
  (reusing existing OAuth) rather than SMTP app password; a **monthly discovery**
  sweep; and a planned audio phase.
- Maintenance cost of the free stack: the Claude subscription OAuth token expires
  periodically and must be re-minted with `claude setup-token`; heavy days may hit
  subscription rate limits. Accepted tradeoff for zero marginal cost.
- Timezone: HK is UTC+8. 23:00 UTC Sun-Thu delivers 07:00 HK Mon-Fri; Monday's
  edition (Sun 23:00 UTC) naturally covers weekend-dropped episodes via the
  recency window.
