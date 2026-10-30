# Scheduled agent tasks

The prompts a scheduler can run, word for word. Each is a thin wrapper: the work is in the prompt or skill it names.
The operator chooses when each one runs, in whatever scheduler runs the agent; see [README.md](README.md). A clock time in a prompt below is a placeholder. Run output is saved under `SIGMA_DATA_ROOT`
with `deploy/mac/data-commit.sh`. A data-only site update is a separate operator action: run `make publish` from the
production `main` checkout after saving private data. Source changes go through an owner-reviewed release PR; scheduled
tasks do not deploy the site.

## X edition (weekdays, after the scan lands)

> You are the Sigma operator. Repo: <repo>. Read AGENTS.md, then follow skills/x-daily/SKILL.md exactly, using
> .venv/bin/sigma. That skill is the source of truth: the status loop, the edition per prompts/x-daily.md, stances,
> prune, the Signals index (`sigma signals-index`), and save the private data. This is the X-only edition:
> the podcast issue is not part of it.
>
> If there is no usable scan, write no edition from any other source and run no X tool yourself; publish nothing and
> report "X edition skipped: <reason>".
>
> First, before anything else, tell the owner the run has started (time, and the time it was due) and run
> `sigma step begin --scheduled <HH:MM>` with the scheduled time. Time every step as skills/x-daily's Step timing says.
>
> Finish with 3 lines: X edition written or skipped and its headline, the private data save status, and its path; then the
> output of `sigma step table`.

## Podcasts plus X (weekdays, after the fetch job finishes)

> You own Sigma, at <repo>. Prepare today's daily issue and X edition: cd to the repo, read
> AGENTS.md, then follow prompts/daily.md exactly (the launchd job has fetched and transcribed), then
> skills/x-daily/SKILL.md for the X edition. These two files are the single source of truth for this run.
> The X edition rebuilds today's date from the whole day and is saved with the daily data.
>
> Run `sigma signals-index <today>` after labelling today's X scan (prompts/daily.md); the X step runs it again.
>
> After the run, make sure today's operator standup exists where the deployment keeps standups (Done, Next, Blocked
> on the owner), based on this run and today's entries in data/decisions.md. Nothing about holdings, buy or sell calls,
> or secrets. If one exists, leave it alone.
>
> Finish with the issue and X edition headlines, the private data save status, and any preview URL actually checked.

## Weekly digest (once a week, after the weekly fetch job)

> You own Sigma, at <repo>. Prepare this week's weekly digest with themes: cd to the repo, read AGENTS.md, then follow
> prompts/weekly.md exactly. That file is the single source of truth for this run.

## The scanner (another agent)

> Follow skills/x-scan in the Sigma repo for today's date, then skills/x-digest. Pull the repo first.

The scanner's own schedule is set in its routine, not here: its scan must have landed before each X run starts. A run that finds no usable scan stops and reports it.
