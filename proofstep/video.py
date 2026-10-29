"""ffmpeg helpers: probing videos and making the copies each model needs."""

import json
import os
import subprocess
import threading
from pathlib import Path

from . import config

DERIVED = config.DATA / "derived"


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate,nb_frames:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True).stdout
    info = json.loads(out)
    stream = info["streams"][0]
    num, den = (int(x) for x in stream["avg_frame_rate"].split("/"))
    return {
        "width": stream["width"],
        "height": stream["height"],
        "fps": num / den if den else 0.0,
        "frames": int(stream.get("nb_frames") or 0),
        "duration": float(info["format"]["duration"]),
    }


def _ffmpeg(src: Path, dest: Path, args: list[str]) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Unique per thread: the second look cuts clips in parallel.
        part = dest.with_name(f"{dest.stem}.{os.getpid()}-{threading.get_ident()}.part{dest.suffix}")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *args, str(part)], check=True)
        os.replace(part, dest)
    return dest


def for_spark(src: Path) -> Path:
    """Same video without the audio track: smaller upload, and the procedures are judged on what is seen."""
    return _ffmpeg(src, DERIVED / f"{src.stem}_noaudio.mp4", ["-an", "-c:v", "copy"])


def clip(src: Path, start: float, end: float) -> Path:
    """Cut [start, end] seconds out of src, re-encoded so the cut lands on the exact frame."""
    return _ffmpeg(src, DERIVED / "clips" / f"{src.stem}_{start:.1f}-{end:.1f}.mp4",
                   ["-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-an", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"])


def for_sam(src: Path, fps: int = 2) -> Path:
    """A low-frame-rate copy for SAM, which is billed per frame."""
    return _ffmpeg(src, DERIVED / f"{src.stem}_{fps}fps.mp4",
                   ["-an", "-vf", f"fps={fps}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                    "-pix_fmt", "yuv420p"])
