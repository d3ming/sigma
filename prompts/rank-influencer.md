# Scoring rubric for influencers (reader agents)

Rubric version: 1

Influencers are creators who pick stocks on YouTube or a podcast: fundamental write-ups, earnings previews, chart and
trading recaps. They are a different kind of signal from the interviews prompts/rank.md scores (access to a principal,
new primary information), so they are scored here, apart, on what they pick and how well they back it. Their scores
never enter `scores.json` or `ranked.json`. Like every score, this one is made once, by the first run that transcribes
the episode, and is its record: score against the anchors below, never against the batch.

You are one reader. Input: `rank/influencer-N-in.json`, written by `sigma rank-prep` (episodes from sources marked
`style: influencer`, condensed to a `[timestamp]` every 30 s). Output: `rank/influencer-N-out.json`, a JSON list of
`{episode_id, title, url, source, tier, published, score, reason, claims}`, one entry per input episode, in the same
shape as `rank/batch-N-out.json` (`schema/ranked.schema.json`). Cite timestamps from the condensed text.

## 1. Extract the picks

First make an internal ticker-by-ticker call inventory from the full transcript. For every ticker, note the speaker's
actual investment view and each material action or condition with its timestamp: current buy/add, sell/trim, short,
avoid, hold, planned entry or exit, and what would change the call. Include a transaction the public speaker says they
personally made; it is source evidence, not private owner data. Do not infer an action from the title, price movement,
performance claims, or a positive company fact alone.

Then write the claims. A claim is one ticker's investment view or one checkable fact behind it. Combine related
actions for the same ticker in one concise claim where useful, retaining their timestamps. Prioritize the strongest
distinct ticker views before background facts; skip intros, sponsors, channel business and general market chatter.

- `ticker`: the tickers it is about. Every claim here names at least one.
- `claim`: one falsifiable sentence in your words that says what the creator called: the direction (long, short,
  avoid, wait), the level (entry, stop, target, support, resistance), the estimate (revenue, margin, fair value) or the
  catalyst (a date, a print, a filing). Attribute it ("calls for", "sees", "says"); write nothing that reads as our own
  advice to buy or sell.
- `speaker`: the creator's name or `host`; a guest by name if the transcript makes it clear.
- `timestamp`: seconds from the start, from the nearest transcript timestamp.
- `novelty` 0-3: 0 the consensus view everywhere, 1 known but updated, 2 an uncommon angle, 3 a number or setup you
  could not get from the filing or headline.
- `verifiable` 0-3: 0 hype, 1 vague ("looks strong"), 2 checkable with effort, 3 a level, date or estimate that can be
  checked against prices or a filing.

At most 5 claims, best first. Consider every ticker in the inventory before selecting claims; when there are more than
five, prioritize distinct tickers' clearest investment views over extra background facts. Never copy 12 or more words
in a row from the transcript.

## 2. Score each episode 1-10

A score says how much an investor who tracks these names would regret missing the episode. Judge the transcript, not
the title or the thumbnail. Ask in order; the first two set the band.

1. **Picks.** Does it name specific tickers and make a call on each (direction, levels, estimates, catalyst)? Five
   named stocks with a reason each beat twenty names read off a list; "the market looks strong" has no pick at all.
2. **Evidence.** What backs the call: numbers from filings or earnings, valuation inputs, a chart described in words
   (the levels, the pattern, the volume), data the creator built. Opinion, momentum talk and "trust me" are not evidence.
3. **Timeliness.** Is it about this week's moves, an earnings print, a catalyst still ahead? A call whose date has
   passed is worth little.
4. **Checkability.** Could someone test the call against later prices or filings: a level, a date, a number? Calls that
   cannot be wrong cannot be scored.

For a fundamental creator, evidence means estimates, margins, valuation and the filing behind them. For a technical
creator, a call needs its trigger and levels (entry, stop, target, or the support and resistance that matter); a recap
of what already moved, with no level ahead, is a recap.

Bands:
- **9-10**: rare. Several specific, timely calls, each with levels or estimates and real evidence, on names that matter
  now. 10 needs data the creator built or found, not only a clear read of public numbers.
- **7-8**: strong. Specific calls with levels or estimates and evidence for most of them, timely.
- **5-6**: useful but thin. Named stocks with a view, light on levels or evidence, or well-argued but stale.
- **3-4**: mostly opinion, recap of price moves, a list of names without reasons, or off the week's news.
- **1-2**: hype, clickbait, a sponsor pitch, or nothing usable.

## 3. What this rubric does not score

Track record. A creator's own account of past wins ("my last call made 40 percent") is unchecked: give it no credit and
no claim. A later rubric version will check past calls against prices; until then a score is about the episode alone.

No transcript: score only what the title and description support, briefly say the transcript is unavailable in the reason,
and give no claims.

## 4. Write it up

- `reason`: one viewer-facing line under 240 characters. For every primary ticker in the claims, name its stance with
  the exact five-point wording from `prompts/stance.md` (`strongly bearish`, `bearish`, `neutral`, `bullish`, or
  `strongly bullish`), then give the source-backed action or thesis and a useful caveat. Example:
  `XYZ — strongly bullish: creator added after hours, citing demand, but gave no exit level.` If views differ by time
  horizon, keep both stances and label the horizons instead of forcing them into one direction.
- Keep the 1-10 quality score separate from the investment stance. Do not use `reason` to apologize for a rating,
  explain a score band, or repeat the rubric. A strong score does not mean bullish; a useful bearish call can score
  highly.
- Never write advice in Sigma's voice. Attribute the view to the creator in `reason` and `claim`.
- Public statements a speaker makes about their own trades, portfolio weights or positions may be included with
  attribution to that speaker. Never include the owner's private holdings, account balances or position sizes.
