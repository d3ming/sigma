---
name: x-daily
description: Write and publish Wire's daily X edition from the scanner's posts - cited sentences about what happened today for two lenses, Alpha (investing) and SI (AI, agents, tech), then the posts behind them. For the Wire operator agent, any model or harness. Run after the scan lands, and again whenever the scan is extended.
---

# X daily edition (editor)

Pull the data repo first (the scanner pushes scans from its own clone). In this repo, work on `develop`: `git checkout develop && git pull --ff-only`. Then loop on `wire x status [D] --json` and do
its `next` until it says `done`. The code knows the order; you supply the judgment.

- `command`: run it.
- `agent`: write `next.output` following `prompts/x-daily.md`, then `wire x check D` until it passes. Fix the file,
  never the check.
- `stop`: no usable scan. Write nothing from any other source; report `scan_problems`. The scanner owns the fix. Publish no X edition.
  At the 3:30 PM run, do not hold back the podcast issue: if `develop` is ahead of `main` with it, go to the release below. At 7:15 AM, stop.
- `done`, already pushed: the X edition is out. At the 3:30 PM run, if `develop` is still ahead of `main` (the podcast issue), go to the
  release below; otherwise stop.
- `done`, not pushed:
  1. Stances: `wire stance-prep --x D`, one reader per batch following `prompts/stance.md` (a small, fast model is
     enough), then `wire stance-merge --x D`.
  2. `wire x prune D`: removes posts deleted on X, as X's terms require, and writes the ids the next scan checks.
  3. `wire alpha-index D`: rebuilds `published/alpha/` (every labelled signal; `complete:false` names a missing
     source, never wait for it). Prune has already dropped deleted posts from earlier days' files.
  4. Commit `published/x` and `published/alpha` ("Publish X edition D"; prune may touch earlier days), run the tests, push to `develop`.

A scan extended after publishing makes `status` say `prep` again: the loop rebuilds D from the whole day and replaces
the edition. Stance labels are never redone.

Every run then releases through the reviewed flow (AGENTS.md, To release); this skill never fast-forwards `main` or deploys by itself.
On weekdays there are two runs: the **7:15 AM** run publishes the X edition alone, live by 8:00 AM (an intraday edition), and the
**3:30 PM** run, after launchd's 14:30 fetch and transcribe, publishes the podcast issue together with the X edition, live
by 5:00 PM (the canonical edition for the day). The edition's date is the Pacific day it covers, so the 5:00 PM run rebuilds
the 8:00 AM edition's date. At 3:30 PM, if the podcast run (`runs/<today>`) is not done yet (`wire status runs/<today> --json`),
wait for it (check every 2 minutes, up to 40 minutes) so the one publish carries both.
Release: `make release`; it tests the exact commit and posts the result on the PR. Get two independent reviews of that SHA (a
Codex CLI session on this Mac, and Bellatrix, the critic bot), each posted on the PR as REVIEW.md says, fix what a review finds on `develop`, and rerun `make release`.
When both are clean, comment `LGTM <sha>` with a `reviews:` line on the PR, then `make release-land` from the main checkout. It
deploys (`site-deploy.sh`: two a Pacific day, a third is refused) and checks the live site; confirm it with
`wire verify <site url> --alpha D` (`--run <name>` for a run published today; a weekly digest also `--expect '<h2>Themes</h2>'`). Then
`wire x heartbeat edition --by <your name>`, log the edition's headline, what led and what you left out in
`data/decisions.md`, return the clone to `develop` (`git checkout develop`), and save the private data repo (`deploy/mac/darkroom-commit.sh` on the reference setup).

## Step timing

A slow publish must say where the time went. The first thing a run does is `wire step begin --scheduled HH:MM` (the time its
schedule says, Pacific): it records how late the run started. Around each step, run `wire step run NAME -- COMMAND...` for a
command, or `wire step mark NAME start` and `wire step mark NAME end` for work no command wraps (writing the edition, a
reader batch, waiting on a review). `make release` and `make release-land` mark their own steps. The log is
`<x dir>/steps/<Pacific date>.jsonl`: private, never published, no post text. `wire step table` prints each step's start, end
and seconds, the gaps no step claims, and the slowest step. Put that table in the run's closing message.

Only `published/x/editions/` is public: ids and Wire's own sentences, never post text.

Weekly, list core accounts no edition cited in the last 10 and propose cuts or additions in the run summary; the list
changes only by the owner's approval. SI is capped at `xdaily.MAX_SI_ACCOUNTS` accounts, so adding one means cutting one.
