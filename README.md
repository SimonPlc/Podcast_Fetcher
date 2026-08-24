# Podcast Fetcher

An unattended pipeline that watches finance podcast feeds and written-research
feeds, transcribes and scores everything for relevance to a Hong Kong bank
financing / repo desk, and emails a morning brief each weekday at ~07:00 HK.

One card per relevant item, sorted by relevance score: show or publication,
score, tags, a one-liner, summary bullets, key claims, and a link back to the
source. A monthly sweep proposes new shows to add, and never adds one itself.

`SPEC.md` is the source of truth for behaviour and for why each decision was
made. This file covers setup and operations.

## How it runs

Everything runs on GitHub Actions, on a public repo so Actions minutes are
unlimited. There is no server. State lives as JSON committed back into this
repo after each run, which is why you will see `Update pipeline state [skip ci]`
commits appear on `main`.

Three run modes, all in `.github/workflows/pipeline.yml`, with the mode derived
from whichever cron fired:

| Mode | When | What it does |
|---|---|---|
| `collect` | 6x/day, staggered | Fetch podcast feeds, download audio, Whisper-transcribe, score with Claude, queue anything scoring >= `MIN_SCORE` |
| `digest` | 23:00 UTC Sun-Thu, plus a 23:30 backup | Render the queued episodes, fetch and score today's articles, email one merged brief, then clear the queue |
| `discover` | 1st of the month, 21:17 UTC | Search the iTunes API for configured terms, score the candidates, email new show suggestions |

23:00 UTC Sun-Thu is 07:00 HK Mon-Fri. Sunday's run sweeps up whatever dropped
over the weekend.

Podcasts are transcribed in `collect` and only rendered in `digest`, because
Whisper is expensive and that work is worth amortising. Articles have no such
cost, so they are fetched and scored inside the `digest` run and their text is
never written to state. That last point is deliberate: this repo is public.

## Setup

You need a GitHub repo, a Gmail OAuth client, and a Claude subscription.

### 1. Secrets

Set all six on the repo (Settings > Secrets and variables > Actions, or `gh`):

| Secret | What it is |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude subscription token, see below |
| `GMAIL_CLIENT_ID` | OAuth client id for the Gmail API |
| `GMAIL_CLIENT_SECRET` | OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | Refresh token with the `gmail.modify` scope, which permits send |
| `EMAIL_TO` | Where the brief goes |
| `EMAIL_FROM` | The sending address, i.e. the Gmail account that owns the OAuth grant |

### 2. Mint the Claude token

This has to be done interactively, in a real terminal. It will not work inside
an agent session or any non-TTY shell: the browser flow completes but the token
is printed to a terminal that is not there to receive it.

```
claude setup-token
```

Complete the browser flow, then take the token it prints and set it without
letting it land in a transcript or a file:

```
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <owner>/<repo>
```

**This token expires periodically.** Re-mint it the same way when it does. See
"When the token expires" below, because expiry is not a quiet failure.

### 3. Sources

Edit `feeds.yaml`. Every entry needs `name`, `url` and `tier`; `tier` is
descriptive only, since relevance is decided per item by the score.

```yaml
  - name: "Odd Lots"
    url: "https://.../podcast.rss"
    tier: "plumbing"

  - name: "NY Fed Liberty Street Economics"
    url: "https://libertystreeteconomics.newyorkfed.org/feed/"
    tier: "plumbing"
    kind: "article"          # defaults to "podcast" when omitted

  - name: "BIS working papers"
    url: "https://www.bis.org/doclist/wppubls.rss"
    tier: "macro"
    kind: "article"
    min_body_chars: 400      # abstract-only feed, see below
```

Article feeds must carry the **full article body in the RSS feed**. There is no
scraping and no readability extraction. An entry whose body is shorter than
`min_body_chars` (default ~2500) is skipped as a teaser. Research-paper feeds
set it low on purpose, because an abstract is a purpose-written summary rather
than a teaser.

The same file holds `discovery_terms`, the search terms the monthly sweep uses.

## Operations

### Running by hand

```
gh workflow run "Podcast Fetcher Pipeline" --ref main -f mode=collect
gh workflow run "Podcast Fetcher Pipeline" --ref main -f mode=digest
gh workflow run "Podcast Fetcher Pipeline" --ref main -f mode=discover
gh run list --limit 5
gh run view <run-id> --log-failed
```

Run `collect` before `digest` if you want the brief to contain anything.

### Pausing everything

```
gh workflow disable "Podcast Fetcher Pipeline"
gh workflow enable  "Podcast Fetcher Pipeline"
```

Do this if the Claude token is missing or expired. See below for why.

### When the token expires

**A `collect` run with a broken Claude token reports success and destroys
content.** It downloads and transcribes each episode, fails at the scoring
step, and records the episode as processed anyway, so it is never retried. The
episode is gone: never scored, never delivered, and it will not come back when
the token is fixed.

If this happens:

1. `gh workflow disable "Podcast Fetcher Pipeline"` to stop further loss.
2. Re-mint the token and set the secret.
3. Recover the burned episodes by deleting their records from
   `state/emailed_episodes.json` (they are the entries with
   `"status": "failed"`), commit, and push. They become eligible again as long
   as they are still inside the `MAX_RECENT_DAYS` window.
4. Re-enable the workflow.

Issue #9 tracks fixing this properly, so that a failure on our side defers the
episode instead of burning it.

### State files

All committed to the repo, all safe to hand-edit if you know why you are doing
it:

| File | Holds |
|---|---|
| `state/emailed_episodes.json` | Every podcast episode ever attempted, with status and extraction. Presence here means "never process again" |
| `state/pending_digest.json` | Episodes queued for the next brief. Cleared after a successful send |
| `state/seen_articles.json` | Hashes of articles already seen, plus the feed name. Deliberately holds no title, body or summary |
| `state/discovery_seen.json` | Show candidates already proposed, so the monthly sweep stops re-suggesting them |

To force a re-run of an item, delete its entry and push.

## Configuration

All via environment variables, all with working defaults:

| Variable | Default | Effect |
|---|---|---|
| `RUN_MODE` | `collect` | `collect`, `digest` or `discover` |
| `WHISPER_MODEL` | `medium` | faster-whisper model size; larger handles rates/credit jargon better but is slower |
| `MAX_RECENT_DAYS` | `3` | Recency window for episodes and articles |
| `EPISODES_PER_FEED` | `2` | Per-feed cap per collect run |
| `MAX_EPISODES_PER_RUN` | `8` | Hard total cap per collect run |
| `COLLECT_TIME_BUDGET_MIN` | `50` | Wall-clock budget: stop starting new episodes past this |
| `MIN_EPISODES_PER_RUN` | `2` | Floor attempted even if the budget is already exceeded |
| `MAX_EPISODE_ATTEMPTS` | `3` | Retries before an our-side deferral becomes terminal |
| `MIN_SCORE` | `3` | Relevance bar for the brief, and for proposing a show |
| `MAX_TRANSCRIPT_CHARS` | `60000` | Transcript truncation before scoring |
| `MAX_ARTICLES_PER_DIGEST` | `10` | Cap on articles per brief |
| `DISCOVERY_LIMIT` | `25` | iTunes results per search term |
| `DISCOVERY_BATCH_SIZE` | `25` | Candidates scored per Claude call |
| `CLAUDE_MODEL` | `sonnet` (in CI) | Extraction model. Pinned to Sonnet in the workflow so the background job stays off the shared weekly Opus allowance and extraction quality is predictable; unset locally falls back to the CLI default |

## Development

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m mypy podcast_fetcher
```

Tests never touch the network, Whisper, the Claude CLI or Gmail. Everything
crossing one of those boundaries is injected, so the pure logic (selection,
parsing, rendering, dedupe, scoring thresholds) is tested directly and the thin
I/O wrappers are verified by a manual dispatch instead.

Running a mode locally needs the same environment variables as the workflow,
plus a working `claude` CLI on `PATH`. On Windows the CLI must be reached
through its real `claude.exe` rather than the npm `.cmd` shim, which silently
truncates large piped stdin; `llm.py` handles that and needs no configuration.
