# Read X evidence

Readers move between dated X editions and open the posts cited by a theme.

## Sub-features

- `x-editions`: Today, This week and Archive reach their corresponding views.
- `x-citation`: choosing a citation opens its post disclosure.
- `x-read`: marking a theme read persists in that browser context.

## How to get to it (user POV)

Choose `X` in main navigation, then `Today`, `This week` or `Archive`; choose a theme citation or `Show N posts`.

## Driving it with Playwright

Preconditions: a checked dated X edition with matching citation/post IDs exists in the isolated data.
The default fixture lacks it; stop and report the missing precondition instead of passing an empty view.

Use a new Playwright context at the driver’s recorded origin. Click the main-nav link named `X`, then each edition
link. Choose a cite by accessible name `Post N by @handle`; require its enclosing `details` to be open and its source
URL to match the cited post. Open `Show N posts` directly too. Click `Mark read: <theme>` using the actual theme text,
reload and require retained read state in that context. Record the actions, IDs/URLs, DOM state, screenshots/ARIA and
trace under `evidence/x/`. Verify no data files changed; the read marker belongs to browser storage.

## Gotchas

- The driver blocks external requests; third-party X embed rendering is unproved offline even when citations work.
- A scanner acknowledgement or private PR is not a checked edition. Do not dispatch a scan to fill this fixture.
- Use actual edition text to resolve accessible names; `N`, handle and theme here describe source-dependent values.
