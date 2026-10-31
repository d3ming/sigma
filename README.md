# Sigma

Sigma finds evidence-backed signals for the US stock market. Its checked podcast and X pipeline publishes cited claims; source-reading skills extend discovery to issuer disclosures, filings, news and public communities. It also publishes research about methods and tooling. Code handles collection, validation and publishing; an agent follows the prompts to score and summarize.

## Run your own

Run `make setup` to install an editable Python environment, transcription tools and Git hooks. On macOS,
install [Homebrew](https://brew.sh) first; elsewhere, install [uv](https://docs.astral.sh/uv/getting-started/installation/)
and `ffmpeg` with your package manager. Setup chooses Python 3.12 and MLX on Apple silicon, or CPU Whisper elsewhere.

For an existing private data directory:

```bash
export SIGMA_DATA_ROOT=/absolute/path/to/private/data
make setup
.venv/bin/python -m sigma.cli doctor
```

Setup updates only the private `operator.json` runtime paths, preserving scanner settings. Keep `SIGMA_DATA_ROOT`
exported when running Sigma. `sh scripts/bootstrap.sh --help` describes installation and configuration behavior.

For a separate empty demo, copy the examples explicitly before setup:

```bash
export SIGMA_DATA_ROOT="$(mktemp -d /tmp/sigma-demo.XXXXXX)"
cp -R examples/data/. "$SIGMA_DATA_ROOT/"
make setup
.venv/bin/python -m sigma.cli site --out /tmp/sigma-site
```

The demo contains no follow list, claims or research posts. Open `/tmp/sigma-site/index.html`; add your own sources
and people before ingesting. Neither setup nor a local build publishes a site or enables scheduled jobs.

`SIGMA_DATA_ROOT` is the only home for operator inputs and output. Keep it outside the checkout, or use the ignored `data/` link. Public code never carries your follows, transcripts, drafts, scores or published content. Site identity belongs in `site.json` there; the checked-in example is generic.

## Operate the desk

Use [signal-discovery](skills/signal-discovery/SKILL.md) for a bounded US-market sweep and [source-reading](skills/source-reading/SKILL.md) to read the underlying evidence across source types. [The source comparison](docs/source-research.md) explains the design choices.

Start with `sigma --help` and `sigma doctor`. For a complete day, use the [daily update skill](skills/daily-update/SKILL.md), which coordinates video ingest, the podcast issue, and the independent X scan. The existing [daily prompt](prompts/daily.md) and [X workflow](skills/x-daily/SKILL.md) remain their task instructions. Every claim needs a source, speaker and timestamp. Fix a failed grounding check before publishing.

Research posts are explicitly allowed in the data root and checked before the site build. A refused post stops the build. Nothing is published just because it exists in the data folder.

The site is built locally from private data and uploaded prebuilt. Push source changes to `develop`, then review a
release PR into `main`. A passing release PR authorizes `make publish`: it checks the frozen build, saves private data
to its repository's `main`, tags the version and uploads. Merging does not deploy. `scripts/release.sh --help` owns the
commands, including a plan-only dry run.

## Contribute

Read [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [REVIEW.md](REVIEW.md). [Architecture](docs/architecture.md) explains the ownership boundaries; [the agent guide](docs/agent-guide.md) explains how to use the evidence.

## License

[MIT](LICENSE). Source material belongs to its creators. Transcripts are never included in this repository or served by the site.
