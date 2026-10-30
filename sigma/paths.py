from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def data_root() -> Path:
    return Path(os.environ.get("SIGMA_DATA_ROOT") or ROOT / "data").expanduser()
