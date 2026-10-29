# Stance labels (reader agents)

For each item you are given, say how bullish or bearish it is on each US-listed stock it is about, and on the market
itself when it takes a view of that. The labels feed the Sentiment page, which adds them up with a weight for recency. A
label is made once and kept, so judge each item on its own text.

You are one reader. Input: `stance/in-N.json`, written by `wire stance-prep`: a list of items. Output:
`stance/out-N.json`, a JSON list with one entry per input item, in the shape of `schema/stance.schema.json`:

```json
[{"key": "c-0123456789ab", "labels": [{"ticker": "XYZ", "stance": 1, "reason": "Calls demand for its product strong this year"}]}]
```

Copy `key` exactly. Save the file, then the coordinator runs `wire stance-merge`; it lists every problem it finds.

## Items

- A **claim** (`kind: claim`) is one sentence a speaker said on a podcast, with the speaker, the show and
  `candidates`: the US tickers the claim was tagged with. Give every candidate a label, with `0` where the claim only
  mentions the company. You may add a US ticker the claim is clearly about and the tags missed. A claim with no
  candidates was sent because its words read like a market view: label it `@MARKET`, `@RATES` or `@CREDIT` if it is one,
  and give `labels: []` if it is not. Market targets are never required.
- An **X post** (`kind: post`) is one post by an account Wire follows, with its `handle` and the post it quotes, if any
  (`quoted`, context only: the author's view is what counts). `candidates` are the US tickers it cashtags or names, a hint
  only. Label the US-listed companies the post is about, named or not, and nothing else; `labels: []` when no US stock is
  its subject. A post that reports a fact or headline with no view ("Brazil's market falls 20%", "MSFT is offering
  buyouts") is stance `0` or no label: news is not a view unless the author frames it as one (calls it good or bad for
  the stock, says what it means for the price). A post of one stock's chart or level without a call is `0`.
  A thread item (an author's own posts in a row, separated by blank lines) is one view: label it once, as a whole.
- An **X sentence** (`kind: x`, older) is one sentence of Wire's daily edition about what several accounts posted. Label
  it like a post.
- An item with `market_only: true` already has its ticker labels, which stay. Give it market labels (below) only, and
  `labels: []` when it is not a market view.

Only a ticker listed on NYSE, Nasdaq, NYSE American or Cboe counts. A private company, a foreign line (a `.KS` or `.T`
symbol), an index, a currency or a commodity gets no ticker label. A broad index fund (SPY, QQQ, IWM, DIA, VOO, VTI,
RSP) is a ticker and is labelled like one.

## Market targets

Besides tickers, an item may take a view of the market itself. Use `@MARKET`, `@RATES` or `@CREDIT` as the `ticker`, with
the same scale and the same reason rule:

| Target | The item is about | `+` means | `-` means |
|---|---|---|---|
| `@MARKET` | US stocks as a whole: the S&P 500, the Nasdaq, "the market", the rally, a bubble, a correction | stocks expected to rise, a constructive read | a sell-off, crash, bubble or downturn expected |
| `@RATES` | interest rates, the Fed, Treasuries, yields, inflation as it bears on rates | rates or yields expected to fall, policy to ease (good for bonds and stocks) | rates or yields expected to rise, policy to tighten, inflation running hot |
| `@CREDIT` | credit spreads, high yield, private credit, defaults, debt markets | credit healthy, spreads tight or tightening | stress, spreads widening, defaults rising |

- A market label is optional. Give one only when the item itself states or implies a view of that target. A claim that
  happens to contain "rates" or "market" (a funding round's valuation, a company's market share, a default setting,
  "rates" of growth) is not a market view: leave it out, and `labels: []` is a complete answer.
- A view of one stock or sector is a ticker label, not a market label. A statement about a group of stocks with no
  single target ("AI stocks are expensive") is a market view only when it is about stocks broadly.
- One item may carry ticker labels and market labels together, and may take a view of more than one target (a hot
  inflation print that raises rate-hike odds is `@RATES -1` and often `@MARKET -1` too, if the item says stocks suffer).
- Do not label a market target twice, and do not repeat the market view as a stock label.

## The scale

The stance is the item's view of the stock as an investment: which way the item says its value goes. It is not the
mood of the news and not your own view of the stock. Use only what the item says.

| | |
|---|---|
| `-2` | Clearly bearish: calls for a short or a sale, says to avoid it, expects the stock or the business to fall or lose |
| `-1` | Leaning bearish: a fact or opinion that is bad for this stock, the direction implied rather than stated |
| `0` | Neutral or a mention: the stock is named, compared or used as an example, and the item takes no side |
| `1` | Leaning bullish: a fact or opinion that is good for this stock, the direction implied rather than stated |
| `2` | Clearly bullish: calls it a long or a buy, a top idea, expects it to rise or win |

- Label every ticker apart. One fact can help one company and hurt another (a shortage helps its seller and hurts its
  buyers); give each its own sign.
- A speaker reporting someone else's view ("analysts see...") labels that view only if the speaker adopts it.
- A level, target or setup with a direction (long above 180, short below support) is `±2`. Pure description of a
  chart or a past move, with no call, is `0`.
- A strong result or a big number with no stated read is `1` at most, `±2` is for a stated call.
- When unsure between two values, choose the one nearer `0`.

## Origin, horizon and target (for every label with a stance other than 0)

The Alpha index (`wire alpha-index`) hands these labels to people and agents, and the private ledger grades them later at
5, 21 and 63 trading days. Add three fields to a label whose stance is not `0`; leave them out of a `0`.

```json
{"ticker": "XYZ", "stance": 1, "reason": "...", "origin": "primary", "horizon_days": 21, "target": "memory chips"}
```

- `origin`: `primary` when the speaker is first-hand: an executive or operator on their own business, a source publishing
  its own numbers (exports, sales, lease or grid data), or someone giving their own view or call. `recap` when the item
  relays a headline, a result someone else reported, or someone else's view. A host reading the news is `recap`; the
  guest who runs the company is `primary`.
- `horizon_days`: `5`, `21` or `63`, the trading days the view is about: `5` a trade or a near event (earnings this week,
  a setup), `21` the next month or two, `63` a quarter or longer. Pick the nearest to what the item implies; when it
  implies nothing, `21`.
- `target`: optional, the company, sector or theme in a few words ("memory chips", "grid equipment"), only when the ticker
  alone would not tell a reader what the view is about (an index fund, a market target, a supplier read).

## The reason

Under 15 words, in your own words, saying what the item says about the stock ("Expects margins to recover next year").
Attribute it to the speaker or account when it is a call; write nothing that reads as our advice to buy or sell. Never
copy 12 or more words in a row from the item.
