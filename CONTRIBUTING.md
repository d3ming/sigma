# Contributing

Issues and pull requests are welcome. Follow the [Code of Conduct](CODE_OF_CONDUCT.md). The owner reviews the initial `seed` proposal into `develop` before it lands.

## Set up

```bash
python3 -m venv .venv                      # python3.14 -m venv .venv if `python3` is 3.15 or newer
.venv/bin/pip install -e '.[dev,whisper]'     # on Apple silicon: '.[dev,whisper,mac]'
.venv/bin/pytest -q
```

The suite runs in a few seconds with no network access. A change is ready when it passes and you have shown the
changed behavior working: a test where one earns its place (below), otherwise the command you ran and what it printed,
in the commit message.

## Ground rules

- **Code stays deterministic.** No LLM calls and no paid APIs. Judgment belongs in `prompts/`, and every output an
  agent writes gets a schema in `schema/` and a check in code.
- **Tests stay offline and isolated.** Use fixtures and fakes for network calls. `conftest.py` keeps tests out of
  `data/` and `published/`; do not work around it.
- **A test must earn its place.** Default to no new test. First extend an existing test at the same boundary; if
  running the command once shows the change works, put that in the commit message instead. Write a new test only when
  a wrong result would be seen by a reader or a caller (a wrong claim or link on the site, a lost or corrupted
  manifest, a broken command, a leaked private item) and nothing else would catch it. Its expected value must come
  from outside the code: a bug you reproduced, a figure worked out by hand, a stated rule (a rerun changes nothing),
  or reviewed command output. Say which in its name or docstring.
- **Banned tests.** Tests of help text, log text or wording nothing parses; tests that only check a mock was called;
  tests that copy the code's logic or constants as the expected value; `is not None`-only or "did not raise"-only
  assertions; a wall of near-identical cases where the boundary and the sign carry the risk; a second test of the
  same outcome at the same boundary. Delete one when you find it, in the same commit.
- **Nothing private in the repo.** No transcripts, holdings, tokens, Notion page ids, personal paths, or copied
  newsletter text. Real-world test fixtures are synthetic or rephrased.
- **Code is the documentation.** Say what a command or flag does in its `--help`, and why in the commit message; code carries no comments.
  Docs hold only what code cannot: [AGENTS.md](AGENTS.md) for a rule the operator would otherwise get wrong,
  [docs/architecture.md](docs/architecture.md) when a part is added or moves.

## Proposing a change

Send the initial launch changes to `seed` for the complete review into `develop`. Keep source lists and editorial output in your configured data root; suggest generic examples instead of submitting a real follow list. Never commit `data/`, `runs/`, publication output, transcripts, `.env` content or local reference copies.

Run `scripts/setup.sh` once to install the local hooks. Before pushing, run `scripts/check.sh` and exercise the affected command with real or clearly identified example inputs. Record the command, output and limits in the commit body. A passing offline suite does not prove a live deployment.

## Commit messages

Write the subject as an imperative sentence about the change's effect, under about 72 characters, with no trailing
period. Use the body to say why and what changed in behavior, wrapped at 72 characters. Name what you verified.

```text
Match Apple episodes by guid before title

A loose title match attached Thursday's TBPN episode to Friday's and
Part 2 of an interview to Part 1. Match the feed guid or enclosure
first; fall back to a 0.9 title ratio with equal numbers and the
closest release date. No match now means no link.

Tests: 257 passed; new cases for both wrong matches.
```

Good subjects: `Cache feeds with conditional GET`, `Match Apple episodes by guid before title`. Avoid `fix stuff`,
`updates`, or a list of file names. Data commits from the operator (`Publish daily report 2026-10-24`) need no body.
