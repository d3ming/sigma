# Inspect sentiment evidence

Readers sort company views and expand the speakers and source claims behind a company’s aggregate.

## Sub-features

- `sentiment-order`: Most voices, Bullish and Bearish change order.
- `sentiment-evidence`: company disclosure exposes speaker votes and source evidence.
- `sentiment-source`: Source links identify the original claim’s location.

## How to get to it (user POV)

Choose `Sentiment` in main navigation, then a sort button and a company disclosure in `#board`.

## Driving it with Playwright

Preconditions: checked directional views from multiple speakers exist in the isolated data, with independently
worked-out expected votes/order. The default fixture has none; its empty state does not prove vote aggregation.

Use a fresh context at the recorded origin. Click the main-nav `Sentiment` link. Click `Most voices`, `Bullish` and
`Bearish` and compare visible company order with those expected values. Expand `#board > li > details > summary`;
require the speaker’s aggregate vote, original labeled source claims and any opposing evidence, not just an unlabeled
count. Inspect the `Source` link and its source timestamp without contacting outside sites. Capture actions, before/after
order, expanded evidence, screenshots/ARIA and trace under `evidence/sentiment/`; require source files unchanged.

## Gotchas

- `No directional views in this window.` is a valid empty state, not proof of the vote calculations.
- One speaker can contribute repeated or opposing claims; preserve the canonical aggregation rules and do not rescore
  sources to make the expected result pass. Browser ordering alone cannot establish numerical correctness.
