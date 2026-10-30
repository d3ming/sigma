# Scoring rubric (reader agents)

Rubric version: 2

Every episode is scored once, by the first run that transcribes it, and that score is its record: the site ranks by
it and later runs reuse it. So score against the absolute anchors below; never against a week or a batch.

You are one reader. Input: `rank/batch-N-in.json` (or `rank/eval-in.json`, a blind re-score of already-scored episodes
that measures drift), written by `sigma rank-prep` (episodes with real transcripts, condensed to a `[timestamp]` every
30 s). Output: the same name ending `-out.json`, a JSON list of `{episode_id, title, url, source,
tier, published, score, reason, claims}`, one entry per input episode. Cite timestamps from the condensed text.
`rank-merge` combines the batches into `ranked.json` (`schema/ranked.schema.json`) and rejects ids it does not know;
`publish` rejects timestamps or numbers the transcripts do not support. Merge does not rescale scores, so score against
the absolute anchors below, not against the other episodes in your batch.

## 1. Read and extract claims

For each episode with a transcript, read it and keep the claims an investor, or someone tracking AI and robotics, could act on or check.
Skip ads, intros, banter and vague opinion. Each claim has:

- `ticker`: list of tickers it is about (`private:Name` for private companies; empty if none).
- `claim`: one falsifiable sentence in your words. No hedging filler.
- `speaker`: name if the transcript or context makes it clear, else role (host, guest), else `unknown`.
- `timestamp`: seconds from the start, taken from the nearest transcript timestamp.
- `novelty` 0-3: 0 widely known, 1 known but updated, 2 uncommon angle, 3 new primary information.
- `verifiable` 0-3: 0 opinion, 1 hard to check, 2 checkable with effort, 3 checkable against filings or public data.

Keep at most 5 claims per episode, best first. One claim per point: if the speaker returns to a point, or says it two ways,
write it once, with its figures and the company it is about. A claim that only restates another in fewer words is dropped
(`sigma` merges such repeats anyway, but the best wording is yours to choose).

## 2. Score each episode 1-10

The reader is a public-equity investor in technology and AI: hyperscalers, frontier labs, semiconductors and their
supply chain, data centers and power, AI software, robotics and space. A score says how much this reader would regret
missing the episode. Judge the transcript, not the title.

Ask these in order. The first two set the band; the rest move within it.

1. **Access.** Who speaks with authority, firsthand? A CEO, CFO or founder of a large company or frontier lab, or the
   person who ran the thing, is worth most, and more the rarer it is: a principal who seldom gives long-form interviews
   outranks one who is on a podcast every week. Then a top analyst with proprietary data, then operators of smaller
   companies, then hosts and commentators.
2. **Materiality.** Could what is said change estimates for a large company or for the AI buildout as a whole
   (capacity, demand, capex, pricing, unit economics, supply limits, timelines, strategy)? A new number that moves a
   very large company outweighs an equally new number about a niche or a private startup.
3. **Novelty.** Not already in a press release, filing or the week's headlines. A principal repeating the last
   earnings call is worth less than one adding to it.
4. **Evidence.** Specific numbers, mechanisms and names that can be checked, not vibes.

Bands:
- **10**: a must-hear of the quarter. A rarely heard principal of a very large company or frontier lab discloses new
  numbers that change the picture for that company or the buildout.
- **9**: a must-hear of the week. Principal access with new, material, checkable information; or analyst work with
  proprietary data that changes how the market should model something big.
- **8**: strong. Most investors in the space should hear it: firsthand detail with specific numbers, or a top analyst
  with real data.
- **7**: worth it for specialists in that corner: real firsthand or analytical content, narrower or less new.
- **5-6**: solid but skippable: known theses, recaps, or interesting material with little investment consequence.
- **3-4**: thin, mostly opinion, or off this reader's beat (culture, politics, sports, general business history)
  however well made.
- **1-2**: nothing usable.

News-recap and market-wrap shows, hosts riffing on headlines, and panels restating known theses sit at 6 or below
even when lively. A commentator's own experiment or model can reach 8, but sits below a rare principal disclosing
something of comparable materiality.

A rarely heard principal of a large company or frontier lab who gives firsthand figures on their own capacity,
bookings, supply limits, or demand against supply is disclosing new numbers, as material as capex or revenue; do not
hold them a band lower for lacking capex, margin or guidance figures. Senior technical and operating leaders count as
principals for what they run. Such a principal scores at least one band above an analyst or investor working from
others' data at comparable materiality, never level with them.

Scores are absolute: never spread or squeeze them to fit a batch. A batch of strong interviews can be all 7 and up.

Keep score-band comparisons internal. The viewer-facing summary describes the investment content.

## 3. Tier rules

- Tier 3 (low-priority shows): at most 2 episodes in the ranking. Drop the weaker extras. Creators who pick stocks are
  not tier 3: they are `style: influencer` sources, scored apart under prompts/rank-influencer.md, and never reach you.
- Tier 3 is never a top pick: no tier 3 episode in ranks 1-3, whatever its score.
- No transcript: keep the episode, score it on title, description and tier only, say so in the reason, and give it no claims.

## 4. Write it up

- `reason`: one viewer-facing line under 240 characters: lead with the primary ticker and the speaker's five-point
  investment stance from `prompts/stance.md`, then their stated action, thesis or condition. Read the whole transcript
  before choosing facts; public buy/add/sell/short/hold statements take priority over background numbers. If no
  investment view is stated, say so and name the material disclosure; never turn good business news into a buy call.
  Keep each ticker's stance separate, attribute the view, and preserve different time horizons. The evidence-quality
  score is separate from bullishness; never fill the summary with a rating justification.
- Order by score, then by tier, then by recency. `rank` starts at 1.
- Never include holdings, weights or portfolio data in `ranked.json`.
