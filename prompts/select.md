# Select must-watch episodes (daily)

Input: a daily run folder (`manifest.json`, one `.md` per episode, and `scores.json`: every transcribed episode,
already scored 1-10 with claims).
Output: `selected.json` in the run folder, valid against `schema/selected.schema.json`.
Check it with `sigma check selected runs/<name>/selected.json`; the check enforces the floor below.

The count: **at least 3 picks a day, and no upper limit.** Pick every episode scored 6 or more, best first, however
many that is. If fewer than 3 score 6 or more, fill up to 3 with the best episodes scored 5, each flagged
`lower_confidence: true` (the report labels them). Never pick anything below 5, even to reach 3: on a day with fewer than
3 episodes scored 5 or more, pick them all and stop. A day with several 6s is not capped at 3.
The floor counts podcast interviews only (`scores.json`). Episodes from influencer sources (`style: influencer`, scored apart in
`scores-influencer.json`) and X posts never count toward it and are never picked; `check selected` rejects an influencer pick.

1. Start from `scores.json`: candidates are the episodes scored 5 or more, best first. Read their claims and reason;
   open the transcript only to settle a close call. Do not rescore: the score is the record, and the site ranks by it.
   Novelty and decision-relevance are already inside the score, so you may not drop a 6+ for being "not new enough" and
   you may not use them to stay under 3. Every scored episode must have a transcript; if one that should be a candidate
   has none (`transcribe_skip` in `manifest.json` says why), run `sigma transcribe --top 0` and score it first.
2. A pick must pass all of these:
   - Speaker: an executive on their own company (CEO, CFO, founder, lab head; `kind: exec`) or an investor with a
     named fund view (`kind: investor`). Analysts only with primary research (`kind: analyst`). No `other`.
   - Decision-relevant: could change a view on a named public company, sector or supply chain, or on where AI and
     robotics capabilities are heading.
3. Reject: recaps, news and markets shows (daily briefings, anchor-led roundups), clip compilations, hosts-only chat,
   reruns, and repeat appearances that add nothing new. One pick per person.
4. `left_out`: list every episode scored 6 or more that you do not pick, and (on a day under 3 picks) every 5+ you pass
   over, each with its `reason` (`news_show`, `recap`, `clip`, `hosts_only`, `speaker_other`, `duplicate_person`, `rerun`,
   `not_decision_relevant`, `repeat_appearance`) and an optional one-line `note`. The check fails a 6+ with no entry, and
   fails a day under 3 picks while a 5+ remains that no hard rule (the first seven reasons) rejects.
5. Prefer genuinely new episodes (published under 24 hours before the run). Skip `rerun: true` (replays, re-airs).
6. Prefer episodes with a real transcript (`has_transcript: true`). `fallback_text: true` means the text is a short show
   description, not a transcript: if you still pick it, set `fallback_text: true` and say "fallback" in `why`.
7. `guests`: names and roles as the episode states them. `why`: one sentence naming the new fact and who it affects.
   For a `lower_confidence` pick, say what holds it back.
8. Never include holdings, position sizes or weights.
