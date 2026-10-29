# Weekly runbook

Goal: the week's top-15 digest, published and committed. Run from the repo root with the venv's `wire`.
After any step, `wire status runs/<week> --weekly` shows what is done and the next step. On the Mac a scheduled agent
runs steps 3 onward at 15:30 PT on Sundays; start with `git checkout develop && git pull --ff-only`. If the run folder does not exist, run
`bash deploy/mac/run-weekly.sh` in the background and wait for `done` in `logs/run-<week>.log` (a Monitor or
until-loop). Change no code, settings or schedules; if code is broken, stop and report.

1. Pick a run name, for example `2026-10-19-weekly` (the week's Monday plus `-weekly`; any unused name works).
   `wire fetch --days 7 --refetch --run-name <week>`. `--refetch` keeps episodes the daily runs already saw
   (transcribe reuses their transcripts). On the Mac, `run-weekly.sh` does
   steps 1 and 2 at 14:30 on Sundays.
2. `wire transcribe runs/<week> --top 0 --minutes 6000` (a week is often 50+ hours of audio). This can take hours; it is done when `transcribe.log` says
   `finished`.
3. `wire rank-prep runs/<week> --eval 6`. Episodes the dailies already scored keep that score (`rank/stored.json`);
   only the rest go into `rank/batch-N-in.json`. `rank/eval-in.json` holds 6 scored episodes to re-score blind.
   Episodes from `style: influencer` sources go into `rank/influencer-N-in.json` instead (see step 4).
4. For each batch and for the eval file, one reader (you, or one sub-agent per file, in parallel) follows `prompts/rank.md` and
   writes `rank/<name>-out.json`. Eval readers must not see the stored scores. An `influencer-N-in.json` file is read
   under `prompts/rank-influencer.md`; `rank-merge` keeps those scores in `scores-influencer.json`, out of `ranked.json`.
5. `wire rank-merge runs/<week>` writes `ranked.json` from the new and stored scores, and prints the eval's drift
   (mean change, how many crossed the 6 bar). The eval never changes a stored score. On an error, fix the file it names
   and rerun. Record the drift in `data/decisions.md`; a mean change over 1 point means the rubric needs work.
6. Themes: follow `prompts/themes.md` and write `runs/<week>/themes.json`, then
   `wire themes-check runs/<week> --top 15`. Fix the file on each `invalid:` line. Append your rationale to
   `data/decisions.md` (private), as that prompt says.
7. `wire publish runs/<week>/ranked.json --top 15` checks every claim and the themes, and writes
   `digest-<week_of>.md` (`week_of` is the earliest episode date) and `published/<week>/`, including the themes.
   On an `invalid:` line about a claim, fix that claim in its batch file and rerun from step 5; on one about themes,
   fix `themes.json` and rerun this step.
8. Wire is the publication: do not post to Notion. Optional, before the commit: `wire stance-prep runs/<week>`, one reader
   per `stance/in-N.json` following `prompts/stance.md` (saved as `stance/out-N.json`), then `wire stance-merge runs/<week>`;
   it writes `published/<week>/stances.jsonl`, which step 9 commits. Claims the dailies already labelled are skipped. Market views ride in the same batches (`prompts/stance.md`).
9. `git add published/<week> && git commit -m "Publish weekly digest <week>" && git pull --rebase -q && git push` (on `develop`).
   Never add `runs/`, `data/`, transcripts, `.env*` or tokens. Pushes do not deploy: release the digest through
   the reviewed flow (AGENTS.md, To release: `make release`, two reviews, the LGTM, `make release-land`), which deploys and verifies it.
10. `deploy/mac/darkroom-commit.sh "wire: weekly <week>"` saves the decision log and the run's JSON to the private
    `darkroom` repo (`data/` links into it).

If a check fails and you cannot fix it, publish nothing and report the step and its `invalid:` lines.

Done when `status` says `done` and the commit is pushed. Finish by saying the headline, the theme titles, the digest's
URL, the commit hash, how many episodes were ranked versus fetched, and anything that went wrong.
