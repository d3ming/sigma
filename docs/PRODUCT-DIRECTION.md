# Product direction

Set by the owner on 2026-10-28. This changes what Wire makes and how it is organised. Where an older doc disagrees, this
one wins.

## 1. Market alpha is the main product

- It updates at least daily.
- Podcast and X signals for Alpha must be highly relevant, actionable and news-focused. A signal that is not any of the
  three is cut, not softened.
- Cadence, scoring and source choices are judged by one question: does this help someone act on today's news?

- Selection floor (owner, 2026-10-28): a day surfaces at least 3 episodes and has no upper limit. Every episode scored 6+ is
  picked; with fewer than 3, the best 5s fill up to 3, labeled lower-confidence. Nothing under 5 is added.

## 2. SI moves to a few deep reports

- SI (AI news and how-tos) does not need daily cadence. Stop treating it as a daily feed.
- Replace it with a few deep research reports, each kept up to date about weekly.
- First report: **Coding factory**, the best practices for coding agents and personal agents. It can be one long article
  or several linked ones.
- Sources are YouTube, X and the web. Go deep on a few topics instead of wide on many.

## 3. Usable by humans and by AI agents

Every published thing, in both products, must work for a person and for an agent:

- Clean markdown and JSON, not markup that only a browser makes sense of.
- Stable URLs that do not change once published.
- Machine-readable indexes: what exists, what changed, what each report cites.

## 4. Wire goes public again

- The public core is the tooling: the research pipeline and the site publisher. Anyone can run their own research or
  publish their own site with it.
- The owner's site is one flavor of that tooling, not the product.
- Personal config and data stay separable from the tooling, in darkroom (private). What Wire follows, its scores and
  notes, and any account or deployment detail must not be needed to run the public core.

## Priorities, in order

Set by the CIO, who is Wire's priority-setter for this work. Do them in this order; the owner can reorder.

1. **An agent-readable Alpha index, before the SI reports.** One JSON file per day with every Alpha signal, ready with each publish (8:00 AM and 5:00 PM PT).
   Each row has the ticker, the stance, the speaker and their role, a link to the timestamp, the post or episode ID, and
   whether the source is primary or a recap.
2. **Make "actionable" gradable.** Each signal names a company or sector, a direction and a timeframe, so the creator-call
   ledger can grade it at 5, 21 and 63 trading days. Later, weight sources by that record and cut the ones that fail.
3. **Favor first-hand and primary data over recaps.** Examples: Korean chip exports, Taiwan monthly sales, data center
   leases, grid queues, and interviews with the operators who run the business.
4. **The SI deep reports come second.** The order of their topics waits on the owner.
5. **Keep the private record private.** The creator-call ledger, scores and follow reasons stay in darkroom and never go
   in the public core.

## What follows from this

Not decided yet; each needs its own plan before work starts:

- Alpha: tighter relevance and action tests for podcast and X picks; faster turnaround.
- SI: the report format, the weekly refresh, and what happens to the daily SI lens.
- Agent access: the index files and URL scheme.
- Public core: which files are tooling and which are the owner's flavor, and how the latter is split out.
