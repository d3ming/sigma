# AGENTS.md

Sigma finds evidence-backed signals for the US stock market and publishes research on methods and tooling. A stranger can clone it,
supply their own follow lists, and run the pipeline and the site. The owner's instance runs on a Mac with private inputs.

Push changes directly to `develop`. Source reaches `main` through a reviewed `develop`→`main` PR. A passing release
PR authorizes publication, including new public pages, without another owner approval. Use `make publish`; it validates
the frozen build, saves private data
to its own repository’s `main`, then tags and uploads. Merging alone does not deploy. Keep automatic Git deployments
disabled. Private migration notes never enter this repository or its history.

This file holds only what a capable agent would get wrong here without being told. The code and each command's
`--help` own the rest.

## Tenets

- **An ungrounded claim stops the work.** Every published signal carries a speaker, a timestamp and a link, and code
  checks it against the source. Never publish around a failed check, and never fill in a missing value.
- **One owner per fact and per decision.** Change the owner and update its callers; never add a second path, alias or
  fallback beside it. Redirects exist only where outsiders hold old links.
- **Nothing private in the repo, ever.** Follow lists, published output, post drafts, scores, notes and the call ledger
  live in a separate private data repo and reach the code through `data/` or a setting. Holdings never enter any repo.
  Anything committed may be read by anyone.
- **Sigma knows nothing of the fund.** Research posts are about method and tooling, never about investments, fair
  values or calls.
- **Evidence is not permission.** Prepare the full proposal yourself; the owner authorizes what is his (below).

## What needs the owner's go

Bring a reviewed dry run, and wait for an explicit yes, for:

- changing the repo's visibility;
- deleting data that has no saved copy;
- a force-push or history rewrite outside `develop`;
- a credential, permission, domain or hosting-account change;
- anything sent or posted as the owner.

Everything else is yours to decide. Be bold with reversible work.

## Working here

- Work in a worktree, never in the primary checkout.
- Commit subjects are [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/), 72 characters at most.
- Err toward a body. The subject says what changed; the body says why, what you chose over what, and how you proved it.
- Never name the owner or anyone behind the project in files or commit messages: write "the owner" or "the
  maintainer". `.private-words.sha256` (committed) holds salted hashes of the words the commit hooks and CI refuse;
  `scripts/private_words.py --add` adds one from stdin, so a word never lands in a file. A missing list fails. An optional
  git-ignored `.private-words` adds plain words on one machine. Run `git config core.hooksPath .githooks` once per clone.
- Early history, before this guard, names the owner's domains and handle. The owner accepted it as it stands: no history
  rewrite, no force-push. Keep current files clean; do not copy old strings forward from history.
- Commits use the GitHub no-reply address, which is set in this repo's config. Check it with `git config user.email`
  before your first commit. Create commits locally when an API cannot set that identity explicitly.
- Use `--force-with-lease` for rewrites on `develop`; preserve other contributors' work.
- **Prove a change by using it.** Run the command a person or a routine would run, on real inputs, and put the command
  and what it printed in the commit message. A passing test suite is not proof that a tool works.
- Use at most one helper agent, unless the owner has asked you to coordinate others.

## Tests

- **No test-driven development.** Do not write a test before the code it tests, and do not write tests to steer a
  design.
- A change needs no new test. A test is admitted only when its expected value comes from outside the code: a failure
  seen in real use, a value worked out by hand, a rule the owner stated, or what an installed command does. The full
  rules are in [CONTRIBUTING.md](CONTRIBUTING.md) and the banned list is there too.
- Tests stay offline and build throwaway roots; they never read `data/` or real published output.

## Leaving a trail

- **Write no comments.** Why code is the way it is belongs in the commit message, where `git blame` and `git log -L`
  find it. The one exception is a line an agent would otherwise "fix" wrongly: one line, no measurements.
- Updating a document means cutting what code, config or `--help` already says, never adding the current state.
- A removed feature gets an entry in `docs/REMOVED_FEATURES.md`: what it did, why it went, and where its last copy
  lives.
- An accepted limitation is a `Known limit:` paragraph in the body of the commit that accepts it.
- Reviewing a change: [REVIEW.md](REVIEW.md).

For broader source discovery and reading, use `skills/signal-discovery` and `skills/source-reading`. Their private leads do not bypass the podcast and X publication checks.
