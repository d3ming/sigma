# Architecture

The map of the repo: what each part does, where its code and data live, and why it is built this way. The code is the
reference; `wire <command> --help` lists every flag, and each module's docstring says what it owns.

## The split

Deterministic code fetches, transcribes, checks, stores and builds the site. An LLM agent makes the judgment calls,
following a prompt in `prompts/` or a skill in `skills/`: which episodes matter, what was said, how bullish a claim is,
what X said today. Code never calls a model. Every file an agent writes has a schema in `schema/` and a check in code that
refuses it until it is grounded in a transcript or a post. `wire status` (and `wire x status`) names the next step, so the
agent never has to remember the order.

## What it produces

| Product | Who makes it, when | Flow | Code | Agent instructions |
|---|---|---|---|---|
| Daily issue | launchd 14:30 PT fetches and transcribes; an agent at 15:30, live by 17:00 | `today` → `transcribe` → `rank-prep`/`rank-merge` → `check` → `links` → `report` | `fetch`, `ingest`, `people`, `triage`, `transcribe`, `whisper`, `rank`, `report`, `links` | `prompts/daily.md`, `rank.md`, `select.md`, `report.md` |
| Weekly top 15 | Sundays, same times | `fetch --refetch` → `transcribe` → `rank-prep`/`rank-merge` → `publish` | `rank`, `ranked`, `themes`, `digest` | `prompts/weekly.md`, `rank.md`, `themes.md` |
| Custom set | on request | `find` → agent picks → `custom-run` → `transcribe` | `custom` | none: the agent decides |
| Social: YouTube | inside the daily and weekly runs | `style: influencer` sources are scored apart | `rank`, `creators` | `prompts/rank-influencer.md` |
| Social: X edition | the scanner agent before each run; an agent at 07:15 (X only, live by 08:00) and again at 15:30 with the podcasts (live by 17:00, canonical) | `x status` → `x prep` → `x check` → `x publish` → `x prune` | `xdaily`, `xprune`, `xlinks` | `skills/x-scan` (scanner), `skills/x-daily`, `prompts/x-daily.md` |
| Alpha index | with the 15:30 run, again in the X step | `alpha-index` after `stance-merge` and `x prune`; never waits. Also adds `tickers[]` and `markets[]`: the day's X signals per ticker, one vote per speaker, labelled on a 5-step scale or Mixed (`alpha_sentiment`, a deterministic rule, no model) | `alpha_index`, `alpha_sentiment`, `stance` | `schema/alpha-index.schema.json`, `prompts/stance.md` |
| Sentiment board | after each run publishes | `stance-prep` → readers → `stance-merge`; summed at site build | `stance`, `board`, `tickers` | `prompts/stance.md` |
| Search | nightly upload; live API | `search-index --upload` → `api/search.py` | `searchindex`, `api/search.py` | none |
| Site | twice a weekday, once per publish, through `make release-land` | `wire site` builds `dist/`; `deploy/mac/site-deploy.sh` deploys it. The home page stays the podcast home and opens on Newest (episodes rated 6 or more, newest day first): a status line says "Updated today" when the newest day is today in Pacific time (otherwise "Last update <day>"), and that day's rows are marked New. There is no separate latest-issue page: a daily issue's address redirects to `/#d-DATE`, which opens the list on that day, while its Markdown, JSON and claims files stay for agents. With `published/alpha/` data it gains a collapsible "X signals" panel with the X mark, X-sourced signals only (open beside the podcasts on a wide screen, closed on a phone, choice kept in localStorage; closed it is a slim scrolling ticker tape of per-ticker items only (`NVDA ▲ Bullish`, `MU ◆ Mixed`; no date, count or summary), CSS only, pauses on hover or focus and is a scrollable strip under reduced motion, each ticker linking to its row on /alpha/DATE/), `/alpha/` is the full Alpha page: one card design for the home panel, the day pages and `/x/` (a collapsed `<details>` per daily pick and per market, `TICKER ▲ Bullish · 3/3` over one line saying what was said, in Wire's words with no counts; it opens to X's official embeds of the posts behind it (a link-only `blockquote.twitter-tweet` with `data-dnt`; widgets.js is loaded on the first card open, at most 10 show with a "Show N more" button, and a plain handle-and-arrow link list stays as the fallback; podcast signals are one link line); low confidence only fades the card; "More from today" (`details.rest`) holds every other ticker, collapsed; each ticker appears once, with the X read merged into its card), `/x/` and its day pages open with the Alpha view, and `/alpha/*.json`, `/alpha/schema.json`, `/research/` are written; `make preview` (`scripts/preview.sh`) serves a rebuilding local copy on port 8787; `/podcasts/` redirects to `/`. The Sentiment page gets an X column (the latest Alpha day's per-ticker X read) beside Net, which is unchanged, and an "X on DATE" list of tickers X had a view on that have no board row | `site`, `alpha_site`, `alpha_sentiment`, `entities`, `published` | none |

The private call ledger (`wire calls`, `calls.py`) grades creators' calls against prices. It never reaches the site.

## Where things live

| What | Where | Public |
|---|---|---|
| Code, prompts, skills, schemas | this repo | yes (repo is private until a planned relaunch; keep it ready) |
| What Wire follows | `sources.yaml`, `people.yaml`, `x-accounts.json`, `creators.json`, `entities.json`, `show_links.yaml` | yes |
| Everything the site shows | `published/<run>/`, `published/x/`, committed to `develop`, released to `main` | yes |
| Run folders: manifests, transcripts, logs | `runs/<name>/`, on the Mac only | no |
| Library, feed cache, event log, X scans, decision log, notes, call ledger | `data/`, a symlink into the private `darkroom` repo (`darkroom/wire/`), committed by `deploy/mac/darkroom-commit.sh` | no |
| Search index | private Vercel Blob store `wire-search` | no |
| The site | Vercel project `wire`, at wire.dming.si; pushes do not deploy, `site-deploy.sh` does, from `main` (production); `develop` has no automatic build | yes |

The Mac runs everything: see [deploy/mac/README.md](../deploy/mac/README.md) for the schedule and setup. Agents with only a
checkout read `published/`; an investor agent starts at [agent-guide.md](agent-guide.md).

## Design decisions

- **No LLM calls in the code.** Any agent can run the prompts, the repo needs no model keys, and every mechanical step is
  testable. The cost is a runbook, which `status` and the prompts are.
- **Check the agent, don't trust it.** Schemas plus grounding checks turn a hallucinated timestamp, a number never spoken
  or a copied sentence into an error the agent must fix, not a published claim.
- **Free sources only.** RSS, iTunes Search, YouTube and local Whisper: nothing to pay for or rotate. The X scan is the
  exception, run by the scanner agent on its own X API account.
- **One manifest per run, locked writes.** `transcribe` runs for hours while other commands update the same file, so
  every write goes through `manifest.update`.
- **Never guess a link.** No match means no link, not the closest one. Hand edits to `show_links.yaml` are never
  overwritten.
- **Once-only judgments.** An episode's first score and an item's first stance label are kept; changes go into the
  prompt for new items, so the site's history never shifts under a reader.
- **SQLite for the library.** No server, fast full-text search, queryable from a shell. Local to the Mac; `published/` is
  the copy for everyone else.

## One claim per point

The ranking pass, the report's signal bullets and its section claims each state what was said, in their own words, so one
moment can come back as three claims. `claimdedupe` merges them without a model: same episode, same speaker (a role such as
`host` matches a name), within 60 seconds, the same key figures (a conflict blocks the merge) and similar words. The most
complete wording stays and takes the union of the tickers. It runs in `library.ingest_run` (so a new publish is clean), in
`wire dedupe-published` (rewrites existing `published/*/claims.jsonl`, idempotent) and in `site.build_episodes` (two runs may
word one moment differently). Precision wins over recall: a near miss stays as two claims.
A data check backs it: `wire check-claims` (and a test over the real `published/`, so `make release` and the push hook run it)
fails on any pair of claims in one claims file that make the same point, and `published.export` refuses to write such a file.

## Known limits

- Claims are checked against transcripts, not filings or prices.
- Whisper does not label speakers and misspells names; speakers come from the agent.
- YouTube blocks data-center IPs, so video-only shows and YouTube lookups need the Mac's home connection.
- On Linux or Intel, Whisper falls back to CPU `base.en`: slower and worse on names than MLX on Apple silicon.
