# Spec: Podcast Fetcher — Macro/Rates/Credit morning brief

> Status: tickets #1-#3 implemented and closed (github.com/SimonPlc/Podcast_Fetcher,
> issues #1-#6). Phase 1 (email digest) verified end-to-end with a real sent
> email. Next: tickets #4 (GitHub Actions workflow), #5 (monthly discovery
> sweep), #6 (repo secrets + cloud smoke-test).
>
> **Revision (2026-08-18):** after seeing the first real digest, the digest
> format was changed from a cross-episode thematic synthesis to **per-episode
> digest cards** (one card per queued episode, sorted by relevance score) for
> clarity and so each show is individually accessible — closer to the
> `livescript-shared` reference than the original synthesis design. This
> removed `synthesize.py` and its two-step LLM machinery entirely: the digest
> step now makes **no LLM call** at all, it just renders each episode's
> already-computed extraction (from the collect step) into a card. If you see
> references to a "Brief"/theme-based synthesis elsewhere (old commit
> messages, closed issue #3's original text), that reflects the pre-revision
> design — this file is current.
>
> **Revision (2026-08-18, later same day):** ticket #7 added written articles
> as a second source type (money-market/central-bank research blogs and
> abstract-only paper feeds), scored and rendered exactly like podcast
> episodes into the same per-episode card, ranked into one list by score.
> Unlike podcasts, articles have no collect-time queue: they are fetched,
> scored, and rendered entirely inside the digest run, since there is no
> expensive transcription step to amortise (see the new Implementation
> Decisions below). Article content is never persisted to state, only a hash.
>
> **Revision (2026-08-19):** ticket #5 implemented the monthly `discover`
> run mode: it queries the free, keyless iTunes Search API for the domain
> terms in feeds.yaml's new `discovery_terms` list, dedupes candidates
> against the current podcast feed list and against previously-proposed
> candidates (`state/discovery_seen.json`), and emails whatever is new for
> manual approval -- it never adds a feed itself. Discovery is
> **podcasts-only**: there is no free keyless directory API for general
> article/RSS feeds, so article sources in feeds.yaml remain curated by
> hand (see "Podcast discovery" below).
>
> **Revision (2026-08-19, later same day):** ticket #8 added a Claude
> scoring pass over discovery candidates: run live, the keyword-only
> sweep from #5 returned mostly crypto/real-estate/personal-finance shows
> (a genre pre-filter doesn't help -- Bankless is filed under Business,
> same as the shows the desk actually wants), so surviving candidates are
> now scored by Claude against the same relevance persona
> `prompts/extract.txt` uses, and only candidates scoring >= `MIN_SCORE`
> are emailed. The persona/priorities text was factored out of
> `prompts/extract.txt` into a shared `prompts/persona.txt` (loaded via
> `podcast_fetcher.persona`) so the new `prompts/score_candidates.txt`
> states the same priorities rather than a second, driftable copy.
>
> Scoring was initially written as ONE call covering the whole sweep, and
> that was corrected before it ever ran: measured live, a first sweep
> yields ~225 surviving candidates, and demanding a single complete reply
> for all of them meant one dropped entry discarded every good score and
> triggered a fallback that emailed all 225 unvetted shows and marked them
> permanently seen. Scoring is now chunked (`DISCOVERY_BATCH_SIZE`,
> default 25), partial replies are tolerated, and anything unscored is
> *deferred* rather than guessed at or suppressed. See "Podcast discovery"
> below for the full behaviour, including the deferral and
> not-marked-seen-when-filtered-out rules.

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
emails me a digest each weekday morning (~07:00 Hong Kong time) with **one card
per relevant episode** — show, score, tags, one-liner, a prose recap,
persona-angled implications, optional watch/terms, key claims, and a link —
sorted by relevance so the most important shows are
immediately clear and each is individually accessible. A monthly sweep proposes
new relevant shows for me to approve. The written per-item recap is the end
product; a spoken "podcast of podcasts" was considered and is not planned.

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
6. As a trader, I want one card per relevant episode rather than a blended
   cross-episode synthesis, so that each show is clearly separated and I can
   tell at a glance which ones are worth my time.
7. As a trader, I want each card to carry the show, a relevance score, tags, a
   one-line summary, bullet-point details, and key claims, so that I can judge
   relevance and substance without opening the episode.
8. As a trader, I want each card to link back to its source episode, so that I
   can go listen to the full segment when something matters.
9. As a trader, I want cards sorted by relevance score, so that the most
   important episodes are immediately at the top.
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
24. As a trader, I want written research (central-bank blogs, market
    commentary, paper abstracts) scored and summarized the same way as
    podcast episodes, so that my brief isn't limited to audio-only coverage.
25. As a trader, I want articles and episodes ranked into a single list by
    relevance score, not split into separate sections, so that the most
    important source of the day is obvious regardless of its format.
26. As a trader, I want an article card to link back to the source article
    (labeled "Read") the way an episode card links to "Listen", so that I
    can go read the original when something matters.
27. As a trader, I want a failed article fetch or extraction to be logged and
    skipped rather than blocking the digest, so that a broken research feed
    never costs me my podcast coverage for the day.

## Implementation Decisions

**Runtime & hosting**
- Runs entirely on **GitHub Actions** (no server). The repo is **public**, giving
  unlimited free Actions minutes. Secrets live in encrypted GitHub Secrets, never
  in the repo.
- State is persisted as **JSON files committed back to the repo** after each run
  (the repo is the database). Four files: a permanent podcast processed/dedup
  record, a pending-digest queue, a permanent article dedup record holding
  hashes only (since ticket #7 -- see "Written articles" below), and (since
  ticket #5) a permanent discovery-candidate record holding previously-
  proposed podcast candidates -- see "Podcast discovery" below.

**Pipeline shape** — two decoupled modes plus a monthly mode:
- **Collect** (several times per day): for each feed, take the newest N episodes
  within a recency window, skip already-processed, download audio, transcribe,
  run a per-episode LLM extraction (relevance score, one-liner, tags, a prose
  recap, persona-angled implications, optional watch/terms, key claims). Record
  every processed episode in the dedup record so it
  is never re-transcribed; queue only episodes scoring >= threshold.
- **Digest** (once each weekday morning + a backup run): read the podcast queue;
  separately, fetch every article feed, filter/dedupe/score new articles
  (ticket #7, see "Written articles" below); merge both into one set of
  records and render one HTML + plain-text card per record (sorted by score,
  highest first), send it, then clear the podcast queue and commit the newly
  seen article hashes. No LLM call happens against the podcast queue -- each
  episode card is built entirely from the extraction already computed at
  collect time. Articles are the one exception to "digest makes no LLM call":
  they have no collect-time queue, so their single Claude extraction happens
  here, in the digest run itself.
- **Discover** (monthly): query the iTunes Search API for each configured
  domain term, dedupe candidates against the current podcast feed list and
  against previously-proposed candidates, email a candidate-shows list for
  manual approval, and record newly-proposed candidates as seen only after
  that email sends successfully. Never adds a feed itself (see "Podcast
  discovery" below).

**Ingestion**
- Pure **RSS** via feedparser; download the episode's audio enclosure like any
  podcast app. No scraping, no auth. Paywalled/Spotify-exclusive shows are out of
  scope because they expose no open audio feed.
- Source list lives in `feeds.yaml` (name + url + tier). ~24 podcast feeds at
  launch spanning plumbing/repo, macro/policy, credit & structured credit,
  quant, broad spillover, and an Asia bonus; ticket #7 added ~10 article feeds
  (see "Written articles" below), distinguished by a `kind: podcast|article`
  field defaulting to `podcast` so no existing entry needed editing.

**Written articles (ticket #7)** -- a second source type, treated exactly like
podcast episodes (same 1-5 score, same extraction prompt, same digest card,
ranked into the same score-sorted list), with these deliberate differences:
- **No collect step, no queue.** Articles are fetched, scored, extracted, and
  rendered entirely inside the digest run. Podcasts keep the collect/digest
  split solely to amortise expensive Whisper transcription; articles cost
  nothing to fetch, so there's no reason to ration them across runs.
- **Full-text RSS only, no scraping.** A feed qualifies only if it already
  publishes the article body in `content:encoded` or `summary`/`description`
  -- the same thing any RSS reader sees. An optional per-feed
  `min_body_chars` overrides the ~2500-char full-text default; the two
  research-paper feeds (BIS working papers, Fed FEDS Notes) set it to ~400,
  since an abstract is a purpose-written summary rather than a truncated
  teaser. Whichever threshold is in effect also tells the extraction prompt
  whether it's reading a full article or an abstract, so it can calibrate
  (e.g. not treat an abstract as if it had access to the whole paper).
- **Article content is never persisted.** The repo is public; committing a
  Claude-derived summary of someone else's article, even just to a dedup
  record, is a redistribution question this project deliberately avoids
  entirely rather than relies on a defensible-use argument for. The only
  thing written to `state/seen_articles.json` is a hash of (feed name, URL)
  per article, plus the feed name alongside it for debuggability -- the feed
  name is our own config, not third-party content, so it carries no such
  risk. No title, body, or LLM-generated summary ever reaches disk.
- **Dedup hashes commit only after a successful send**, exactly like the
  podcast queue only clears on success -- a failed send must not silently
  burn that day's articles by marking them seen before they were ever
  delivered.
- **Article failures are non-fatal and never block podcast delivery.** A
  feed that 404s, an entry below `min_body_chars`, or a failed Claude
  extraction is logged and skipped; the digest still sends with whatever it
  has, including podcast-only on a bad day for the article feeds. An
  extraction failure specifically is *not* marked seen (unlike a below-
  threshold score, which is), so a transient failure gets retried on the
  next digest run rather than silently dropping that article forever --
  there's no expensive resource spent on it to justify writing it off.
- **FT is excluded**, even though it would otherwise be a strong source: FT's
  Terms & Conditions section 3.5 prohibits machine-learning use of FT
  content, `ft.com/robots.txt` blocks `ClaudeBot`/`Claude-Web`/`anthropic-ai`
  by name, and its Copyright Policy caps redistribution at a 30-word summary,
  ten per day. FT Alphaville's free Substack is included instead: an openly
  published, full-text feed with none of those restrictions.
- Structured credit (CLO/ABS/CMBS/lev fin) has no free full-text article
  feed, so it remains covered only by the podcast list -- a known, accepted
  gap (see Out of Scope).

**Podcast discovery (ticket #5)** -- a monthly `discover` run mode that
proposes new podcast shows for manual approval; it never adds a feed itself:
- **iTunes Search API only.** `https://itunes.apple.com/search?term=<term>&entity=podcast&limit=<n>`
  is free, keyless, and returns `collectionName`/`feedUrl` per result --
  confirmed working. Queried with `requests` and an honest, identifying
  User-Agent, the same reasoning as `transcribe.py`'s `_REQUEST_HEADERS`.
  `DISCOVERY_LIMIT` (default 25) caps results requested per search term.
- **Article-feed discovery is explicitly out of scope.** There is no free
  keyless directory API for general RSS/article feeds -- Feedly's search API
  needs OAuth, Podcast Index needs a key, everything else is scraping.
  Discovery therefore only ever searches for and proposes `kind: podcast`
  shows; article sources in feeds.yaml stay hand-curated, as they always
  have been.
- **Search terms live in feeds.yaml**, as a top-level `discovery_terms` list
  (loaded by `feeds.load_discovery_terms`, kept separate from `load_feeds`/
  `Feed` since the terms describe the sweep as a whole, not any one feed),
  so domain coverage can be tuned without touching code -- same principle as
  the feed list itself. An absent `discovery_terms` key loads as an empty
  list rather than raising, so existing feeds.yaml files/tests are
  unaffected.
- **Dedupe by both normalised feed URL and normalised name**, against BOTH
  the current `kind: podcast` feed list and every previously-proposed
  candidate, so the same show already declined isn't re-proposed every
  month. Normalisation: case-fold, strip surrounding whitespace, drop a
  trailing slash, and treat `http`/`https` as equivalent -- directory data
  routinely lists the same show under a slightly different URL or scheme.
  Candidates are also deduped against each other within one run, since the
  same show can surface under more than one search term.
- **Previously-proposed candidates persist to `state/discovery_seen.json`**,
  keyed by normalised feed URL, storing the show's name, feed URL, and the
  term that surfaced it. Unlike article content, a podcast's name and public
  feed URL are directory metadata (the same thing anyone gets back from the
  iTunes Search API), not third-party content requiring the article
  no-persist treatment, so persisting them in full is fine.
- **A candidate is recorded as proposed only after the email sends
  successfully** -- exactly like the podcast queue and article dedup hashes
  only commit on a successful digest send -- so a failed send doesn't
  silently burn that month's candidates before Simon ever saw them.
- **A failing search term is logged and skipped**, not fatal to the run,
  matching `collect.py`'s per-feed and `digest.py`'s per-article defensive
  style.
- **No candidates found** (including when `discovery_terms` is empty)
  renders a "no new candidates" note and still emails, rather than sending
  nothing -- mirroring the digest's quiet-day behaviour: a monthly email
  confirms the sweep ran even when there's nothing to review.

**Scoring discovery candidates (ticket #8)** -- candidates surviving
`select_new_candidates` are scored by Claude before being emailed, so the
sweep proposes a handful of real prospects rather than a wall of keyword
noise (run live against the real feed list, the first 4 of 13 configured
terms alone returned 32 surviving candidates, almost all crypto/real-estate/
personal-finance shows; a genre pre-filter doesn't fix this since e.g.
Bankless is filed under Business, the same genre as the shows the desk
wants):
- **Batched, never one call per candidate**, but chunked rather than one
  call for the whole sweep. Candidates are serialized to a JSON array on
  stdin (`discover.build_score_stdin`) and scored via `run_claude`
  (`discover.score_candidates`), reusing `llm.py`'s CLI plumbing
  (including its Windows `.exe`-over-`.cmd`-shim handling) and following
  `extract.py`'s pattern: render a prompt, pipe the payload via stdin, get
  strict JSON back, parse it tolerantly-but-strictly
  (`discover.parse_score_response`, mirroring `extract.parse_extraction`).
- **Chunk size `DISCOVERY_BATCH_SIZE` (default 25)**, applied by
  `discover.score_in_batches`. A single call for the whole sweep was tried
  and rejected: measured against the live iTunes API and the real
  `feeds.yaml`, a first sweep yields ~225 surviving candidates, ~33k chars
  of stdin, and a reply that must carry a score and a sentence for all 225.
  That invites truncation, and because a chunk is all-or-nothing, one bad
  entry would discard every good score alongside it.
- **Incomplete replies are tolerated, not fatal.** `parse_score_response`
  stays strict about the shape of what it receives (malformed entry,
  out-of-range id, duplicate id, bad score/reason all raise) but ids simply
  missing from an otherwise valid reply are not an error: they come back as
  *deferred*.
- **The prompt (`prompts/score_candidates.txt`) is explicit it is judging
  a SHOW, not an episode**: the only input per candidate is its iTunes
  `collectionName`/`artistName`/`genres` -- no transcript exists at this
  stage and none is fetched. The prompt tells the model to calibrate
  accordingly and to score an unrecognised show low rather than invent
  facts about it or guess generously from genre/name alone.
- **Shares its persona/priorities wording with `prompts/extract.txt`**
  rather than duplicating a copy that can drift: both prompts include a
  `{{PERSONA}}` placeholder filled from `prompts/persona.txt` by the new
  `podcast_fetcher.persona` module (same plain-string-replace mechanism as
  `extract.py`'s `{{KIND}}` placeholder, for the same reason -- the JSON
  examples are full of literal `{`/`}`).
- **Threshold: `MIN_SCORE`** (no dedicated discovery knob -- the existing
  digest/collect threshold earns its reuse here rather than adding a
  second, easily-mismatched number). `discover.filter_by_threshold` is a
  pure function so this is directly testable.
- **The email shows each proposed show's score and one-line reason**
  alongside its existing name/feed URL/search term (`render.render_discovery`,
  extended to take `ScoredCandidate` instead of a bare `Candidate`).
- **Scoring failures are non-fatal and handled per chunk**, in the same
  defensive spirit as `collect.py`'s per-episode and `digest.py`'s
  per-article handling. A chunk whose call or parse fails is logged and
  deferred whole; other chunks are unaffected. Deferred candidates are
  never emailed and never marked seen, so they are simply reconsidered on
  the next sweep. The email reports how many were deferred, so a quietly
  shrinking sweep stays visible.
- **If nothing could be scored at all, the email says so** and proposes
  nothing. It does not fall back to emailing the unscored list: mailing a
  couple of hundred unvetted shows and then suppressing them forever is
  strictly worse than reporting that scoring is broken, and it would
  defeat the entire purpose of this ticket.
- **Only candidates actually emailed are recorded as seen.** Anything
  scored below `MIN_SCORE`, and anything deferred, stays unrecorded so a
  better prompt or a working run can still surface it later.

**Transcription**
- Local **faster-whisper** (CTranslate2), model `medium` by default, running
  on Actions CPU. faster-whisper is ~4x faster than openai-whisper for the same
  model with no torch dependency, which is what makes the more accurate
  `medium` affordable within the collect time budget (roughly where the old
  openai-whisper `small` landed). Decoding is biased toward finance jargon via
  an `initial_prompt` glossary and pinned to English. Model size is an env knob
  (`WHISPER_MODEL`).

**LLM**
- **One extraction call per source item**, always via **Claude Code CLI** using
  a long-lived subscription OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`), i.e. zero
  marginal cost. For a podcast episode this happens at collect time
  (transcript via stdin); for an article (ticket #7) it happens at digest time
  (article body, or abstract, via stdin) since there is no article collect
  step. Model overridable via env either way. Aside from articles, the digest
  step still makes no LLM call: an episode's card is built entirely from the
  extraction already computed at collect time. The monthly discover run
  (ticket #8) is the one exception to "one call per item": it scores its
  whole candidate batch in a single call -- see "Podcast discovery" above.
- The shared `prompts/extract.txt` prompt takes one source item at a time and
  is told, via a `{{KIND}}` placeholder, whether it's reading a podcast
  transcript, the full text of an article, or a paper abstract, so it can
  calibrate accordingly -- an abstract is scored/summarized only on what it
  itself states, not assumed to have the full paper's detail behind it. The
  strict-JSON output contract and shape (`score`/`one_liner`/`tags`/`recap`/
  `implications`/`watch`/`terms`/`key_claims`) is shared by podcasts and
  articles; `render.py` uses a `kind` field on each record to choose "Listen"
  vs "Read". The recap-format change (2026-08-20) replaced the old bullet
  `summary` list with a prose `recap` plus a persona-angled `implications`
  line and optional `watch`/`terms` sections (each omitted from the card when
  empty); `render.py` still falls back to an old-shape `summary` list for any
  record queued before the change.
- **`prompts/extract.txt` and `prompts/score_candidates.txt` (ticket #8)
  share one persona/priorities statement** via a `{{PERSONA}}` placeholder
  filled from `prompts/persona.txt` (loaded by `podcast_fetcher.persona`),
  rather than each prompt hand-stating the same priorities and risking the
  two silently drifting apart.
- The extraction prompt demands **strict JSON output** so downstream rendering
  is simple templating, with a tolerant parser that extracts the JSON object if
  the model wraps it in prose.
- On Windows, the Claude CLI must be invoked via its real `claude.exe` rather
  than the `.cmd`/`.ps1` npm shim: the shim requires a `cmd.exe` relay hop
  (plain `CreateProcess` can't launch a `.cmd` directly), and that hop was
  confirmed, via live testing, to silently truncate large piped stdin before it
  reached the model. `llm.py`'s `_resolve_claude_executable()` prefers the real
  `.exe` (via `CLAUDE_CODE_EXECPATH` or a derived path) and falls back to a
  plain PATH lookup elsewhere, since other platforms (incl. the GitHub Actions
  Linux runners this pipeline actually runs on) have no such shim/relay.

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
23:00 UTC Sun-Thu (= 07:00 HK Mon-Fri) with a 23:30 backup; discover monthly
(1st of the month, 21:17 UTC). Concurrency is serialized (queue, do not cancel)
so runs don't race on the committed JSON state. `workflow_dispatch` allows
manual runs with a mode override.

**Config knobs (env):** `RUN_MODE`, `WHISPER_MODEL`, `MAX_RECENT_DAYS` (3),
`EPISODES_PER_FEED` (2), `MIN_SCORE` (3), `MAX_EPISODES_PER_RUN` (8, hard cap
per collect), `COLLECT_TIME_BUDGET_MIN` (50, wall-clock budget -- ticket #9),
`MIN_EPISODES_PER_RUN` (2, floor attempted even past the budget -- ticket #9),
`MAX_EPISODE_ATTEMPTS` (3, retry cap before an our-side deferral becomes
terminal -- ticket #9), `MAX_TRANSCRIPT_CHARS`, `MAX_ARTICLES_PER_DIGEST` (10,
cap on articles extracted per digest run -- ticket #7), `DISCOVERY_LIMIT` (25,
cap on iTunes results requested per search term -- ticket #5),
`DISCOVERY_BATCH_SIZE` (25, candidates scored per Claude call -- ticket #8),
`CLAUDE_MODEL`, `EMAIL_TO`, `EMAIL_FROM`. Articles reuse `MIN_SCORE` and
`MAX_RECENT_DAYS` unchanged rather than getting their own knobs.

**Collect run bounding and failure handling (ticket #9).** A collect run is
bounded in wall-clock time: it stops starting new episodes once
`COLLECT_TIME_BUDGET_MIN` is reached, but always attempts at least
`MIN_EPISODES_PER_RUN` first (the floor wins so a slow prior run never starves
this one to zero work); the workflow job also carries a `timeout-minutes: 90`
hard backstop. Deferred episodes are simply left unrecorded, so they stay
eligible next run. Per-episode failures are split by cause: an **episode-side**
failure (bad audio, a transcription error, or a malformed-but-successful LLM
reply -- `LLMParseError`) is recorded `failed` (terminal, never retried); an
**our-side** failure (`ClaudeUnavailableError` -- the Claude CLI missing,
token expired, rate-limited, hung/timed out, or crashing) is recorded
`deferred` with an attempt counter and does **not** burn the episode, and the
rest of the run is aborted since a known-bad CLI can't score the remaining
episodes either. A cheap `check_claude_available` preflight runs before any
transcription for the same reason. Only `ok`/`failed` records exclude an
episode from future selection (`store.terminal_ids`); a `deferred` record
stays selectable until its attempts reach `MAX_EPISODE_ATTEMPTS`, at which
point it is recorded `failed` so a persistently broken CLI can't re-transcribe
it forever. Selection processes the eligible pool **oldest-in-window first**
(FIFO) across feeds so an episode nearest the `MAX_RECENT_DAYS` cutoff is
handled before it can age out unscored; the per-feed cap still keeps each
feed's newest `EPISODES_PER_FEED`.

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
3. **Email rendering** — given a dict of queued episode records, assert the HTML
   and text contain each episode's title, link, feed name, score, tags,
   one-liner, recap, implications, and key claims (with empty watch/terms/
   implications blocks omitted), sorted by score descending; and
   that the empty/quiet-day case renders the quiet note rather than an empty
   shell.

Ticket #7 added the same kind of pure-logic, no-I/O tests for articles:
article body extraction from a synthetic feed entry and the `min_body_chars`
threshold; `select_articles`' recency/dedup/cap behavior; a unified
score-descending sort across a mix of episode and article records; the
dedup-hash-committed-only-after-a-successful-send ordering in `run_digest`
(a failing `send` must leave `state/seen_articles.json` untouched, mirroring
the existing pending-queue-untouched-on-failure test); and an explicit
assertion that a persisted article record contains no `title`/`body` or any
LLM-generated content (`recap`/`summary`) key.

Ticket #5 added the same kind of pure-logic, no-network tests for discovery:
`normalize_url`/`normalize_name` on the documented equivalence cases
(trailing slash, http/https, case, whitespace); `select_new_candidates`
excluding a match by URL alone, by name alone, against previously-proposed
candidates, and dedup within one batch, while confirming a candidate is
*not* excluded just because it collides with an existing `kind: article`
feed; a failing search term not aborting `run_discover` (fake `search`
raises for one term, the run still emails the rest); the
candidates-recorded-only-after-a-successful-send ordering (mirroring
articles' dedup-hash ordering, asserted against a failing `send`); and the
empty-candidates ("no new candidates") render, including when
`discovery_terms` itself is empty.

Ticket #8 added tests for the scoring pass, all against fakes, no network
or Claude CLI: `build_score_stdin`'s exact id/name/artist/genres shape;
`parse_score_response`'s tolerant-but-strict parsing (prose-wrapped JSON
accepted; missing `scores` key, an out-of-range score, an out-of-range id,
a missing `reason`, or a duplicated id all raise, while an *incomplete*
reply is accepted and yields only the ids present); `score_candidates`
against a fake `run` (asserts the shared persona text landed in the
rendered prompt, the empty-candidate-list short-circuit never calls `run`,
a malformed response propagates as `LLMParseError`, and omitted ids come
back as `missing`); `filter_by_threshold` keeping/dropping by score; and,
at the `run_discover` level, integration cases against a fake `score`:
a below-threshold candidate is emailed to no one and NOT recorded in
`discovery_seen.json` (the subtlest rule in the ticket, since it differs
from every other "mark seen after send" case in this codebase); and a mixed
batch emails and records only the candidates that cleared the threshold.

Hardening the same ticket added chunking tests: `score_in_batches` over a
sub-batch, an exact multiple, and a ragged tail; one failing chunk
deferring only its own candidates while the others still score; a partial
reply deferring only the omitted ids; a rejected batch size of zero; and,
at the `run_discover` level, that a total scoring failure proposes nothing,
says "scoring was unavailable", and records nothing as seen, while a
partial failure still proposes what it could judge, reports the deferred
count, and leaves the deferred candidates unrecorded.

No prior art in-repo (greenfield). Tests use plain `pytest` with hand-built
fixtures; no network or model access. The pipeline is structured so these three
functions are importable without triggering any I/O at import time.

## Out of Scope

- **Phase 2 audio** ("podcast of podcasts"): TTS of the brief, audio assembly, MP3
  hosting, and generating a subscribable RSS feed. **Not planned** (decided
  2026-08-20): the written per-item recap is the intended end product, not a
  stepping stone to audio. User stories 22-23 are retired rather than deferred.
- Auto-discovery that silently adds shows (discovery only *proposes*; humans
  approve).
- Paywalled or Spotify-exclusive shows (no open audio feed).
- Per-segment timestamped chapterization of episodes.
- A web UI / archive site.
- Multi-user support; this serves one recipient.
- **Paywalled article sources** (ticket #7): same reasoning as paywalled
  podcasts -- if a source doesn't openly publish full text (or a genuine
  abstract) via RSS, it's not in scope. FT proper specifically, despite
  being a strong source, is excluded on its own T&C/robots.txt grounds (see
  "Written articles" above).
- **Body extraction / scraping / readability parsing of article pages**
  (ticket #7): a source only qualifies if its own feed already carries the
  body. No HTML-page fetch-and-extract step exists or is planned; adding one
  would blur the "full-text RSS only" line that keeps the redistribution
  question simple.
- **Article-feed discovery** (ticket #5): the monthly `discover` sweep only
  ever searches for and proposes podcasts. There is no free keyless
  directory API for general RSS/article feeds to query the way the iTunes
  Search API covers podcasts, so article sources in feeds.yaml remain
  curated by hand -- see "Podcast discovery" above.

## Further Notes

- Reference implementation studied: `TillAlexanderHani/livescript-shared` — same
  core idea (RSS → Whisper → Claude → email on GitHub Actions with git-committed
  JSON state), and now the same **per-episode card** digest shape (see the
  2026-08-18 revision note above -- an initial cross-episode synthesis design
  was tried, built, and abandoned after real use). Divergences that remain:
  broadened credit/structured-credit persona; Gmail **API** (reusing existing
  OAuth) rather than SMTP app password; a **monthly discovery** sweep; and a
  planned audio phase.
- Maintenance cost of the free stack: the Claude subscription OAuth token expires
  periodically and must be re-minted with `claude setup-token`; heavy days may hit
  subscription rate limits. Accepted tradeoff for zero marginal cost.
- Timezone: HK is UTC+8. 23:00 UTC Sun-Thu delivers 07:00 HK Mon-Fri; Monday's
  edition (Sun 23:00 UTC) naturally covers weekend-dropped episodes via the
  recency window.
