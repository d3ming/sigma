# Operators: the publisher and contributors

The owner's Sigma instance is run by more than one agent environment. Each environment is an operator, and every
operator works in one of two modes. The mode, not the machine, decides what an operator may do. Operators share code
and data only through git; they never share a working tree.

| | Publisher | Contributor |
|---|---|---|
| Who | Exactly one operator; today the owner's Mac agents | Any number; today cloud agents |
| Code | Pushes to `develop` (AGENTS.md) | A branch and a pull request into `develop` |
| Private data | Lands on the data repo's `main` with [`deploy/mac/data-commit.sh`](../deploy/mac/README.md) or `make publish` | A fresh branch and a pull request against the data repo's configured branch; never a direct push |
| Jobs | Owns every job not handed to a contributor: the daily and weekly editions, [x-daily](../skills/x-daily/SKILL.md), `make publish`, scheduling | Only the jobs it is handed: a one-off [ingest request](../skills/ingest-request/SKILL.md), the [X scan](../skills/x-scan/SKILL.md) when it is the configured scanner, code changes, reviews |
| `operator.json` | Its settings are the committed copy | Keeps its own settings in its clone; never commits the file |
| Typical `video.backend` / `x.reader` | `mlx` / `bird` | `faster-whisper` / `official` |

## Rules for every operator

- **Separate clones.** Clone Sigma and the private data repo yourself. Never commit from, or write into, another
  operator's working tree.
- **Bind locally.** After cloning, run `SIGMA_DATA_ROOT=/path/to/data make setup`. It rewrites only the `runtime`
  paths in `operator.json` and keeps scanner, video and X settings. Set `video.backend` and `x.reader` for this
  machine in the same file.
- **One writer per job.** A job has one operator at a time. The publisher owns it unless the owner hands it to a named
  contributor, as `daily_update.scanner` does for the X scan. Never run a job another operator owns; propose a pull
  request or review instead.

## Rules for contributors

- **Stage only what your job names.** Commit the exact paths your skill delivers (for example `scan/D/` and
  `heartbeat/scan.json`); never `git add -A` in the data repo. This keeps your `operator.json` out of every commit.
- **Deliver by pull request.** Code goes to a pull request into `develop`; data goes to a pull request against the
  data repo's configured branch. Do not merge your own pull request; the publisher accepts it (for a scan, through
  daily-update's **Accept the scan PR**) or the owner merges it.
- **No publisher commands.** Never run `make publish`, `deploy/mac/*`, or a daily or weekly edition.

## X reader

`x.reader` in `operator.json` picks how this operator reads X. There is one reader per operator and no fallback
between them: when the configured reader fails, follow the failing skill's recovery steps, not the other reader.

- **Absent, null or `bird`:** the Bird CLI, read-only, signed in through the operator's browser.
- **`official`:** the agent platform's official X tools, read-only. One call at a time, about 10 seconds apart;
  wait 3 minutes after a rate-limit (429) response. A 429 you waited out is not a failed call. Request full long-post
  text (`note_tweet`) and articles, view attached images and charts, and page the author's thread and self-replies.
  Never guess cut-off text, scrape X in a browser or reuse browser cookies.
- **Any other value:** a configuration error. Stop and report it; do not pick a reader.

Either reader produces the same files: the scan format in [skills/x-scan](../skills/x-scan/SKILL.md) and the notes
in [skills/ingest-request](../skills/ingest-request/SKILL.md). The reader is transport; the files are the product.
