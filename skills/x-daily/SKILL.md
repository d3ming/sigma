---
name: x-daily
description: Write Sigma's daily X edition from a completed scanner run, validate cited Signals sentences and synchronize deleted posts. Use for editing an edition, not for broad discovery or posting as an account owner.
---

# Edit the X edition

Refresh the configured private scan data through its operator workflow. Loop on `sigma x status [D] --json` and follow `next` until done. The status output owns the order and paths.

- For `command`, run the supplied command.
- For `agent`, write `next.output` using `prompts/x-daily.md`, then run `sigma x check D`. Fix the file when validation fails.
- For `stop`, publish nothing from another source; report the exact scan problem. A missing X scan does not invent an edition or prevent an independently checked podcast issue.

When the edition is valid, label the eligible posts through `sigma stance-prep --x D` and `sigma stance-merge --x D` using `prompts/stance.md`. Run `sigma x prune D` to remove posts confirmed deleted, then `sigma signals-index D` to rebuild the structured desk. A missing source is recorded as missing; do not borrow yesterday's data.

An extended scan restarts prep for the same Pacific day. The rebuild includes the full day's eligible posts; existing stance labels are retained. The published records contain source IDs and Sigma's own paraphrases, not raw post text.

All output stays under the configured data root. Never stage `published/x` or `published/signals` in the public source repository. Save private data with `deploy/mac/data-commit.sh` when configured. Build and check the whole publication before a separately authorized production upload; source review does not authorize posting or deployment.

Record the edition's headline, what led, rejected candidates and validation problems in the private decision log. Use `sigma step` for timing when the operator requests it, and report the actual output location and anything that blocked completion.
