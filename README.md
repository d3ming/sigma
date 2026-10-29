# Sigma

Sigma turns public podcast and X signals into short, cited claims checked against their sources. Its scope is a Signals desk and public research about methods and tooling.

The initial code import is reviewed in the `seed` → `develop` pull request. It still uses the `wire` package and command. Private follow lists, published output and migration notes are excluded from this repository.

## Run the tools

Requires Python 3.10–3.14. Transcription also needs `ffmpeg` and the optional Whisper dependencies.

```bash
git clone https://github.com/d3ming/sigma
cd sigma
git switch seed
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m wire.cli --help
.venv/bin/pytest -q
```

The tests use synthetic inputs and need no private data. Ingest requires your own sources; the example inputs and complete setup walkthrough are part of the remaining launch work.

## Before the initial review lands

- Remove the SI news lens and add research pages with a publish check.
- Read operator inputs and output through one data root; ship a runnable example set.
- Configure site identity separately from the code.
- Rename the package and CLI to Sigma, and the Alpha index to Signals.
- Build the site locally and deploy it prebuilt, with content-based change checks and matching release verification.

Pushing this repository does not deploy the site. Production cutover is separate from reviewing this import.

## Contributing

Read [AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md) and [REVIEW.md](REVIEW.md). Changes to the initial proposal stay on `seed` until the owner reviews the complete PR into `develop`.

## License

[MIT](LICENSE). Source material belongs to its creators; transcripts and private operator data are not included.
