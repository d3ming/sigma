# Scheduled agent tasks

The prompts the reference setup's scheduler runs, word for word. Each is a thin wrapper: the work is in the prompt or
skill it names. Times are Pacific and weekdays unless said; the owner set them (2026-10-28), see [README.md](README.md).
Every task publishes through the reviewed release (AGENTS.md, To release): commit to `develop`, `make release`, two
independent reviews of that SHA, the `LGTM` comment, `make release-land`. None of them fast-forwards `main` or deploys by itself.

## X edition (weekdays 07:15, live by 08:00)

> You are the Wire operator. Repo: <repo>. Read AGENTS.md, then follow skills/x-daily/SKILL.md exactly, using
> .venv/bin/wire. That skill is the source of truth: the status loop, the edition per prompts/x-daily.md, stances,
> prune, the Alpha index (`wire alpha-index`), commit, then the release and the live check. This is the X-only publish:
> the podcast issue is not part of it.
>
> If there is no usable scan, write no edition from any other source and run no X tool yourself; publish nothing and
> report "X edition skipped: <reason>".
>
> First, before anything else, tell the owner the run has started (time, and the time it was due) and run
> `wire step begin --scheduled 07:15`. Time every step as skills/x-daily's Step timing says.
>
> Finish with 3 lines: X published or skipped and its headline, the release SHA and PR link, and the edition's URL; then the
> output of `wire step table`.

## Podcasts plus X (weekdays 15:30, live by 17:00)

> You own Wire, at <repo>. Publish today's daily issue and today's X edition in one release: cd to the repo, read
> AGENTS.md, then follow prompts/daily.md exactly (launchd's 14:30 job has fetched and transcribed), then
> skills/x-daily/SKILL.md for the X edition and the release. These two files are the single source of truth for this run.
> The X edition rebuilds today's date from the whole day: this publish is the canonical one.
>
> Run `wire alpha-index <today>` after labelling today's X scan (prompts/daily.md); the X step runs it again.
>
> After the run, make sure today's operator standup exists where the deployment keeps standups (Done, Next, Blocked
> on the owner), based on this run and today's entries in data/decisions.md. Nothing about holdings, buy or sell calls,
> or secrets. If one exists, leave it alone.
>
> Finish with 3 lines: the issue's headline and the X edition's, the release SHA and PR link, and the live URL.

## Weekly digest (Sundays 15:30, after the 14:30 fetch)

> You own Wire, at <repo>. Publish this week's weekly digest with themes: cd to the repo, read AGENTS.md, then follow
> prompts/weekly.md exactly. That file is the single source of truth for this run.

## The scanner (another agent)

> Follow skills/x-scan in the Wire repo for today's date, then skills/x-digest. Pull the repo first.

The scanner's own schedule is set in its routine, not here: its scan must have landed before each X run starts (07:15 and
15:30). A run that finds no usable scan stops and reports it.
