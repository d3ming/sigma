# Daily runbook

Goal: today's report, published and committed, with no human input. Run from the repo root with the venv's
`wire` (see AGENTS.md). `status` tells you what is next; do not guess the order. On the Mac a scheduled agent runs
this at 15:30 PT on weekdays, after launchd's 14:30 fetch and transcribe (`deploy/mac/run-daily.sh`, log
`logs/run-<date>.log`).

0. `git checkout develop && git pull --ff-only` (daily work is on `develop`; `main` only moves at release). If today's issue is already published and no new episodes came in, say so and stop.
   Change no code, settings or schedules; if code is broken, stop and report.
1. Run `wire today`. It starts today's run if it does not exist (the 14:30 job did not run: Mac asleep or job not
   installed), then prints the status.
2. Loop: run `wire status runs/<name> --json --record` and act on `next`:
   - `wait`: transcription is running. Wait until `transcribe.log` says `finished` (a Monitor or until-loop, not
     repeated sleeps), then run status again.
   - `command`: run `next.command` exactly, then run status again.
   - `agent`: follow the prompt file in `next.prompt` (`prompts/rank.md` to score, `prompts/select.md` to pick,
     `prompts/report.md` for links and the report), write the file it names, then run `next.command` to validate it.
   - `done`: stop.
3. `blockers` lists validation errors. Fix the file and rerun the command; never edit around a check.
4. Stage notes:
   - **Score:** every transcribed episode is scored once, here. `rank-prep` batches only the episodes the library has
     not scored; give each `rank/batch-N-in.json` to a reader (you, or one sub-agent per batch) and save
     `rank/batch-N-out.json`. `rank-merge` writes `scores.json` and stores the scores in the library.
     `rank/influencer-N-in.json` (episodes from `style: influencer` sources) are different: a reader follows
     `prompts/rank-influencer.md` and saves `rank/influencer-N-out.json`; `rank-merge` writes them to
     `scores-influencer.json`, apart from `scores.json`, so they are never select candidates.
   - **Select:** if `missed.md` exists, read it first. At least 3 picks a day, no upper limit for 6+, filled from the best 5s
     (`lower_confidence`) when under 3; `prompts/select.md` has the rules and `check selected` enforces them.
   - **Links:** find each pick's YouTube video by web search. Set `youtube_url` only on a title-or-guest and date
     match, then run `wire links runs/<name>`.
   - **Publish:** Wire is the publication; do not post to Notion. After the commit below, run
     `wire mark publish end --run runs/<name>`.
   - **Stances (optional; a run publishes without them):** after `report`, run `wire stance-prep runs/<name>`. Give each
     `stance/in-N.json` to a reader (you, or one Sonnet-class sub-agent per file; not Haiku for claims) following `prompts/stance.md`, save
     `stance/out-N.json`, then `wire stance-merge runs/<name>`. It writes `published/<name>/stances.jsonl`, which the
     commit below carries; fix the file on each problem line it prints. The batches also hold claims that read like a
     market view and earlier items owed a market read (`market_only`); the prompt says how to label them.
   - **Alpha index:** `wire alpha-index <name>` writes `published/alpha/<name>.json` and `index.json`: every
     stance-labelled signal of the day for agents. The same file carries `tickers[]` and `markets[]`, the X signals added up per ticker (a deterministic step in the same command; nothing extra to run). If today's X scan has landed (`wire x status --json`), first label its posts
     (`wire stance-prep --x <name>`, readers per `prompts/stance.md`, `wire stance-merge --x <name>`) so the file has both
     sources. Never wait for a missing one: the file says `complete: false` and names it, and the X step (skills/x-daily) runs
     `wire alpha-index` again after its own labels and prune.
   - **Commit:** `report` writes `published/<name>/`. Commit and push it to `develop`:
     `git add published/<name> published/alpha && git commit -m "Publish daily report <name>" && git pull --rebase -q && git push`.
     Never add `runs/`, `data/`, transcripts, `.env*` or tokens.
   - **Release:** not here. Pushes do not deploy. The 15:30 run publishes this issue with the day's X edition in one
     release (`skills/x-daily`: `make release`, two reviews, the LGTM, `make release-land`), live by 17:00, and verifies it.
   - **Entities:** run `wire entities check`. For each company, person or show it lists that you can place, add an entry to
     `entities.json` (a person's company and role, a show's topics, a company's aliases and topics) and commit it with the
     run. Leave a name alone when you are not sure; never guess an employer. Mention what you added in the decision log.
   - **Decision log:** append a `Run` entry to `data/decisions.md` (git-ignored; the format is at the top of the file;
     create it from that format if missing): the picks and why each cleared the bar, close calls left out and why,
     and any judgment call (a speaker you named by role, a claim you dropped). Never commit it to Wire.
   - **Darkroom:** `data/` is a link into the private `darkroom` repo. Run
     `deploy/mac/darkroom-commit.sh "wire: daily <name>"`: it saves the decision log, notes and this run's JSON there.
5. Next morning, if you have the TMTB Podcast Intel newsletter (the outside list of essential episodes we benchmark
   against): `wire tmtb-import <email.txt>` records recall, the share of its episodes our picks covered.

If stuck:
- `status` keeps saying transcribe is interrupted: run the `next.command` it prints; add `--force` only if
  `transcribe.lock` names a process that is no longer running.
- Whisper or another tool is missing: `wire doctor` names it and exits 1.
- A check fails and you cannot fix the file: stop and report the `blockers` lines instead of publishing.

Never read the TMTB newsletter before selecting: it arrives at 2:40 PM, and seeing it would spoil the recall measure.

Finish by saying the picks, the issue's URL, the commit hash, any `notes` the last status printed, and anything that
went wrong.
