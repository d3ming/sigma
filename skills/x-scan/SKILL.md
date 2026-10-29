---
name: x-scan
description: Scan the X accounts Wire follows and deliver the day's raw posts in Wire's scan format. For the scanner agent, which reads X through the official API. Run before each X run (weekdays, so the scan lands before 07:15 and again before 15:30), and again whenever asked for an on-demand scan. Read-only on X.
contract_version: 1
---

# X scan (scanner)

You collect the day's posts from the accounts in `x-accounts.json`; Wire filters, ranks and writes the edition. So keep
every post the API returns, judge nothing, and add nothing of your own to the scan. After it is delivered, write the
day's private digest (step 8).

The contract is this file, `schema/x-scan.schema.json` and `wire x scan-check`. Copy `contract_version` (front matter)
into every manifest; `scan-check` refuses another version, which means your copy of this file is stale: pull and re-read.
When a rule here cannot be met, deliver what you have with `complete: false` and say why in the manifest's `notes`.

## Setup

- A clone of this repo with `python3 -m venv .venv && .venv/bin/pip install -e .`, for `x-accounts.json` and the checker.
- `WIRE_X_DIR`: the folder scans go in, inside a private data repo you can push to. Post text is the authors' and never
  goes in this repo or anywhere public.
- Use clones of your own, not working trees another job commits from. Pull both before a run; end it with both clean.

## Each run, for date D (today, Pacific time)

1. **Window.** From the `window_end` of the newest manifest under `$WIRE_X_DIR/scan/` (24 hours back when there is
   none) to now, never more than 72 hours. If `scan/D/` already exists this run extends it: add only posts whose id is
   not there yet and rewrite its manifest to cover the whole day. Never overwrite earlier posts.
2. **Accounts.** Every `core` account in `x-accounts.json`, all Alpha accounts before any SI account, so that running
   out of calls costs SI posts first.
3. **Posts.** Each account's own posts in the window: no reposts, no replies to other people (replies to itself, its
   threads, stay), the full text of long posts, and each quoted post once (`quoted.jsonl`). Make sure paging covered
   the whole window for every account; an account with nothing usually means the search missed it, so check it alone.
4. **Deletions.** If `$WIRE_X_DIR/check-ids.json` lists ids, look each up and report in `ids_gone` the ones X says no
   longer exist or are no longer visible. X's terms require Wire to delete those, and Wire deletes on your word, so a
   failed or unclear lookup is never "gone": leave it unchecked and say so in `notes`. Never post text here.
5. **Write** `scan/D/posts.jsonl`, `quoted.jsonl` and, last, `manifest.json`, as the schema says.
6. **Check** with `.venv/bin/wire x scan-check D` until it prints `ok`, and act on its warnings. Fix the files, never
   the check.
7. **Deliver.** `.venv/bin/wire x heartbeat scan --by <your name>`, then commit `scan/D/` and the heartbeat to the data
   repo and push. Beat after every run, a failed one too: it is how Wire tells "the scanner is down" from "a quiet day".
8. **Digest.** Follow `skills/x-digest` for D. It never delays step 7.

## Rules

- Read-only on X: never post, like, reply, follow, bookmark or message.
- To change this skill, `skills/x-digest` or a prompt you need, open a pull request on this repo. Never edit another
  agent's working tree.
- Two failed calls in a row, or a rate limit you cannot wait out before the edition runs: stop, deliver what you have
  with `complete: false`. There is no fallback scanner.
