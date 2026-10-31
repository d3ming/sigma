# Daily runbook

Produce today's checked podcast report in the configured data root. Run the installed `sigma` command from its checkout. Do not change code, accounts, schedules or deployment configuration while operating an edition.

1. Run `sigma today` and use the run directory it prints.
2. Loop on `sigma status <run> --json --record` and follow `next`. For an agent step, read its named prompt and write the specified file. For a command step, run the exact command and return to status. For a wait, observe the named transcription process or log before retrying.
3. Fix each reported validation error in its source file; do not weaken checks or invent missing evidence. If the error cannot be fixed, stop and report the exact blocker.
4. After the report is checked, label eligible claims through `sigma stance-prep <run>` and `sigma stance-merge <run>`, following `prompts/stance.md`. Rebuild the day with `sigma signals-index <date>`; a missing X source stays explicitly missing.
5. For transcribed episodes selected for the website, use the project `podcast_editor` role and `prompts/edit.md` to write separate key insights and chronological summaries in the run's `editor.json`. Reuse a reviewed edit when its source hash and prompt version are unchanged. Validate with `python -m sigma.editor <run>`, review semantic attribution and every cited interval, then re-export with `sigma export-published <run>`. Preserve ranking, claims and stance owners. Keep failed drafts separately until repaired; never replace reviewed output with a failing edit.
6. Save the private output and record the picks, borderline exclusions, attribution decisions and unresolved source gaps in the data root's decision log. `deploy/mac/data-commit.sh` can save it when that data root is in a private Git repository. Never commit publication output, scores, transcripts or follows to Sigma.

Routine publication reuses unchanged edits and show artwork from ingestion metadata. Prompt/model comparisons are development work; do not repeat them for each issue or curate an image for each episode.

Every transcribed episode is scored once under the active rubric. Selection keeps all eligible 6+ episodes, with no upper limit. When fewer than three clear that bar, the best 5s fill up to three and are marked `lower_confidence`. Never pad with a lower score or drop a qualifying episode just for novelty. `check selected` enforces the floor.

The X edition follows `skills/x-daily`. Build and inspect the complete publication before any separately authorized production upload. Report what was produced, its source date, where it was saved, and any remaining blocker. Do not call a local build deployed.
