# Mac setup

On macOS, launchd can fetch and transcribe source material before a scheduled agent prepares the daily and weekly
editions. The site is built separately from the configured private data root.

| When | launchd job | Scheduled agent |
|---|---|---|
| Weekdays 07:15 | (none) | `skills/x-daily`: prepare the X edition and save private data |
| Weekdays 14:30 | `run-daily.sh`: fetch 72 h (Monday 96 h), transcribe (MLX) | 15:30: `prompts/daily.md` and `skills/x-daily` |
| Sundays 14:30 | `run-weekly.sh`: fetch 7 days (`--refetch`), transcribe | 15:30: `prompts/weekly.md` |

Times are Pacific. An edition's date is the Pacific day it covers. The scanner delivers the X scan before each X run.

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

If the Mac sleeps through 14:30, launchd runs the missed job once on wake. `caffeinate` keeps it awake until
transcribe ends. Both scripts are safe to rerun: fetch is skipped when the run exists and transcribe resumes.

`run-weekly.sh` passes `--refetch` because the weekday runs already marked most of the week's episodes as seen.
transcribe reuses those runs' transcripts, so it only whispers what the weekday runs skipped.

Set `SIGMA_DATA_ROOT` to a private data directory before running the jobs. The example data in `examples/data` can be
copied into a new local `data/` directory by `scripts/setup.sh`. The agent tasks save private changes with
`deploy/mac/data-commit.sh`; that command stages only the configured data directory inside its Git repository.

For a data-only site update, first save the private data, then run `make publish` from the production `main` checkout.
`make publish DRY_RUN=1` runs the Vercel production build and quota check without upload, and needs the clone linked to its
Vercel project. `deploy/mac/site-deploy.sh --site-only` builds the site without Vercel or an account. No source-release
PR is needed for a data-only update. Source changes use the owner-reviewed release PR flow and `make release-land`.

The launchd labels are `com.sigma.daily` and `com.sigma.weekly`. The scheduled scripts use the repository path passed
to `deploy/mac/install.sh` through `SIGMA_REPO` or their own location.

Rollback: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.sigma.daily.plist` and
`launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.sigma.weekly.plist`.
