---
name: score-eval
description: Measure and improve Wire's episode scoring (prompts/rank.md) against the owner's gold set, one change per round, until the top of the ranking matches the owner's judgment. Use when the owner disputes a score or an ordering, before any change to prompts/rank.md, when adding gold labels, or when a weekly eval shows drift.
---

# Score eval

The score is Wire's core judgment: it orders the Top list, the weekly ranking and the daily picks. This skill keeps
it honest. The rubric is changed only through a measured round, and the measure is the owner's own judgment, written
down as a gold set.

Everything here lives in `data/score-eval/` (git-ignored: gold labels are research). The code is
`wire/scoreeval.py`, run as `wire score-eval pool|prep|grade|table`.

## What "good" means

In order of weight:

1. **Top-region order** (`band_pairs`). Every pair inside the gold top 15 whose gold scores differ is put the right
   way round; a tie counts half. This is the headline: the reader sees the top first. `top_pairs` counts every pair
   in the strict gold order, including pairs gold itself scores the same; a whole-number score cannot order those,
   so it has a ceiling below 1 (gold's own tied pairs at half) and is shown for reference only.
2. **The top beats the rest** (`edge`). Every gold-top episode scores above every episode outside it.
3. **Owner pairs** (`owner_pairs`). Every "A beats B" the owner has stated. These must be 1.00.
4. **Precision at 10** (`p_at_10`). Gold top 10 that land in the predicted top 10, ties broken by tier as the site does.
5. **Guardrails**: mean absolute error against gold (`mae`), share within one point (`within_1`), and spread between
   repeat runs of the same episode (`rep_sd`). These must not regress outside noise.

Every reported number is on the `test` split as well as `all`. The analyst reads train only.

## The gold set

- `gold.jsonl`: one row per episode: `gold` (1-10), `order` (1..15 for the top region, strict), `why`, `by`
  (`owner` or `editor`), `split` (`train` or `test`, fixed once, random within score bands), and the transcript path.
- `pairs.jsonl`: `{better, worse, why, by}`. Every time the owner says "X should beat Y", add a pair, even when
  X or Y is not yet in gold; add the missing episode too.
- `editor-brief.md`: the owner's taste in prose. Editors label from it, never from the rubric, so gold and rubric
  stay independent.

**Adding labels.** Candidates come from `wire score-eval pool` (library episodes with a score and a transcript).
Label new ones with fresh editor agents: give each 5-6 episodes, the brief and the condensed transcripts under
`cond/`, and ask for a dossier per episode (speakers and how rarely they are heard, up to four material new facts with
timestamps, a score, why, `not_higher`, `not_lower`). Then one calibration pass orders the top region from the
dossiers alone. Show the owner the top 15 and every changed label; the owner's word overrides an editor's and sets
`by: owner`. Re-grade every variant after a gold change (`grade` is free: it re-reads stored outputs).

## One round

1. **Prep.** `wire score-eval prep vN --reps 2 --size 10`: snapshots `prompts/rank.md` into `vN/rubric.md` and
   writes `vN/in/rep<r>-b<k>-in.json`. Batches are seeded per rep, so every variant scores the same batches.
2. **Read.** One fresh reader agent per batch, nothing else in its context: the variant's `rubric.md`, its input
   file and the transcripts it names. Tell it to open nothing else under `data/score-eval/`. Output goes to
   `vN/out/<same name>-out.json`. Readers never see gold, prior scores or other batches.
3. **Grade.** `wire score-eval grade vN` writes `vN/results.jsonl` and `vN/summary.json` and prints the status table.
   It lists every missing or unknown id; a round with problems is incomplete and is not compared.
4. **Analyze, train only.** A fresh analyst agent gets the train rows of `results.jsonl` (score, gold, the reader's
   reason), the train gold rows with `why`, and the current rubric. It names the one behavior that costs the most
   top-region pairs and proposes one change. It must describe the behavior, not paste episode names or facts into
   the rubric. Save its rationale to `vN+1/change.md` and the diff to `vN+1/change.patch`.
5. **Decide.** Keep a change when the test headline improves outside noise and no guardrail regresses outside
   noise; otherwise revert. Noise: the spread between two baseline reps of the same variant. On a tie, keep the
   simpler rubric.
6. **Record.** Write the status table (`wire score-eval table`) and a short paragraph to `data/score-eval/narrative.md`:
   which variant wins and why, in terms of the changes. Append the decision to `data/decisions.md`.

Stop when the test headline has not moved outside noise for three rounds, or `owner_pairs` is 1.00 and `band_pairs`
and `edge` are both above 0.90. Then ship it (below). Do not climb past the point where the remaining misses are
8-versus-9 calls on labels only an editor made: show those to the owner first.

When a round stalls, read the train failures before writing another change, and sort them: a rubric gap (keep
going), a wrong gold label (ask the owner), a reader that ignored a clear rule (change the rule's place or form, not
its wording), or noise (more reps).

## Levers worth trying

The rubric text is one lever. Others: the order of the rubric's sections; worked examples per band (descriptions of
the episode type, not real episodes); a required `not_higher` sentence; sub-scores the code combines; batch size;
and a second, comparative pass over a run's top episodes against a few fixed calibration episodes.

## Shipping a new rubric

The score-once rule holds within a rubric version. A new version is the one time old scores change:

1. Bump the version line at the top of `prompts/rank.md` and commit the rubric with the round's table in the
   commit message (numbers only, no gold content).
2. Re-score every library episode under it (`rank-prep --rescore` per run, readers, `rank-merge`), then re-publish
   the affected issues and the site.
3. Record the version change in `data/decisions.md`.

## Never

- Let a reader or the analyst see gold, test-split outputs, or prior scores.
- Change a gold label to make a variant win. Gold changes only on the owner's word or a new editor pass, and every
  variant is re-graded after it.
- Put gold labels, episode-specific verdicts or owner preferences about named people into the repo. The rubric and
  this skill stay generic.
