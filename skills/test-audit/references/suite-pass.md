# Broad pass over a test suite

Run this only when the user has scoped a pass over a whole suite or a large
part of it. The aim is to delete, not to rewrite. Set a cap first (files,
rounds or helper agents) and say what is written down when it is hit. The
numbers behind each step are in [evidence.md](evidence.md).

## 1. Take stock

- One timed run of the suite, saving per-test durations.
- For each test file: its tests, line count, markers, and any stated reason
  it exists. A stated reason or a "caught a bug" counter is a claim to check
  against the test body, not a pass.
- If the repository has static test checks (no assertions, unused fixtures,
  slow tests), run them and use the ranked list as a starting point. Static
  rules find a minority of what a hand pass deletes: the list is a start,
  not the pass.

## 2. Find candidates

Delete a test when it catches nothing cheaper proof misses, or when it:

- asserts that a mock was called, or compares the code with a copy of itself
  kept in the test;
- checks help text, log text or level, column order, output formatting or how
  arguments are passed along;
- repeats a journey or another test at the same boundary (name it); where the
  same refusal is tested at three layers, keep the one at the boundary the
  user meets;
- covers a layout, command, cache or feature that has been removed or paused;
- feeds values the real program never produces, or never calls product code;
- is one of a wall of cases where two (the boundary and the sign) carry the
  risk.

The first three need no break check: delete them in one sweep before any
coverage work.
For this sweep, helper agents can take whole files (about 50 tests each, no
two agents in one file) instead of 15 tests.

Say in one line why each kept test in a long file stays.

Keep, saying so in one line per group: money and other figures people act on,
persisted data and its crash recovery, migrations, permissions and secrets,
publish or deploy decisions, concurrency, and the journeys.
When in real doubt about one of these, keep it and list it as doubtful.

## 3. Prove "another test covers it" by breaking, not reading

Reading a test and judging it redundant is unreliable. Use coverage and
breaks instead:

1. **Unique lines.** Run coverage per test (for example coverage.py with
   `--cov-context=test`, or the runner's per-test coverage) and list, for
   each test, the product lines no other test runs. A test with lines of its
   own stays unless the code has no live caller. A test with none is a
   candidate, not a verdict.
2. **First checker.** Give candidates to helper agents, at most 15 each, with
   the task stated against removal. For each candidate the checker lists every
   assertion and every reachable branch, breaks the product line behind each
   in its own worktree, and runs the suite without the candidate. Covered only
   when every break fails some other test.
3. **Second checker.** A stronger model repeats step 2 for every test the
   first called covered or dead.
4. **Land.** One commit removes what both agree on, naming the surviving test
   for each. If review says a removed test was the only proof of something,
   restore it; do not argue.

Before landing, keep without a break check any test with a recorded real
catch, and any test that is the only one passing some flag or argument value
through a live command: two checkers in agreement still miss these.

A journey "covers" a deleted test only if breaking the line the test guarded
makes the journey fail.

## 4. Clean up and record

- Delete what dies with the tests: fixtures, helpers, constants, data files,
  allowlist entries. Find product code that only the deleted tests called by
  listing unused names before and after; report it to the user rather than
  deleting it, and leave alone anything whose name or file feeds a stored
  identity (a hash, a cache key, a migration).
- Write no new test, except one small one where deleting a large file would
  drop a single real contract.
- Record the decision per file or group, with the surviving proof in its own
  column, wherever the repository keeps such records; git is the archive.

## When to stop

A second round finds little. Expect line count to fall far more than run time, since the
journeys own most of the time and they stay.
