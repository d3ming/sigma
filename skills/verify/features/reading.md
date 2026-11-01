# Read an episode

Readers expand an episode’s key insights on the homepage and open a separate chronological narrative.

## Sub-features

- `reading-expand`: collapsed episode reveals insights without a full narrative in the feed.
- `reading-detail`: the episode page shows insights and chronological sections.
- `reading-direct`: a direct episode URL opens the same full reading.

## How to get to it (user POV)

- Open Podcasts & video at `/`, then the episode’s disclosure button.
- Choose `Open the episode page` from the expanded card.
- Open `/episodes/yt_abcdefghijk.html` directly in the fixture.

## Driving it with the Sigma verification driver

Preconditions: launch and doctor passed; `Verification agents` is in the current publication window.

- Run `"$SIGMA_PYTHON" "$DRIVER" drive --work "$VERIFY_WORK" --feature reading`.
- The driver clicks the button named `Toggle details for Verification agents` within `#top li.entry`.
  Require `aria-expanded=true`, visible `.key-insights` and no `.dense-summary` in that card.
- Follow the contained `Open the episode page` link, waiting for navigation. Require one insight and two
  `.dense-summary > section` elements. The timestamps and section order must preserve the seeded source clock.
- Repeat through the direct episode address. Retain expanded/detail screenshots, ARIA, action JSON and trace
  for both viewport widths; require no JavaScript error, horizontal overflow or data mutation.

## Gotchas

- Clicking the title navigates; it does not expand the card. The disclosure fetches a fragment asynchronously.
- Home date windows and lens settings persist in localStorage; use fresh contexts and an appropriate window.
- Wait for navigation and the target selector before counting sections; querying the outgoing page can falsely fail.
- A transcript button links an externally public transcript. Local source text does not imply that button exists.
