# Mac setup

On macOS, launchd can fetch and transcribe source material before a scheduled agent prepares the daily and weekly
editions. The site is built separately from the configured private data root.

| Cadence | launchd job | Scheduled agent |
|---|---|---|
| X edition, on weekdays | (none) | `skills/x-daily`: prepare the X edition and save private data |
| Daily issue, on weekdays | `run-daily.sh`: fetch 72 h (Monday 96 h), transcribe (MLX) | after the job finishes: `prompts/daily.md` and `skills/x-daily` |
| Weekly digest, once a week | `run-weekly.sh`: fetch 7 days (`--refetch`), transcribe | after the job finishes: `prompts/weekly.md` |

The operator sets every time: the launchd jobs in `StartCalendarInterval` (the shipped plists use 14:30 as an example) and
each agent routine in the scheduler that runs it. Nothing in the code assumes a clock time, except that an edition's
date is the Pacific day it covers. The scanner delivers the X scan before each X run starts, and a run that finds no usable scan stops.

## One-time steps

```bash
# 1. Clone or update
mkdir -p ~/projects && cd ~/projects
[ -d sigma ] || git clone <public-repository-url> sigma
cd sigma

# 2. Venv + deps (ffmpeg via Homebrew: brew install ffmpeg). Python 3.10 to 3.14: if `python3` is 3.15+, use
#    /opt/homebrew/bin/python3.14 -m venv .venv (youtube-transcript-api has no 3.15 release)
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e '.[dev,whisper,mac]'
SIGMA_WHISPER_BACKEND=mlx .venv/bin/sigma doctor

# 3. Install both launchd agents (logs in ~/projects/sigma/logs)
bash deploy/mac/install.sh

# 4. The jobs run in the afternoon, when the Mac is in use, so Sigma needs no scheduled wake. If an earlier setup
#    scheduled an early-morning wake (check: pmset -g sched), `sudo pmset repeat cancel` removes it; it needs your password

# 5. Test the daily job now
launchctl kickstart -k gui/$(id -u)/com.sigma.daily
tail -f logs/run-$(date +%F).log            # ends with "done"
```

If the Mac sleeps through the scheduled time, launchd runs the missed job once on wake. `caffeinate` keeps it awake until
transcribe ends. Both scripts are safe to rerun: fetch is skipped when the run exists and transcribe resumes.

`run-weekly.sh` passes `--refetch` because the weekday runs already marked most of the week's episodes as seen.
transcribe reuses those runs' transcripts, so it only whispers what the weekday runs skipped.

Set `SIGMA_DATA_ROOT` to a private data directory before running the jobs. The example data in `examples/data` can be
copied into a new local `data/` directory by `scripts/setup.sh`. The agent tasks save private changes with
`deploy/mac/data-commit.sh`; that command lands only the configured data directory on private `main`.

Promote source to `main` through a reviewed release PR. A passing release PR authorizes `make publish`; its frozen
build and private-data checks must pass before tagging or upload. Private data lands on its own repository's `main`
without changing the ingest checkout or unrelated dirty folders. A conflict stops publication. The command details
belong to `scripts/release.sh --help`. Keep automatic Git deployments disabled: a cloud build cannot read the private
data root.

A data-only publication can reuse the version tag while `main` is unchanged. A new source version needs a reviewed
version bump. For a local site build without a Vercel account, use `deploy/mac/site-deploy.sh --site-only`.

The launchd labels are `com.sigma.daily` and `com.sigma.weekly`. The scheduled scripts use the repository path passed
to `deploy/mac/install.sh` through `SIGMA_REPO` or their own location.

Rollback: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.sigma.daily.plist` and
`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.sigma.weekly.plist`.
