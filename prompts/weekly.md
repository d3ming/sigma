# Weekly runbook

Produce the week's checked digest in the configured data root. Do not change code, accounts or schedules while operating it.

Choose a run name and use `sigma fetch --days 7 --refetch --run-name <week>`. Use the run directory printed by the command. `--refetch` includes episodes that daily runs already saw; existing scores retain their original ownership.

Follow `sigma status <run> --weekly` and its next action. Score batches using the named rank prompts, validate them, and select the weekly ranking. If themes are requested, use `prompts/themes.md`; source citations must identify the actual ranked claims. Validate and publish with the command status supplies. A missing manifest, transcript or valid claim blocks publication rather than weakening the check.

Optional stance labels use `sigma stance-prep <run>` and `sigma stance-merge <run>` with `prompts/stance.md`. Existing labels are retained. Record selection reasons and exclusions in the private decision log.

Save output only in the configured data root. `deploy/mac/data-commit.sh` can save it when the data root belongs to a private Git repository. Never stage publication output or transcripts in Sigma. Build and inspect the complete site before any separately authorized production upload.

Finish with the digest and theme titles, actual output location, source dates and any blocker. State whether it was only built or actually deployed.
