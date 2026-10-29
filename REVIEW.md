# REVIEW.md

You review one Wire release PR (`release-candidate` into `main`). Your job: decide whether this exact commit should go
live on https://wire.dming.si. Judge each release on its merits. Give `BLOCK` for any real problem: anything in the
general review or the Wire-specific block list below, and anything else that would harm readers, AI agents or the owner
if it went live. Give `PASS` when you find none.

**Be adversarial.** Try to prove this commit is wrong. Assume nothing is safe until you have checked it yourself: not the
PR description, not a green release check, not a claim in a commit message, not another reviewer's comment. Pick the
riskiest change and try to break it with a bad input, an empty file, a missing field, a second run, a stale cache.
"I saw nothing wrong" counts only for what you actually opened and ran.

## 1. Review the change itself

Do this first, on every PR, as a careful engineer would. Read the whole non-`published/` diff, and the changed lines of
anything in `published/` that the checks flag.

- **Correctness:** does the code do what its commit message and docstring say? Trace one real input through it.
- **Bugs and edge cases:** empty, missing, duplicate or malformed input; the first run and the re-run; time zones (Wire
  dates everything in Pacific time); off-by-one on dates and windows; partial failure halfway through a step.
- **Security:** secrets, shell or path injection, unsafe `eval`/`subprocess`/HTML building from data, anything that leaves
  the machine, a new public endpoint or file the build now copies into the site.
- **Data integrity:** can this change corrupt, drop, reorder or double-write published data? Is a re-run idempotent? Does
  generated output still match its schema and the data it came from?
- **Tests:** does a new behavior have a test that would fail without it, and does a changed behavior still have one? A test
  that asserts the implementation instead of the result, or that cannot fail, is a finding.
- **Simplicity:** is there a smaller change that does the same job? Dead code, a new layer, a flag nobody sets? Say so.

A finding is blocking when shipping it would cause a wrong, unsafe or broken result. Otherwise it is a note.

## 2. Wire-specific things to call out

The general review is the review. This section is what a reviewer new to this repo would not know: Wire's intent, what
this repo's PRs hold, what blocks, what does not, and known quirks. Use it to check the change; do not stop at it.

### What Wire is for

- Wire publishes daily market alpha from podcasts and X: relevant, actionable, news-focused.
- Every output must work for people and for AI agents: clean markdown and JSON, stable URLs, machine-readable indexes.
- The repo is meant to go public again. Anything that must not be public must not be in it.
- Keep everything simple. Ship fast: one review pass, blocking issues only. Everything else is a note.

### What the PR contains

`develop` into `main`. Mostly `published/` data (episodes, claims, `published/alpha/`, `published/x/`) plus the site pages
built from it, sometimes code, docs or prompts. Landing it (`make release-land`: fast-forward `main`, then `site-deploy.sh`) deploys wire.dming.si, so a mistake goes public.
Review the diff of the exact head SHA, not a branch name. Do not read every line of a regenerated `published/` file, but
run `git diff origin/main <SHA> -- published | grep '^+'` through the Wire-specific block list below (holdings and weights,
long quotes, buy/sell words, secrets, person names), and open a sample of new claims against their episode's timestamps.

### Block on (Wire-specific)

1. **Private holdings or position sizes**, and any **third-party portfolio weights** (a real case: a poster's
   NBIS/MU/LITE percentages reached the X edition). Weights of a named person's portfolio are never published.
2. **Quotes of 12 or more words** from a post, transcript or newsletter, and **buy/sell calls** (Wire reports what was said;
   it never tells a reader to buy or sell).
3. **Naming the owner or anyone behind the project** in repo docs, prompts, skills, scripts or commit messages (AGENTS.md,
   Rules): write "the owner" or "the maintainer". A name added in a doc for any other person is a note unless it is private
   information. Host or speaker attribution inside published episode data is fine, and so are reviewer bot names.
4. **Duplicate or near-duplicate claims** in a claims file. `wire check-claims` is the gate, and it is heuristic: it can miss a repeat more than 60 s apart or worded differently. Run it, then read the claims of any episode the PR adds or changes for restated points yourself.
5. **Broken pages, links or alpha JSON**: a link to a page that does not exist, an episode page without its claims, an
   `alpha/<date>.json` that fails `schema/alpha-index.schema.json`.
6. **Contract breaks for agent consumers**: `published/alpha/<date>.json`, `published/alpha/index.json`, `/llms.txt`, the
   schemas in `schema/`. Only additive changes are allowed: a new optional field is fine, and must be in the schema in
   the same PR (the alpha, selected, report, ranked and library-claim schemas set `additionalProperties: false`); renaming, removing, retyping or moving a field or URL is a block.
7. **Secrets**: tokens, keys, cookies, `.env` content, personal paths, anything from `data/` or `runs/`.

### Do not block on

- Style, naming, wording, formatting, or "could be simpler" ideas. Put them in notes (at most five).
- **Public fund rules and public filings.** Example: ARK's 10% position cap is a public rule, not a portfolio weight.
  A figure from a public filing, with its source, is not a holding of ours. Check before you block under item 1. This
  never excuses the weights or sizes of a named person's own portfolio, whatever their source.
- Editorial taste (which episode was picked, how a score was set), as long as the selection rules below hold: every 6+
  episode picked, at least 3 a day, nothing under 5 added, and scores and stance labels not redone (AGENTS.md).
- The deploy cap below delaying the deploy; that is the release owner's call.
- Missing tests for data-only changes.
- Anything already true on `main` and not changed by this PR.

### Repo gotchas (expected behavior; still check that the change does not break them)

- **Two deploys per Pacific day.** `deploy/mac/site-deploy.sh` refuses a third (`.vercel/deploys` counts forced ones too).
  `--force` or `WIRE_DEPLOY_FORCE=1` is only for a deploy the owner asked for. A release that changes only tests, docs,
  prompts, skills, scripts or root docs (AGENTS.md, REVIEW.md, README.md and so on) deploys nothing. The exclusions are the named paths in `changes_site()` in that script (`tests`, `docs`, `deploy`, `prompts`, `skills`,
  `scripts`, `.githooks`, `.github` and the named root docs), and they apply only when a deployed-commit stamp exists.
- **Every clone that lands a release needs a `.vercel/` folder** holding `project.json` (the link to the Vercel project) and the
  deploy log that counts the day's deploys. On the second clone it is a symlink to the primary clone's `.vercel/`, so both
  count the same deploys. Without it `make release-land` fails; that is setup, not a PR defect.
- **`cleanUrls` is on** (`vercel.json`). Vercel redirects `/episodes/<id>.claims.html`, which the home-page podcast cards
  fetch, to `/episodes/<id>.claims`. `fetch` follows it. A `.claims.html` link that redirects is expected.
- **Claim dedupe** (`wire/claimdedupe.py`) merges claims of the same speaker within 60 s that share figures or most words.
  A role ("host", "guest", "unknown") counts as any speaker. It blocks a merge across negation, opposite words
  (grew/fell, bought/sold) or different scales and tags, but only by word lists, so check by eye. Two similar claims that
  differ on those are correct. `published.export` and the suite refuse restated claims.
- **Podcast floor.** A day has at least 3 episodes and no upper limit; the best 5s fill up to 3 as `lower_confidence`.
  `wire check selected published/<day>/selected.json` checks it against that folder's `scores.json`. A day with fewer than 3
  episodes is legitimate only when fewer than 3 episodes scored 5 or more; otherwise it is a block.
- **GitHub sometimes keeps a PR's old head SHA after a push.** If the PR head is not the SHA you were given, re-query once
  (`gh pr view <n> --json headRefOid`); if it still differs, review nothing and tell the release owner, who closes and
  reopens the PR. You never close, reopen or edit the PR. `make release-land` refuses a head that no check or LGTM names.
- **`make release-land` needs a comment line `LGTM <sha>`** from a writer, in a comment that also has a `reviews:` line.
  All agents post as one GitHub account, so the script cannot tell reviewers apart. You never post LGTM; the release owner does.
- **Agent commits carry an `Agent: <name>` trailer** (the operator's is `Agent: Vega`). It is a convention: no hook
  enforces it and older commits lack it. A missing one is a note, not a block.
- **Release flow:** work on `develop`; `main` only moves through `make release` and `make release-land`. A fix goes on
  `develop` and `make release` refreshes the same PR, which changes its head SHA, so the old reviews no longer count.

## Run before deciding

```bash
git fetch origin && git checkout --detach <SHA>   # the SHA you were given; confirm `git rev-parse HEAD` matches
.venv/bin/wire check-claims                       # the duplicate-claims gate
git diff --stat origin/main <SHA>                 # what ships
git diff origin/main <SHA> -- . ':!published'     # code, docs, prompts: read all of it
```

Read the newest `wire-release-check` comment on the PR. It must name this SHA and say pass for the suite and the local
preview; if it is missing, failed or names another SHA, that is a finding, not something to assume. You need not rerun the suite. Do not edit files, push, merge, comment `LGTM`, or run `make release*`.

## How to post

Post one comment on the PR for the exact head SHA. The first three lines are fixed:

```
Reviewer: <your name>
SHA: <full 40-character head SHA you reviewed>
Verdict: PASS|BLOCK
```

`Verdict:` is exactly one of `PASS` or `BLOCK`. Then:

- `Blocking:` one bullet per finding, each with the file and line (or URL) and what to change. Write `Blocking: none` when there are none.
- `Notes:` at most five short non-blocking bullets, or `Notes: none`.

Post it with:

```bash
gh pr comment <PR number> --repo d3ming/wire --body-file review.md
```

(Write `review.md` first, outside the repo, or pipe it with `--body-file -`.) Find the number with
`gh pr list --base main --head release-candidate --json number,headRefOid`. If `headRefOid` differs from your SHA, the PR
head moved or is stale (see gotchas): say so in your reply, and post nothing for a SHA that is not the head.
Do not review, and do not post, for a SHA you could not check out and read.

During the trial two reviewers (a Codex CLI session and Bellatrix) review each head independently, without reading each
other's comment first. Fixes land on `develop`; after `make release` refreshes the PR, review the new head the same way.
