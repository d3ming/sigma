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
