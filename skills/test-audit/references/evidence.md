# Evidence behind the rules

Each line gives the finding, the source and its date. "One measured suite"
is a production Python suite of about 770 fast tests plus end-to-end
journeys, audited by hand and by agents in October 2026 (not this repository).

## Agent-written tests add cost, not correctness

- Chen, Sun, Shi, Peng, Gu, Lo and Jiang, "Rethinking the Value of
  Agent-Generated Tests for LLM-Based Software Engineering Agents",
  arXiv:2602.07900 (Feb 2026, rev. Apr 2026). On SWE-bench Verified, six
  models wrote tests on 0.6% to 98.6% of tasks with no matching difference in
  resolve rate. Resolved and unresolved tasks had similar test-writing rates.
  Prompting four models toward or away from tests changed resolved tasks by
  0 to −13, none significant, while tokens moved by 20–49%. Agents used print
  statements far more than assertions.
- Konstantinou, Degiovanni and Papadakis, "Can we find bugs using
  LLM-generated oracles?", arXiv:2410.21136 (Oct 2024). Generated tests
  mainly capture what the program currently does, which makes them poor at
  finding bugs. This is why the source of the expected value decides
  admission.

## Most tests never fail; the ones that do sit close to the code

- Memon et al., "Taming Google-Scale Continuous Testing", ICSE-SEIP 2017. Of
  5.5M affected tests, 63K ever failed; 91.3% of test targets passed at least
  once and never failed; 1.23% of test runs found a breakage or a fix.

## Break the code to judge a test, not read it

- Petrović, Ivanković, Fraser and Just, "Practical Mutation Testing at
  Scale", IEEE TSE 2021 (arXiv:2102.11378). At Google, about 82–89% of
  developer feedback on surfaced mutants was "please fix"; one mutant per
  changed line cut the median from 820 mutants per change to 7. The same
  group (ICSE 2021, arXiv:2103.07189) found mutants coupled with real
  high-priority faults.
- Foster, Gulati, Harman et al., "Mutation-Guided LLM-based Test Generation
  at Meta", FSE 2025 (arXiv:2501.12862). Tests generated to kill specific
  mutants were accepted by engineers 73% of the time: aiming a test at a
  named break works.
- One measured suite: reading a test and calling it redundant was right
  about one time in four. Of 14 proposed removals, 3 survived a break check
  per branch; two checker models each called a test covered after the first
  caught break and missed a branch only it proved.
- One measured suite: of 10 claims that an end-to-end journey covered a
  deleted test, 5 held when the guarded line was broken.
- Noemmer and Haas, SWQD 2020: automatic suite minimisation cut size and run
  time by over 70% but lost about 12.5% of fault detection. Coverage alone
  overstates redundancy; hence the break check.

## Deleting by source is wrong; deleting by coverage is right

- One measured suite, three versions of the verdict rules on 60 tests with
  known outcomes: rules that deleted tests for where their expected value
  came from proposed removing more needed tests than rules where coverage of
  a real break decides. Source admits new tests; coverage retires old ones.

## Helper agents: batch size beats model size

- One measured suite: one small-model agent given 60 tests made about one
  tool call per test and found 7 of 24 removable tests; four agents of 15
  made three to six calls per test and found 15–16, matching a larger model.
  Both models still proposed removing 2–3 of 21 needed tests, so a break
  check before landing stays required. Two identical runs differed on about
  4 of 60 tests.
- One measured suite: a second, stronger checker kept 35 of 75 tests the
  first called removable; review then sent back 8 of 39 agreed removals,
  nearly all tests with a recorded catch or the only one passing some flag
  through a live command.

## Flaky tests

- Luo, Hariri, Eloussi and Marinov, "An Empirical Analysis of Flaky Tests",
  FSE 2014: of 161 classified fixes, async wait 45%, concurrency 20%, test
  order 12%, resource leak 7%, network 6%, time 3%; 78% were flaky from the
  day they were written.
- Gruber et al., "An Empirical Study of Flaky Tests in Python", ICST 2021
  (arXiv:2101.09077): of 7,571 flaky tests in PyPI projects, 59% were
  order-dependent.
- Micco, Google Testing Blog, May 2016: about 1.5% of runs flaky; almost 16%
  of tests show some flakiness.
- One measured suite: a release failed on a test that built "end of
  yesterday plus one hour", which is in the future for the first hour of
  each UTC day.
