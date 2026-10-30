# Removed features

## CLAUDE.md instruction pointer

`CLAUDE.md` imported `AGENTS.md` for Claude. The owner retired this indirection
because Claude supports `AGENTS.md` directly. `AGENTS.md` remains the instruction
file. The last copy is at `088bffc:CLAUDE.md`.

## Tests of the operator's private files

The imported suite validated the operator's live follow lists and published
output. Those files are excluded from Sigma, so these checks do not belong in
its offline suite. Watchlist and creator validation now use synthetic inputs;
the index check builds a throwaway day file. The duplicate-claims command and
its existing synthetic directory test remain. The last original tests are in
the private seed archive at `9ccc50f:tests/`.

## Private migration documents

`PLAN.md` and `docs/migration/` held the private migration handoff and operating
manual. They are excluded from the public history. The originals remain in the
private seed archive at `9ccc50f`; the active plan stays local and ignored.

## Newsletter benchmark

The TMTB email parser measured podcast selection against a particular newsletter and searched for missed episodes. It is outside the public Signals desk's scope. Its command, fetch option, recall statistics and dedicated fixtures were removed together. The last public copy is `68f6d6c:wire/tmtb.py`; a local reference is retained under `.local/deletion-candidates/`. Existing private benchmark records are preserved.

## SI news lens

The SI lens published a second feed of AI news and how-tos. Sigma instead focuses its signal pipeline on Signals; methods and tooling belong in explicitly allowed research posts. The last public implementation is the initial import at `68f6d6c`. Historical operator output is not deleted.

## Legacy command and configuration names

The package and command named `wire`, the `podcast-alpha` alias, the `WIRE_*` and `PA_*` settings, and the Alpha index were replaced by `sigma`, `SIGMA_*` and Signals. Keeping aliases would create competing configuration paths. Old public `/alpha` page links redirect to `/signals`; there are no old CLI or environment aliases. The last implementation is `68f6d6c`.

## Merge-and-deploy release commands

`make release` and `make release-land` prepared a release PR and deployed while moving `main`. Source review and publication now have separate approval boundaries: a normal PR promotes source, and `make publish` prepares the immutable version tag and frozen publication plan. Direct unapproved uploads are refused. The last merge-and-deploy implementation is `641fec3:scripts/release.sh`.

## Separate podcast and YouTube feeds

The home page listed podcast picks while `/social/` listed YouTube creator videos. Both now share one feed ordered by original publication time, with X separate. Source detail pages, search and Signals data remain available; `/social/` redirects to the combined feed for existing links. The last separate implementation is `4f377a0:sigma/site.py`.

## Hosted transcript search

Find's hosted transcript search returned short excerpts and timestamp links from a private search index. It added a serverless function and a separate Blob upload flow. It was removed as unnecessary; the local library continues to ingest and search transcripts. The last public copies are `9fc0a80:api/search.py` and `9fc0a80:sigma/searchindex.py`.

## Secondary navigation menu

The header menu listed Tags, Themes, Shows, Find, daily Signals and Research beside Sentiment. It obscured the main
reading paths and advertised sparse browsing views. The header now links directly to Podcasts & video, X and
Sentiment. Existing detail pages and data exports remain available through source links and old URLs. The last menu
implementation is at `51bc256:sigma/site.py`.

## Weighted sentiment Net and separate X column

The Sentiment board summed quality- and age-weighted claims, ignored mild X views, and showed a separate daily X
label beside that total. Repeated claims could outweigh independent speakers and the two readings could disagree.
Sentiment now uses the same per-speaker voting rule for video and X, with a five-point stance or Mixed and source
evidence, over the past 30 days. Stored labels and video ratings are unchanged. The former model is at
`51bc256:sigma/board.py` and its display is at `51bc256:sigma/site.py`.
