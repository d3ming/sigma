# Weekly themes (for the agent writing themes.json)

Input: `runs/<week>/ranked.json`, written by `rank-merge`. Output: `runs/<week>/themes.json`, valid against
`schema/themes.schema.json`, then `wire themes-check runs/<week> --top 15`. `publish` runs the same check and
refuses on an `invalid:` line, then exports the file to `published/<week>/themes.json` and the site shows it at the top
of the weekly page. A week without `themes.json` publishes as before.

The goal: a reader who will not scroll 40 episodes learns what the week's investors, executives and AI builders were talking about,
who agreed, and where to look. You read `ranked.json`: every episode's `reason` and `claims`, not only the top 15.

## 1. Pick 3-5 themes

- **Across episodes.** A theme is something at least two episodes (`episode_ids`, 2 or more) from different shows
  discussed. One episode's headline is not a theme, however good; do not restate it.
- **Decision-relevant.** Prefer what an investor or someone tracking AI could act on or check: a company, sector, price,
  capacity, capability, regulation or timing question. Skip the generic ("AI is big") and the one-off anecdote.
- **Prefer what several shows discussed.** More shows beats more episodes of one show. Order the themes by that
  breadth, then by relevance.
- **Name both sides of a split.** `stance: "split"` means speakers disagreed: the summary says who holds each view.
  `consensus` means they agreed, `emerging` means a few early voices on something new and not yet widely discussed.
- **Any ranked episode can be a source of the theme** (`episode_ids`), also those below the top 15. The cited
  `evidence` must sit in the top N the digest publishes, so a reader can find it on the page.

## 2. Fields

- `week_of`: the same as `ranked.json`. `run`: the run folder's name, for example `2026-10-19-weekly`.
- `headline`: one sentence about the week, 160 characters at most. Not a list of theme titles.
- `title`: 80 characters at most, plain words, no ticker-only titles.
- `summary`: 2-3 sentences, 420 characters at most. What people said and whether they agreed. Your words: copy
  no run of 12 or more words from a transcript (this holds for the headline too), no hype, no advice.
- `stance`: `consensus`, `split` or `emerging`.
- `tickers`: only tickers on the claims you cite in `evidence`, spelled as in `ranked.json`. May be empty.
- `episode_ids`: every ranked episode where the theme came up, at least 2. The site shows "Came up in N of M
  episodes" with N this list's length and M all ranked episodes, so list them all and nothing that only brushed it.
- `evidence`: 2-4 items `{episode_id, claim_index}`. `claim_index` counts from 0 in that episode's `claims`. Choose
  claims that show the theme, from at least 2 different shows. Each evidence episode must also be in `episode_ids`, and
  each claim must pass the claim checks `publish` runs (a claim that fails there invalidates the theme).

Never put holdings, weights or portfolio data in it. Never put your reasoning in it.

## 3. Check, then write the rationale

1. `wire themes-check runs/<week> --top 15`. Fix the file for each `invalid:` line and rerun; never edit
   around a check.
2. Append a `Run` entry to `data/decisions.md` (git-ignored, private; use the entry format at the top of the file): the date and run, the themes you chose and why, the
   candidates you rejected and why (for example one episode only, one show only, too generic), and any judgment calls
   (a stance you hesitated over, an episode you left out of `episode_ids`). `data/decisions.md` is private: the
   rationale never goes in `themes.json`, `published/` or a commit message.
3. Run `publish` as `prompts/weekly.md` says.
