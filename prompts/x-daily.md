# Write the daily X edition (editor)

Input: `<x dir>/days/<date>/prep.md`, the day's posts from the tracked accounts, best first within each lens: Alpha
first, then SI (written by `wire x prep`).
Output: `<x dir>/days/<date>/edition.json`, valid against `schema/x-edition.schema.json`. Check it with
`wire x check <date>`; fix the file until it passes, then `wire x publish <date>`. `wire x status <date>` tells you where you are.

The edition has two lenses, and the reader is a public-equity investor in technology and AI. X is live news, so each is
about **what happened in this window**, not a summary of each account.

- **Alpha**: public-market investing, from the Alpha accounts.
- **SI**: how to get more done with AI agents, from the SI accounts. Its reader uses Claude Code, Codex, Grok Bot and
  Muse every day, and wants what makes them work better more than AI news.

## What to write

- `headline`: the day in one line, under 120 characters.
- `alpha`: the day's Alpha posts edited into **3 to 5 themes**, most important first. Read all the Alpha posts first and
  find what several accounts were circling: a company's print, a sector move, the market's setup, a trade many made.
  Each theme gets a short title that states its point ("Memory names ran on SK hynix's sold-out guide", not "Memory")
  and 1 to 3 sentences that read as one paragraph, each carrying the same `theme` string. Write it as a good market
  column: the first sentence says what happened and why it matters, the next ones add who did what about it and where
  they disagree; vary the openings and never start two sentences the same way. What to look for, in order of value (owner,
  2026-10-28: real moves count far more than news):
  1. Real moves: a buy, sell, trim or add, a new or closed position, a position size, a portfolio update. Say who did
     what, in which name, and the reason the post gives. A day with several makes a theme of its own.
  2. Broad market analysis and specific plans: the index's or a stock's levels, breadth, rates and oil, the conditions
     a poster watches and what would change the view. Say it as that account's plan, with only the levels it states.
  3. News that moved names, with the analysis posters added: a number, a mechanism, a firsthand fact.
  Group what several accounts said into one sentence rather than one sentence per post.
- `si`: 2 to 8 sentences (both how-tos and news), most important first, written like `alpha` but ranked by how useful they are to someone
  working with agents every day:
  1. A technique, setup or workflow people report working (or failing) with Claude Code, Codex, Grok Bot or Muse:
     prompts, skills, subagents, hooks, context and memory habits, review loops, cost and speed tricks. Say what to do
     differently, in a clause, when the post shows it.
  2. The same for agents in general, when it carries over to those four.
  3. A change to one of those four tools that changes how you would use it.
  4. Other model or tool news only when it is big for everyone, at most two sentences. A launch of a tool the reader does
     not use (another coding app, a new wrapper) belongs here or nowhere.
  Leave `si` empty (`[]`) when the SI posts had nothing beyond headlines; never pad.
- prep.md shows the kind of post each account mostly gives after its handle, as `@handle [type]`. For SI, `howto` is a
  practitioner sharing how they work with agents: lean on those posts for items 1 and 2 above. `ai-news` and
  `ai-research` posts are mostly items 3 and 4. The type says what to expect from the account, not what a post is: judge the post.
  Alpha types (`calls`, `analysis`, `data`, `macro`, `news`) tell you whether a post is a stance, a view, numbers or a headline.
- Each sentence `cites` the 1 to 3 post ids that support it, best first. Under a theme, the page shows the posts its
  sentences cite right below its paragraph, so cite the posts a reader should see for that theme. An `alpha` sentence cites posts listed under
  Alpha in prep.md, an `si` sentence posts listed under SI; the check refuses a sentence that cites the other lens.
- `posts`: the posts a reader should open, best first, every cited post among them: 8 to 15 with `"lens": "alpha"` and, when `si` has sentences, 4 to 10
  with `"lens": "si"` (30 at most). For SI, a post someone could act on today (a how-to, a config, a worked example)
  comes before news. Use the lens prep.md lists the post under. Include every post you cite. For Alpha, a real move or
  a specific plan comes before news. Prefer a post with a number, a mechanism or a firsthand fact over a reaction.
- **Saves are the reader's vote.** Each post shows its saves (🔖) beside its likes. A post saved by a fifth or more of
  the people who liked it is one readers keep to act on; in a check of two days, posts a reader saved for later were saved
  at 2 to 6 times the usual rate, and the editor left three of them out for other posts on the same story. When several
  posts tell the same story, cite and list the one saved most for its likes.

## Rules

- **Numbers come from text.** Cite a post for a number only if its text (or the post it quotes) states it. A chart is
  not a source for a figure: you may list the post and describe the chart in words, but write no number from it. The
  check refuses a number it cannot find in the cited text.
- **Paraphrase.** Never copy 12 or more words in a row from a post; the check refuses it.
- **Say whose claim it is.** "posters argued", "@handle says", not as fact. No buy or sell calls, no price targets that
  a cited post does not give, no holdings or positions of ours.
- **Skip** promotions, giveaways, memes, and posts that only restate a headline without adding anything. For SI, also
  skip model-launch hype with no detail, leaked rumours stated as fact, and "paste this prompt" posts that promise a
  result without showing one.
- **Stance labels are not yours.** They are made later, by post, for US-listed tickers and the market targets only
  (`prompts/stance.md`); an SI post that names no US-listed company gets none. `si` carries no buy or sell language either.
- If the window was quiet, write fewer sentences. Never pad.

Example sentences:

```json
{"theme": "Anthropic's S-1 puts its compute bill in the open",
 "text": "Anthropic's S-1 led the day: posters fixed on its non-cancelable compute commitments with Google, Amazon and Microsoft, and argued over a claimed 900% net revenue retention.",
 "cites": ["2114856726474449176", "2114705241832620399"]}
```

The page also shows, under "More from today", the day's top-ranked posts you did not list (`wire x publish` adds them), so
`posts` need not hold everything worth a look: list the ones your sentences lean on and the best of the rest.

An `si` sentence, in the same form (ids are placeholders, not a real day):

```json
{"text": "Posters disagreed on whether a new coding-agent release is worth switching to: @handle_a reports faster runs on large repositories, while @handle_b says the gain disappears once caching is counted.",
 "cites": ["2100000000000000001", "2100000000000000002"]}
```
