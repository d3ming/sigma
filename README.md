# Sigma

Sigma finds evidence-backed signals for the US stock market. Its checked podcast and X pipeline publishes cited claims; source-reading skills extend discovery to issuer disclosures, filings, news and public communities. It also publishes research about methods and tooling. Code handles collection, validation and publishing; an agent follows the prompts to score and summarize.

## Run your own

Use Python 3.10–3.14. The checkout supplies schemas, prompts and assets, so install it editable.

```bash
git clone https://github.com/d3ming/sigma
cd sigma
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
export SIGMA_DATA_ROOT="$(mktemp -d)"
cp -R examples/data/. "$SIGMA_DATA_ROOT/"
scripts/setup.sh
.venv/bin/sigma site --out /tmp/sigma-site
.venv/bin/pytest -q
```

This builds an empty desk without network access, private files or model credentials. Open `/tmp/sigma-site/index.html` to inspect it. The examples deliberately contain no follow list, claims or research post. Add your own sources and people before starting ingest. Transcription additionally needs `ffmpeg` and the `whisper` extra; Apple silicon can use `.[dev,whisper,mac]`.

`SIGMA_DATA_ROOT` is the only home for operator inputs and output. Keep it outside the checkout, or use the ignored `data/` link. Public code never carries your follows, transcripts, drafts, scores or published content. Site identity belongs in `site.json` there; the checked-in example is generic.

## Operate the desk

Use [signal-discovery](skills/signal-discovery/SKILL.md) for a bounded US-market sweep and [source-reading](skills/source-reading/SKILL.md) to read the underlying evidence across source types. [The source comparison](docs/source-research.md) explains the design choices.

Start with `sigma --help` and `sigma doctor`. An agent follows [the daily prompt](prompts/daily.md), using the next action returned by `sigma status`; the [X workflow](skills/x-daily/SKILL.md) does the same for X. Every claim needs a source, speaker and timestamp. Fix a failed grounding check before publishing.

Research posts are explicitly allowed in the data root and checked before the site build. A refused post stops the build. Nothing is published just because it exists in the data folder.

The site is built locally from private data and uploaded prebuilt. Source changes reach `main` through a reviewed PR; merging does not deploy. Run `make publish` on `main` to prepare a version-tagged publication for approval. `scripts/release.sh --help` owns the prepare and publish commands. The static preview does not run the search API; hosted search needs its configured index and a linked preflight check.

## Contribute

The initial proposal stays on `seed` for the owner's review into `develop`. Read [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [REVIEW.md](REVIEW.md). [Architecture](docs/architecture.md) explains the ownership boundaries; [the agent guide](docs/agent-guide.md) explains how to use the evidence.

## License

[MIT](LICENSE). Source material belongs to its creators. Transcripts are never included in this repository or served by the site.
