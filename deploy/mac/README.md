# Mac setup

The Mac (Apple silicon) does the slow, mechanical part of each run with launchd, and a scheduled agent does the
judgment part an hour later. Weekdays it publishes twice:

| When | launchd job | Then the agent |
|---|---|---|
| Weekdays 07:15 | (none) | `skills/x-daily`: the X edition alone, released and live by 08:00 (intraday) |
| Weekdays 14:30 | `run-daily.sh`: fetch 72 h (Monday 96 h), transcribe (MLX) | 15:30: `prompts/daily.md` (select, report, commit `published/`) and `skills/x-daily`, released together, live by 17:00 (canonical) |
| Sundays 14:30 | `run-weekly.sh`: fetch 7 days (`--refetch`), transcribe everything | 15:30: `prompts/weekly.md` (rank, themes, publish, commit `published/`), released, live by 17:00 |

All times are Pacific. An edition's date is the Pacific day it covers: the 17:00 publish is the canonical one for its
date, and the 08:00 X edition is intraday, replaced when the 17:00 run rebuilds the same date. The scanner delivers
the X scan before each X run (its routine sets when). Each publish is one deploy: two a weekday.

## One-time steps

```bash
# 1. Clone or update
mkdir -p ~/projects && cd ~/projects
# The scripts and plists expect the folder ~/projects/wire (PA_REPO overrides it in the run scripts)
[ -d wire ] || git clone https://github.com/d3ming/wire.git
cd wire && git checkout develop && git pull --ff-only   # daily work is on develop; main is the release branch

# 2. Venv + deps (ffmpeg via Homebrew: brew install ffmpeg). Python 3.10 to 3.14: if `python3` is 3.15+, use
#    /opt/homebrew/bin/python3.14 -m venv .venv (youtube-transcript-api has no 3.15 release)
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e '.[dev,whisper,mac]'
PA_WHISPER_BACKEND=mlx .venv/bin/wire doctor   # whisper line should say: backend mlx

# 3. Install both launchd agents (logs in ~/projects/wire/logs)
bash deploy/mac/install.sh

# 4. The jobs run in the afternoon, when the Mac is in use, so Wire needs no scheduled wake. If an earlier setup
#    scheduled an early-morning wake (check: pmset -g sched), `sudo pmset repeat cancel` removes it; it needs your password

# 5. Test the daily job now
launchctl kickstart -k gui/$(id -u)/com.dming.podcast-alpha
tail -f logs/run-$(date +%F).log            # ends with "done"
```

If the Mac sleeps through 14:30, launchd runs the missed job once on wake. `caffeinate` keeps it awake until
transcribe ends. Both scripts are safe to rerun: fetch is skipped when the run exists and transcribe resumes.

`run-weekly.sh` passes `--refetch` because the weekday runs already marked most of the week's episodes as seen.
transcribe reuses those runs' transcripts, so it only whispers what the weekday runs skipped.

Each agent run ends with `darkroom-commit.sh`: it refreshes the call ledger and the search index and commits `data/` to
darkroom. The site deploys once per publish, two a weekday, through `make release-land` (`site-deploy.sh`; pushes do not
deploy, and it refuses a third deploy in a Pacific day without `--force`, which is for a deploy the owner asked for). The scripts log
their outcome to the event log with `wire event` (`wire/events.py`).

The launchd labels `com.dming.podcast-alpha*` are the maintainer's. Rename them (in the plists, `install.sh` and the
commands here) to your own.

Rollback: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.dming.podcast-alpha.plist` (and `.weekly.plist`).
