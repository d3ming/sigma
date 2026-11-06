# Operators: one codebase, more than one machine

Sigma can be run by more than one operator environment at once, for example the owner's Mac agents and a cloud
agent computer. Each environment is an operator. They share code and data only through git; they never share a
working tree.

| | Mac operator | Cloud operator |
|---|---|---|
| Checkout and data | Clones on the Mac; `runtime` paths point there | Its own clones; `runtime` paths point there |
| `video.backend` | `mlx` | `faster-whisper` |
| `x.reader` | `bird` (browser session) | `official` (official X tools) |
| Scheduling and publish | `launchd` and [deploy/mac](../deploy/mac/README.md) | None; proposes pull requests |

## Rules

- **Separate clones.** Each operator clones Sigma and the private data repo itself. Never commit from, or write
  into, another operator's working tree.
- **Bind locally.** After cloning, run `SIGMA_DATA_ROOT=/path/to/data make setup`. It rewrites only the private
  `operator.json` `runtime` paths and keeps scanner, video and X settings. Set `video.backend` and `x.reader` for
  this machine in the same file.
- **Never commit machine settings.** `runtime`, `video` and `x` in `operator.json` describe one machine. Leave them
  out of every commit to the shared data repo; the shared copy keeps the settings of the operator that owns
  publishing.
- **Deliver through pull requests.** Code changes go to a branch and a pull request into `develop`. Data (scans,
  digests, ingest notes) goes to a fresh branch in the data repo and a pull request against its configured branch,
  never a direct push to that branch.
- **One writer per workflow.** Each scheduled job, publish and data path has one owning operator at a time. The other
  operator may propose pull requests and review, but does not run the same job beside it.

## X reader

`x.reader` in `operator.json` picks how this operator reads X. There is one reader per operator and no fallback
between them: when the configured reader fails, follow the failing skill's recovery steps, not the other reader.

- **Absent, null or `bird`:** the Bird CLI, read-only, signed in through the operator's browser. This is the
  existing Mac path and is unchanged.
- **`official`:** the official X tools of the agent platform, read-only. One call at a time, about 10 seconds apart;
  wait 3 minutes after a rate-limit (429) response. Request full long-post text (`note_tweet`) and articles, view
  attached images and charts, and page the author's thread and self-replies. Never guess cut-off text, scrape X in a
  browser or reuse browser cookies.

Either reader produces the same files: the scan format in [skills/x-scan](../skills/x-scan/SKILL.md) and the notes
in [skills/ingest-request](../skills/ingest-request/SKILL.md). The reader is transport; the files are the product.
