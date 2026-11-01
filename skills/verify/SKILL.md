---
name: verify
description: Drive Sigma’s web UI and one-off ingestion CLI to verify user-visible behavior, capture browser evidence, and diagnose regressions before reporting a feature complete. Use for interaction checks, not editorial quality review or permission to publish.
---

# Verify Sigma

Read [the feature map](features/README.md), then the relevant journey. Use the real site builder and browser;
`python -m sigma.cli verify` checks HTTP and text only. The default fixture is fictional, not publishable research.
Do not use a passing fixture journey as evidence about production data, transcription quality, or deployments.

## Launch

Run from the source checkout with its installed Python. For a fresh checkout, `make setup` installs Sigma;
add the optional browser tooling with `uv pip install --python .venv/bin/python -e '.[verify]'`.
For an existing operator runtime, keep its editable checkout binding: install `playwright>=1.49` into that Python
without reinstalling Sigma. Set `SIGMA_PYTHON` to that executable. The driver uses installed Chrome on macOS,
`SIGMA_VERIFY_BROWSER` when supplied, or Playwright Chromium (`"$SIGMA_PYTHON" -m playwright install chromium`).
A browser download is setup, not verification evidence.

```sh
export SIGMA_PYTHON="${SIGMA_PYTHON:-$PWD/.venv/bin/python}"
VERIFY_WORK=$(mktemp -d /tmp/sigma-verify.XXXXXX)
DRIVER="$PWD/.agents/skills/verify/scripts/control.py"
"$SIGMA_PYTHON" "$DRIVER" launch --work "$VERIFY_WORK"
```

Launch requires an empty scratch directory. It seeds one current, scored, picked episode with an insight and two
chronological sections; runs the normal checked `sigma publish` export and `sigma site` build; then starts a
loopback static server on an unused port. Printed instance JSON means the seeded episode and homepage are usable.
Helper subprocesses replace inherited `SIGMA_` overrides with scratch-only settings. All data, SQLite, output and logs stay under `VERIFY_WORK`. No operator configuration, scanner, media fetch or Vercel
command is used. The static server mirrors clean HTML paths but does not run the serverless search API.

The usual `make preview` owns a shared `.preview/dist`; a different port does not isolate that output. Do not use
it for concurrent verification. Each driver launch has independent data, output, port and fresh browser contexts.
Do not attach this helper to an existing preview, signed-in browser or production instance.

## Doctor

```sh
"$SIGMA_PYTHON" "$DRIVER" doctor --work "$VERIFY_WORK"
```

This read-only check requires the recorded checkout/revision, the owned server’s PID/token response headers,
Sigma’s fixture identity and the actual seeded episode in `/episodes.json`. Run it before driving and whenever
anything looks wrong. A listening port alone is not readiness. Relaunch in a new scratch directory after changing
the source revision. Uncommitted changes require a rebuild too; record `git diff` alongside the proof.

## Drive

```sh
"$SIGMA_PYTHON" "$DRIVER" drive --work "$VERIFY_WORK" --feature reading
"$SIGMA_PYTHON" "$DRIVER" drive --work "$VERIFY_WORK" --feature picks
```

Both commands drive the generated app in fresh desktop and mobile browser contexts. Reading expands insights,
follows the episode link and checks the separate chronological narrative, including direct episode entry. Picks
uses the homepage chip, Find controls, an empty search, the result link and the episode badge. Use the map for the
exact selectors and for CLI, X and Sentiment paths. Missing fixture prerequisites are a failed or unexercised journey,
not permission to weaken its assertions. Browser requests outside the owned origin are blocked; external media and
X embeds require a separately authorized real-source check.

## Evidence

Each drive saves action/result JSON, screenshots, an ARIA snapshot and a Playwright trace under
`$VERIFY_WORK/evidence/`. Build/export commands retain argv, stdout, stderr and exit status. The browser proof hashes
the complete scratch data directory before and after driving; a read-only journey must leave it unchanged.
Record the checkout revision and working diff, feature, entry points and viewport with the result. A screenshot alone
is insufficient: inspect the trace/action log and resulting JSON or files. Failures retain partial actions and traces;
never label a skipped route as covered by another entry point. No mocks replace product code; only fictional inputs
and blocked external requests isolate production boundaries. Cleanup must run after failed iterations as well.

The fixture export writes a scratch publication and library; it is not a deploy dry run. Inspect the recorded commands
and scratch files rather than assuming “verification” means no side effects. No ingestion, scanner or publishing
side effect outside this scratch instance is authorized by this skill.

## Cleanup

```sh
"$SIGMA_PYTHON" "$DRIVER" cleanup --work "$VERIFY_WORK"
test -s "$VERIFY_WORK/evidence/cleanup.json"
ls "$VERIFY_WORK/evidence"
```

Cleanup verifies the instance before signalling only its recorded PID, then checks that its server no longer answers.
It refuses an unverified live PID. Confirm the JSON, screenshots and traces for the feature actually driven still exist. It preserves scratch state and evidence for inspection and the normal temporary-file
retention job; do not remove or move them. If launch fails before an instance exists, no server was started. If a live
instance becomes unidentifiable, report its recorded PID/URL and the ownership failure instead of killing by name.

## Helpers

The executable [control.py](scripts/control.py) owns launch, doctor, drive and cleanup. Every invocation is shown above;
`--help` lists its arguments. Use `/maintain-verification-skill` when app routes, controls or behavior change so this map
and its driver stay aligned. This skill does not install a recurring maintenance schedule.
