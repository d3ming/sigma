---
name: worker-rules
description: >
  Wire's rules for a worker a lead has delegated to: how to run the code from a worktree, what never to run or write,
  how to prove and land, what to report. Preloaded by the implementer, deep-implementer and planner roles; load it
  yourself if you were started without it. Not for the lead.
---

# Worker rules

The lead owns scope and landing; you own one piece. Root `AGENTS.md` is already in your context; these rules add what
a worker in a worktree needs and the briefs do not repeat.

## Start

- Other workers are changing this repository at the same time. Branch from current `origin/main`
  (`git fetch origin`; your worktree may be older), stay inside the files the brief names, and rebase on `origin/main`
  right before your last commit.
- Check the brief's premise against the code and data before building on it. A false premise is a report, not a
  workaround.

## Run the worktree's code

- The venv lives in the main checkout and its `wire` script refuses to run in a worktree. Use
  `<main checkout>/.venv/bin/python -m wire.cli …` and `PYTHONPATH=. <main checkout>/.venv/bin/pytest -q` from the
  worktree.
- The site builds with nothing installed: prove it with `/usr/bin/python3 -S -m wire.site --out <scratch dir>`.
- A command that needs a run folder reads `runs/<name>/` in your worktree: copy the files it needs (a `manifest.json`)
  from the main checkout. Copy, never link.

## Never

- Run `wire today`, `daily`, `fetch`, `transcribe`, or any `x` command that scans X. They start the real pipeline.
- Write the main checkout's `runs/`, `data/` or `published/`. Read them freely; for a step that writes the X data
  folder, point `$WIRE_X_DIR` at a copy in your scratch. Published output you produce goes in your worktree's
  `published/` and lands with your commit.
- Use bare `git stash`, push to anything but `main`, or open a pull request.
- Put private research in the public repo: no copied post or newsletter text, no holdings, no reasons for following
  someone (AGENTS.md, Rules).
- Start subagents.

## Land

- Commit in your worktree. Push only when the brief says so; otherwise the lead reviews and pushes.
- Proof is the command in use on real data or a faithful copy, with what it printed, in the commit message or report.
  `pytest -q` must pass in under 5 s; most changes need no new test (CONTRIBUTING.md).
- A change to published data ships with its republish: run the step by hand for the days or runs it affects and commit
  the result.
- Report: commit hash and branch, the proof, numbers before and after when the change moves a number people read, and
  what you did not verify.
