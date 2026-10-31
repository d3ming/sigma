#!/bin/sh
set -eu
case "${1:-}" in
  --help|-h)
    cat <<'HELP'
Usage: make setup [SIGMA_DATA_ROOT=/path/to/private/data]

Installs Python 3.12, an editable Sigma environment, transcription dependencies,
ffmpeg and Git hooks. macOS requires Homebrew; other systems require uv and ffmpeg.
An existing .venv is reused when its Python is supported.

With SIGMA_DATA_ROOT, require an existing private data directory and update only
operator.json runtime paths. Existing scanner and video settings are retained.
Without it, install tools only; no example data or operator configuration is created.
HELP
    exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1; use --help" >&2; exit 2 ;;
esac
SIGMA=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$SIGMA"
if [ -n "${SIGMA_DATA_ROOT:-}" ] && [ ! -d "$SIGMA_DATA_ROOT" ]; then
  echo "SIGMA_DATA_ROOT must name an existing private data directory: $SIGMA_DATA_ROOT" >&2
  exit 1
fi
if [ "$(uname -s)" = Darwin ]; then
  command -v brew >/dev/null 2>&1 || { echo "Install Homebrew from https://brew.sh, then rerun make setup." >&2; exit 1; }
  command -v uv >/dev/null 2>&1 || brew install uv
  command -v ffmpeg >/dev/null 2>&1 || brew install ffmpeg
else
  command -v uv >/dev/null 2>&1 || { echo "Install uv from https://docs.astral.sh/uv/getting-started/installation/, then rerun make setup." >&2; exit 1; }
  command -v ffmpeg >/dev/null 2>&1 || { echo "Install ffmpeg with your system package manager, then rerun make setup." >&2; exit 1; }
fi
if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
fi
.venv/bin/python -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else "Existing .venv needs Python 3.10-3.14. Save it elsewhere and rerun make setup.")'
EXTRAS=dev,whisper
if [ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ]; then
  EXTRAS=dev,mac
fi
uv pip install --python .venv/bin/python -e ".[${EXTRAS}]"
sh scripts/setup.sh --hooks-only
.venv/bin/python - "$SIGMA" <<'PY'
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

checkout = Path(sys.argv[1]).resolve()
configured = os.environ.get("SIGMA_DATA_ROOT")
if not configured:
    print("Tools ready. Export SIGMA_DATA_ROOT to your private data directory and rerun make setup to bind its runtime.")
    raise SystemExit(0)
root = Path(configured).expanduser().resolve()
if root.is_relative_to(checkout) and root != checkout / "data":
    raise SystemExit("Keep SIGMA_DATA_ROOT outside the source checkout, or use its ignored data/ directory.")
path = root / "operator.json"
config = json.loads(path.read_text()) if path.exists() else {}
if not isinstance(config, dict):
    raise SystemExit("operator.json must contain a JSON object; configuration was left unchanged.")
runtime = {"checkout": str(checkout), "python": sys.executable}
if config.get("runtime") != runtime:
    if path.exists():
        backup = Path(tempfile.mkdtemp(prefix="sigma-setup-", dir="/tmp")) / "operator.json"
        shutil.copy2(path, backup)
        print(f"Previous operator configuration saved to {backup}")
    config["runtime"] = runtime
    path.write_text(json.dumps(config, indent=2) + "\n")
print(f"Runtime bound to {checkout}")
print(f"Private data: {root}")
print(f"Next: SIGMA_DATA_ROOT={shlex.quote(str(root))} {shlex.quote(sys.executable)} -m sigma.cli doctor")
print("Then follow skills/daily-update/SKILL.md for ingestion and edition checks.")
PY
