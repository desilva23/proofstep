"""Frame sheets for checking CaptainCook4D labels by eye.

    python -m proofstep.datasets.label_sheets 8_3 12_43

<id>_steps.jpg has one row per labelled step in time order, four frames spread across its labelled window.
<id>_overview.jpg has one frame every 10 seconds; it is made for recordings with skipped steps, to check
those steps really don't happen. ffmpeg here can't draw text, so the row legend is printed instead.
"""

import math
import subprocess
import sys
import tempfile
from pathlib import Path

from . import captaincook4d as cc4d
from .. import config
from ..decide import clock
from ..procedure import Procedure

SHEETS = cc4d.HOME / "sheets"
WIDTH = 320
OVERVIEW_EVERY = 10
OVERVIEW_COLS = 8


def _tile(inputs: list[str], tile: str, dest: Path) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-vf", f"{tile}", "-frames:v", "1", str(dest)], check=True)


def step_sheet(recording_id: str) -> list[str]:
    truth = cc4d.truth(recording_id)
    procedure = Procedure.load(config.ROOT / "procedures" / f"{truth['recipe']}.json")
    video = cc4d.video_path(recording_id)
    done = sorted((s["start"], s["end"], sid) for sid, s in truth["steps"].items() if s["happened"])
    SHEETS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        times = [a + (b - a) * f for a, b, _ in done for f in (0.15, 0.38, 0.62, 0.85)]
        for i, t in enumerate(times):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                            "-vf", f"scale={WIDTH}:-2", f"{tmp}/{i:04d}.jpg"], check=True)
        _tile(["-framerate", "1", "-i", f"{tmp}/%04d.jpg"], f"tile=4x{len(done)}:padding=4:color=white",
              SHEETS / f"{recording_id}_steps.jpg")

    legend = [f"{recording_id} ({truth['recipe']}): {SHEETS / f'{recording_id}_steps.jpg'}"]
    for row, (a, b, sid) in enumerate(done, 1):
        s = truth["steps"][sid]
        notes = f"  [{', '.join(s['errors'])}]" if s["errors"] else ""
        fixed = "  (label corrected)" if s["label_corrected"] else ""
        legend.append(f"  row {row}: {sid} {clock(a)}-{clock(b)} {procedure.step(sid).text}{notes}{fixed}")
    skipped = [sid for sid, s in truth["steps"].items() if not s["happened"]]
    for sid in skipped:
        legend.append(f"  skipped: {sid} {procedure.step(sid).text}")
    if skipped:
        duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                         "csv=p=0", str(video)], capture_output=True, text=True).stdout)
        rows = math.ceil(duration / OVERVIEW_EVERY / OVERVIEW_COLS)
        _tile(["-i", str(video)], f"fps=1/{OVERVIEW_EVERY},scale={WIDTH}:-2,tile={OVERVIEW_COLS}x{rows}:padding=4:color=white",
              SHEETS / f"{recording_id}_overview.jpg")
        legend.append(f"  overview: {SHEETS / f'{recording_id}_overview.jpg'}, one frame every {OVERVIEW_EVERY} s, "
                      f"{OVERVIEW_COLS} per row (row r, column c is at {OVERVIEW_EVERY * OVERVIEW_COLS}(r-1) + {OVERVIEW_EVERY}(c-1) s)")
    return legend


if __name__ == "__main__":
    for rid in sys.argv[1:]:
        print("\n".join(step_sheet(rid)))
