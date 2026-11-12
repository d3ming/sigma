---
name: worker-rules
description: >
  Sigma's rules for a worker a lead has delegated to: how to run the code from a worktree, what never to run or write,
  how to prove and land, what to report. Preloaded by the implementer, deep-implementer and planner roles; load it
  yourself if you were started without it. Not for the lead.
---

# Worker rules

The lead owns scope and landing; you own one piece. Root `AGENTS.md` is already in your context; these rules add what
a worker in a worktree needs and the briefs do not repeat.

## Start

- Other workers are changing this repository at the same time. Branch from current `origin/develop`
  (`git fetch origin`; your worktree may be older), stay inside the files the brief names, and rebase on
  `origin/develop` right before your last commit.
- Check the brief's premise against the code and data before building on it. A false premise is a report, not a
  workaround.

## Run the worktree's code

- Run `make check` first: it gives the worktree its own `.venv` (about a second, with `uv`). Then run code as
  `.venv/bin/python -m sigma.cli …` from the worktree.
- Private data lives in the data root the brief names, never in this repository. For any command that writes, copy
  what it needs into your scratch and point `SIGMA_DATA_ROOT` at the copy; copy, never link. Set `SIGMA_NO_EVENTS=1`
  on any command run against the real root, because the event log writes into it.
- Prove the site with `SIGMA_NO_EVENTS=1 SIGMA_DATA_ROOT=<copy> .venv/bin/python -m sigma.cli site --out <scratch>
  --published <copy>/published`; it prints `[site] built …`.

## Never

- Run `sigma today`, `daily`, `fetch`, `transcribe`, or any `x` command that scans X. They start the real pipeline.
- Write the real data root's `runs/`, `x/` or `published/`. Read them freely; for a step that writes the X data
  folder, point `$SIGMA_X_DIR` at a copy in your scratch. Published output is private data: it never lands in this
  repository, so keep any you produce in your scratch.
- Use bare `git stash`, push to anything but `develop`, or open a pull request.
- Put private research in the public repo: no copied post or newsletter text, no holdings, no reasons for following
  someone (AGENTS.md, Tenets).
- Start subagents.

## Land

- Commit in your worktree. Push only when the brief says so; otherwise the lead reviews and pushes.
- Proof is the command in use on real data or a faithful copy, with what it printed, in the commit message or report.
  `make check` must pass; most changes need no new test (CONTRIBUTING.md).
- A change to published data does not republish from a worker: name the days or runs it affects in your report. The
  lead republishes them through the `develop`→`main` release PR and `make publish` from the release checkout; a worker
  never runs `make publish`.
- Report: commit hash and branch, the proof, numbers before and after when the change moves a number people read, and
  what you did not verify.
