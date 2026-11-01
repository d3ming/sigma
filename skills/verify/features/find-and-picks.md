# Find episodes and user picks

Readers intersect search and filters, then open an episode. A user pick is provenance, separate from its rating.

## Sub-features

- `picks-home`: the configured homepage chip opens the picks filter.
- `find-query`: matching and empty queries update results without changing stored data.
- `picks-direct`: direct Find supports selecting Picks.
- `picks-detail`: a detail-page pick badge returns to filtered Find.
- `topic-detail`: a detail-page topic chip opens Find for that episode topic.

## How to get to it (user POV)

- Choose the configured picks chip beside Podcasts & video on `/`.
- Open `/find/` directly; there is no Find link in the main navigation.
- Choose the picks badge on an episode page.

## Driving it with the Sigma verification driver

Preconditions: launch and doctor passed; the fixture’s label is `User picks` and it contains one picked episode.

- Run `"$SIGMA_PYTHON" "$DRIVER" drive --work "$VERIFY_WORK" --feature picks`.
- Choose `User picks` in `.top-head`. Require `/find/?picks=1`, select `Picks` value `1`, and `#f-count` of `1 episode`.
- Select `Topic=verification` (label `Verification`) and search `interface`: require one result even though that
  word appears only in the detailed editorial. This proves episode tagging and summary retrieval.
- Fill `Search titles, guests and summaries` with `no-such-verification-episode`: require zero results. Replace it
  with `Verification`: require one result. Open its title in `#f-out h3` and require the full reading.
- Choose the detail’s `Verification` topic chip; require Find’s Topic value `verification` and one result.
  Reopen the episode, choose its `User picks` badge and check the filter again. Open `/find/` directly and select `Picks=1`.
- Save every entry point’s actions, resulting count and URL, browser evidence and the unchanged-data result.

## Gotchas

- Filters intersect; a date, rating, show or lens restriction can hide a real pick. Inspect every active control.
- Wait for `/find-index.json` and `#f-count`; a blank list during loading is not an empty result.
- The default fixture has no below-floor pick. It cannot prove that a low-rated pick remains discoverable while
  staying off the default homepage. Supply a grounded low-rated fixture before claiming that coverage.
