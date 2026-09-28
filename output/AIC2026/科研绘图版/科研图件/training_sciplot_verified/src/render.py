from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMAND = [
    sys.executable,
    'C:\\Users\\Administrator\\.codex\\skills\\sciplot-figure-skill\\scripts\\render_visualspec_matplotlib.py',
    "--spec", str(ROOT / "visualspec.json"),
    "--out-dir", str(ROOT / "output"),
    "--formats", 'png,svg,pdf',
    "--basename", "figure",
    *([] if True else ["--no-support-files"]),
]

if __name__ == "__main__":
    raise SystemExit(subprocess.call(COMMAND))
