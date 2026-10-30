---
name: test-audit
description: "Decide whether a test earns its cost: before writing any new test, when adding, changing or reviewing tests, at the end of a coding session that touched code, and for an explicitly scoped cleanup of a test suite. Any language or framework. Not for diagnosing why a test fails today."
---

# Test audit

A test earns its cost when it is what fails on a real break that someone
would notice: a wrong number, lost data, a broken command or API, a leaked
secret. The rest of a suite is maintenance, run time and false confidence.
This skill decides which tests to write, which to keep and which to delete.

## First: the repository's and the user's own rules

Read the repository's testing policy before deciding anything: `AGENTS.md`,
`CONTRIBUTING.md`, `REVIEW.md`, and the commands the gate runs (`scripts/check.sh`).
Note which tests are end-to-end runs of the real program (journeys). Where the repository conflicts with this skill, it wins; say so.

An explicit instruction from the user also wins ("write tests for the
parser", "do this test-first", "delete this test"). Follow it, still name each
new test's source, and say which tests you would have skipped or which
deletions a break check did not support.

## Where the expected value comes from

A test checks the code against an expected value. If that value came from the
same reading of the task that produced the code, the test only shows that two
copies of one reading agree, and it passes just as well when both are wrong.
An agent that writes code and then its tests does exactly this. So a new test
is admitted only when its expected value has an outside source, named in the
test's name or a one-line docstring:

- **failure-seen**: the bug was reproduced before the fix, or an incident, a
  red gate or a review finding was turned into a failing case. Strongest.
- **outside-value**: a figure from a spec, a standard, a published document or
  a person, or arithmetic done by hand from the definition with the working
  shown. A value copied from what the new code printed is not outside.
- **stated-rule**: a rule a person or written standard states, checked on what
  the program did (a dry run writes nothing; a second run changes nothing; a
  refused request leaves the store as it was). A property-based test is this
  kind: name the invariant it checks.
- **command-output**: what the installed program does, seen through its output
  or the files it leaves. A snapshot of a shipped output counts once a person
  has reviewed it; an unreviewed snapshot restates the code.

Not sources: the implementation's branches walked one by one, a constant or
message repeated from the code, a mock told what to return, a second copy of
the logic kept in the test.

**Tests do not come first.** Unless the repository or the user requires
test-first work, do not write a test before the code or to steer a design:
written first, its expected value is still the author's reading of the task.
What must come before a fix is the failure itself, seen by running the real
program.

## Before writing a test

The default for a change is no new test. Stop at the first step that holds:

1. An existing test or journey already fails on the wrong outcome: write
   nothing.
2. A kept test at the right boundary can take one more input or assertion:
   extend it.
3. Running the changed program once shows the outcome: run it, and put the
   command and what it printed in the commit message or report. That is the
   proof for this change.
4. The wrong outcome is consequential, nothing above catches it, and the
   expected value has a source from the list: write one test, at the cheapest
   boundary that still runs the real code path. If the repository has no test
   runner, do not add one unasked; use step 3 and say the gap exists.

A regression that reached the main branch and showed up in real use always
gets one test. Check it out at the commit before the fix, run the test there,
and see it fail for the reason the incident did. It may be written after the
fix.

## Writing one that earns it

- Call the code as its users do and assert the result they see. It must fail
  if every function it imports returned nothing or a wrong value: no
  `toBeDefined`, `is not None`, "did not throw" or call-count-only checks.
  For a mock, assert the payload it received. A property test asserts its
  invariant over generated inputs instead of one literal.
- Prefer one realistic success path with assertions on output or saved state.
  Add a negative case only for a distinct harm: wrong money, exposed private
  data, an unauthorized write, lost recovery, a broken contract another
  program reads. Assert the protected outcome, not the error text.
- In a table of cases, the risk usually sits in two: the boundary and the
  sign. Keep those.
- Deterministic and offline. The big causes of flaky tests are, in order,
  async waits, concurrency and order dependence: wait for an event with a
  deadline, never a fixed sleep; share no state with other tests; keep
  background processes (file watchers, git maintenance) away from anything
  the test compares. Time is rarer but easy to miss: a test passing at 3 pm
  must pass at 00:05 UTC, on a Sunday, at a month or year end and in any time
  zone, so pass time in or set the program's clock, and never mix local and
  UTC dates.
- A unit test takes about a second or less; a slower one shrinks its input to
  the fewest rows that still cross the boundary, or lowers the threshold that
  forces the size. End-to-end and browser tests have no such budget.

## Verdict on an existing test

For a test that exists, the question is not where its value came from but
whether deleting it loses the only thing that fails on a real break. Answer
from the test body and the code it calls, quoting the deciding line. Take the
questions in order; the first that gives a verdict ends it.

1. **Does it run code the product runs?** It calls only test helpers, or a
   function nothing calls that is also not exported or documented as public
   API: `DELETE`. Cite the search that showed no caller.
2. **Does anything live depend on what it protects?** Live: a shipped
   feature, a public API, a command people or agents run, a scheduled job, a
   published output. Name it. A removed or paused feature, or an experiment:
   `DELETE`, citing where it was removed or paused. Could not trace it either
   way: `DOUBT`.
3. **What would break it?** Name one change to one product line that makes
   it fail and that a user, a caller or a stored value would see. If only
   wording, log text, formatting nothing parses, argument order or private
   names would: `DELETE`. Output another program or a published artifact
   parses is a contract, not formatting.
4. **Does another test fail on that same change?** Check the journeys first,
   then the same file. Name the test and the assertion. If one does:
   `DELETE`, or `MERGE` when this test carries an input or assertion the
   other lacks. "Probably covered" with no test named is not an answer.
5. **Where does its expected value come from?** A source from the list, or
   `restates-code` or `mock`. Those two give `WEAK`: it is the only thing that
   fails on a real break, so it stays, listed as proof to improve. Never
   delete a test for its source alone.
6. Otherwise `KEEP`.

A `DELETE` from questions 1 to 3 that rests on reading alone, with no search
or record to cite, is `DOUBT`. So is any `DELETE` or `MERGE` resting on a
guess at question 3 or 4 when the test guards money or other figures people
act on, persisted data and its recovery, migrations, permissions, secrets, a
publish or deploy decision, or concurrency. `DOUBT` stays and is listed.

One line per test, nothing else:

```text
<file>::<test> | KEEP|DELETE|MERGE|WEAK|DOUBT | q=<deciding question> | reader=<live dependant or none> | breaks_on=<file:line and the change, or none> | covered_by=<test or none> | source=<answer 5 or n/a> | <reason, under 20 words>
```

## A verdict is a proposal: break before you delete

Judging redundancy by reading is wrong more often than right (see
[references/evidence.md](references/evidence.md)). Before a `DELETE` or
`MERGE` from question 4 lands:

1. List each distinct assertion the test makes and each branch or argument
   value a live caller can reach in the code it calls.
2. For each, make the `breaks_on` change in a scratch copy or worktree, run
   the narrowest set of tests that includes `covered_by` (without the
   candidate), and restore the line. Never commit a break.
3. The test goes only if some other test fails on every break. Some caught
   and some not means it stays.

A mutation-testing tool (mutmut, Stryker, PIT, cargo-mutants, go-mutesting)
does step 2 at scale; use it when the repository has one. Set a cap before a
large round of breaks (candidates, or minutes of run time) and report what is
left when it is hit.

Keep without a break check any test with a recorded catch of a real defect,
and any test that is the only one passing some flag or argument value through
a live command.

## Modes

- **Session end (default when no scope is given).** Review the code and tests
  changed since the session's starting commit; if that is unknown, use the
  merge base with the default branch, and say which. Name the plausible wrong
  result of each change and how a user would see it, then decide retain,
  improve, consolidate or delete for the related tests, and look for
  consequential changes with no proof at all. Delete only in test files the
  session already changed; list other candidates for the user. A no-op is a
  valid result. Run the narrow tests, then the repository's gate.
- **A named area.** The same steps, starting from the code the user named.
- **A broad pass over the suite.** Only when the user scopes one. Follow
  [references/suite-pass.md](references/suite-pass.md).

Delete in the same change what dies with the tests: fixtures, helpers, data
files and allowlist entries nothing else uses. Product code that only deleted
tests called is a finding for the user, not a silent deletion.

## Helper agents

Where the harness and the repository allow helpers, give one agent at most 15
tests and state its task against the easy answer ("prove this test is
needed"). A small model does break checks well in batches that size; have a
stronger model re-check every test the first called removable before anything
is deleted.

## Report

Scope and base commit; tests added, kept, improved and deleted, with the
surviving proof named for each deletion; the commands run and what they
printed; any consequential gap left open. Do not claim a clean suite from a
scoped audit.
