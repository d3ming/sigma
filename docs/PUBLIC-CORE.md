# Public core

Wire is meant to go public again, with the tooling as the product. This page says which files are generic tooling, which are
the owner's flavor of it, and what to do before the repository's visibility changes. It is a plan, not a change: nothing here
alters who can see the repository. Direction: [PRODUCT-DIRECTION.md](PRODUCT-DIRECTION.md).

## The rule

A stranger must be able to clone the repo, replace the flavor files with their own, and run the pipeline and the site. Nothing in
the generic tooling may need the owner's follow lists, scores, notes, accounts or deployment. Private data lives in the darkroom
repository (private) and reaches the code only through `data/` (a link made by `scripts/setup.sh`) or an environment variable.

## Generic tooling (stays public)

| What | Where |
|---|---|
| Pipeline: fetch, transcribe, ingest, rank, ground-check, publish | `wire/` (everything except the flavor rows below), `conftest.py`, `pyproject.toml` |
| Judgment steps, as prompts any agent can follow | `prompts/`, `skills/` |
| Output contracts | `schema/` |
| Alpha index and its site: signals, picks, day pages, JSON for agents | `wire/alpha_index.py`, `wire/alpha_sentiment.py`, `wire/alpha_site.py`, `schema/alpha-index.schema.json` |
| Site publisher: the static build, the design tokens, the search API | `wire/site.py`, `web/`, `api/`, `site-assets/` (a placeholder icon set), `vercel.json` |
| Tests, checks, hooks | `tests/`, `scripts/`, `.githooks/`, `.github/` |
| Docs | `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `docs/` |
| Generic reference data | `us-tickers.json` (a public ticker list) |

## The owner's flavor (config a user replaces)

These are public today because they are plain config and the site shows their results. A new user supplies their own.

| What | Where | Note |
|---|---|---|
| What to follow | `sources.yaml`, `people.yaml`, `creators.json`, `x-accounts.json`, `show_links.yaml`, `entities.json` | Replace wholesale. The code reads them from the repo root. |
| Published output | `published/` | One instance's results. A fork starts with this empty. |
| Site identity | `BASE_URL`, `MAKER`, `X_PROFILE` and the site name in `wire/site.py`; the site address in `api/search.py` and the verify example in `wire/cli.py` | `WIRE_BASE_URL` already overrides the address at build time. The rest should move to one config file before the repo is advertised. |
| Mac scheduling | `deploy/mac/` (job labels, paths, install script) | An example setup, with the owner's job names in it. |
| Daily agent instructions | `prompts/daily.md`, `prompts/x-daily.md`, `deploy/mac/tasks.md` | Generic in logic; they name the owner's routine times. |

## Private (never in this repo)

Lives in the darkroom repository, linked in as `data/`:

- the call ledger and its grading (`calls/`, price caches). Track records never reach the site or `published/`;
- `creators-private.json` and outlets behind a login;
- X scans, digests, heartbeat files and the follow reasons behind `x-accounts.json`;
- decision notes, score evaluations, run folders, transcripts, the library database;
- holdings: never in any repo, never in a digest, never in a message.

`wire/calls.py` in this repo is the ledger's code. It reads and writes only under `data/` and nothing on the site path may import it
(a test checks). It is generic tooling, and its inputs are private.

## Leak scan, 2026-10-28

Scanned the working tree and history of the develop branch (275 commits).

- Secrets, tokens, keys, and Slack or Notion ids: none in the tree or history.
- Personal paths: only fixtures in tests (`/Users/me/...`) and the pattern the ranked-file check rejects. None real.
- Holdings: none. History holds an old module that read weights from a private endpoint and was deleted. It never held data.
- Transcripts: none. History has `transcripts.json` index files (episode id, URL, length), no text.
- The maintainer's handle appears in site identity and deploy files (listed above), by design. No home address, email or phone.
- Ledger, scores and follow reasons: none in the tree. `published/` carries only stance labels, claims and Alpha signals.
- Private-word list: `.private-words` is git-ignored and absent from a fresh clone, so `scripts/private-words.sh` checks nothing there.
  Run it on the owner's machine before any visibility change.

## Before the visibility changes

1. Run `scripts/private-words.sh` with the owner's list, and scan history with the same list (the script covers the tree only).
2. Move the site identity constants to one config file; keep the current values as the owner's config.
3. Decide whether `published/` stays in the repo or moves to the site's own branch.
4. Decide whether the flavor files stay here or move to darkroom with a documented example set in their place.
5. Add a short "run your own" walkthrough to `README.md` using the example set.
