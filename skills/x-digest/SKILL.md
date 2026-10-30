---
name: x-digest
description: Write the private X digest for one scan day - a cited read of what the followed accounts said about the market and tickers, quoting the posts - and keep that day's one report page current with it. For the scanner agent, after every scan it delivers (daily or on demand). The deployment says where the page lives.
---

# X digest (analyst)

The scan collects posts (`skills/x-scan`); the X edition (`skills/x-daily`) is Sigma's public, quote-free write-up. The
digest is a private read of the same scan for the owner, in the posts' own words. One page per day: every scan that day
rewrites it from the whole day's scan, so a day scanned three times still has one page, current with the last scan.

## Input and output

- **Input:** only that day's scan folder (`scan/D/`), `x-accounts.json` and the previous day's digest. No other sources,
  no new X calls, no prices. A post that is not in the scan does not exist for the digest; skip any id in `ids_gone`.
- **Output:** `$SIGMA_X_DIR/digest/D.md` in the private data repo, then the same text on D's report page, wherever the
  deployment asked for it (a page per day under a month page, say). Find the page you made before (remember its link in
  the file's front matter as `page_url`), else one with D's title, and create it only when neither exists; replace its
  content, never append. Post text is quoted here, so the digest never goes in this repo or anywhere public.

## What it says

In this order, about two screens, plain and specific (numbers over adjectives, no padding):

1. **Key insights**: 3 to 5 takeaways, sharpest first, each linked to its posts. The first is the market call.
2. **Market**: the call (bullish, bearish or neutral, with low, medium or high confidence), what changed since the
   previous digest, the bear and bull sides with links, and the levels and events posters say would flip it.
3. **Top tickers**: the 5 most discussed, by how many accounts and how specifically, each with its sentiment, a level
   to watch when a poster states one, and its best two posts; then 5 to 10 more to watch.
4. **Most useful posts**: 8 to 12, real trades and position changes first, then analysis with levels or data, then
   news. Each: handle, link, the post's text quoted as is (cut at about 280 characters), and one line on why it matters.
5. **Coverage**: the window, accounts with no posts, and anything the manifest says was incomplete or failed. An
   incomplete scan says so at the top.

## Rules

- Label every claim **(reported)** (a post says it) or **(inference)** (your read). Nothing is "confirmed": the scan has
  no prices or filings.
- A poster's trade or call is theirs. No buy or sell advice of the digest's own, and nothing about the owner's holdings.
- Link posts as `https://x.com/i/status/<id>`, only ids in the scan, and quote a post only in its own words.
- Re-read before saving: every link is in the scan, every quote matches its post, every claim is labelled.
- Commit only the digest file to the data repo and push; end with your clone clean.
