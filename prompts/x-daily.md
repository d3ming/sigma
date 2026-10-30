# Write the daily X edition

Input: `<x dir>/days/<date>/prep.md`, the day's Signals posts from `sigma x prep`.
Output: `<x dir>/days/<date>/edition.json`, valid against `schema/x-edition.schema.json`. Run
`sigma x check <date>` and fix the edition until it passes, then run `sigma x publish <date>`. `sigma x status <date>`
shows the next step.

The edition is about **what happened in this window**, not a summary of each account. Its reader follows public-market
research and wants the event, the evidence and what posters said it means.

## What to write

- `headline`: the day in one line, under 120 characters.
- `signals`: the day's posts edited into 3 to 5 themes, most important first. Read all the posts first and find what
  several accounts were circling: a company's results, a sector move, the market's setup or a trade many made. Each
  theme gets a short title that states its point and 1 to 3 sentences that read as one paragraph. Give every sentence
  under a theme the same `theme` string. The first sentence says what happened and why it matters; later ones add who
  did what and where they disagree. Group what several accounts said rather than writing one sentence per post.
- Each sentence's `cites` lists the 1 to 3 post ids that support it, best first. Every id must be from this scan.
- `posts` lists 8 to 15 posts a reader should open, best first, including every cited post. Put real moves and specific
  plans before news. Prefer a post with a number, mechanism or firsthand fact over a reaction.
- `sigma x publish` adds the day's other top-ranked posts under “More from today”; `posts` need only contain the ones
  the sentences rely on and the best of the rest.

## Rules

- Numbers come from cited post text or quoted post text. A chart is not a source for a figure. Describe it in words
  without writing a number from it. The check rejects unsupported numbers.
- Paraphrase. Never copy 12 or more words in a row from a post; the check rejects it.
- Attribute claims: “posters argued” or “@handle says,” not as fact. Do not add buy or sell calls, unsupported price
  targets, or the owner's holdings. A poster's public statement about their own portfolio, weights or positions is a
  claim to attribute to that poster with its post link; never present it as the owner's or as Sigma's view.
- Skip promotions, giveaways, memes and posts that only restate a headline without adding anything.
- If the window was quiet, write fewer sentences. Never pad.

Example sentence (ids are placeholders):

```json
{"theme":"Memory names ran on SK hynix's sold-out guide",
 "text":"Posters tied the move in memory names to SK hynix's sold-out guide, while disagreeing on how much was already priced in.",
 "cites":["2114856726474449176","2114705241832620399"]}
```
