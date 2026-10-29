"""Local viewer for proofstep reports: python -m proofstep serve, then open http://localhost:8765.

Serves the saved reports in runs/, their videos (with byte ranges, so the browser can seek), SAM's boxes
around the evidence object, and the human labels when the video is a CaptainCook4D recording.

Browsing reads saved results only. Two actions call the API, each only when asked: turning typed
instructions into a procedure (a fraction of a cent), and checking an uploaded video against one (shown
with a cost estimate first, run as a background job with a spending cap).
"""

import json
import mimetypes
import re
import subprocess
import sys
import threading
import time
import uuid
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import api, author, config, evidence, video
from .procedure import Procedure

WEB = Path(__file__).resolve().parent / "web"
UPLOADS = config.DATA / "uploads"
PROCEDURES = config.ROOT / "procedures"
BOX_PAD = 3.0  # seconds of boxes to send either side of the evidence stretch
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm"}
MAX_UPLOAD = 2 << 30
MAX_MINUTES = 20

JOBS: dict[str, dict] = {}


def _report_path(name: str) -> Path | None:
    if not NAME.match(name) or name.endswith(("_first_look", "_no_search")):
        return None
    path = config.RUNS / f"{name}.json"
    return path if path.exists() else None


def list_runs() -> list[dict]:
    runs = []
    for path in sorted(config.RUNS.glob("*.json")):
        if path.stem.endswith(("_first_look", "_no_search")):
            continue
        report = json.loads(path.read_text())
        runs.append({"name": path.stem, "procedure": report["procedure"], "counts": report["counts"],
                     "recording": _recording_id(path.stem)})
    return runs


def _recording_id(name: str) -> str | None:
    from .datasets import captaincook4d as cc4d
    rid = name.removesuffix("_360p")
    try:
        return rid if rid in cc4d.recordings() else None
    except FileNotFoundError:
        return None


@lru_cache(maxsize=64)
def _boxes(video_path: str, concept: str) -> dict[int, list]:
    """SAM's saved boxes for one object, or nothing if that object was never segmented."""
    sam_video = video.for_sam(Path(video_path), evidence.SAM_FPS)
    cached = api.response_cache_path(evidence._key(sam_video, concept))
    return evidence.parse(json.loads(cached.read_text())["text"]) if cached.exists() else {}


def run_detail(name: str) -> dict | None:
    path = _report_path(name)
    if path is None:
        return None
    report = json.loads(path.read_text())
    src = Path(report["video"])
    info = video.probe(video.for_sam(src, evidence.SAM_FPS))
    fps, width, height = info["fps"] or evidence.SAM_FPS, info["width"], info["height"]

    boxes = {}
    for step in report["steps"]:
        ev = step.get("evidence")
        if not ev:
            continue
        found = _boxes(str(src), ev["found_as"])
        lo, hi = ev["from"] - BOX_PAD, ev["to"] + BOX_PAD
        frames = []
        for idx, items in sorted(found.items()):
            t = idx / fps
            if lo <= t <= hi:
                for x1, y1, x2, y2, c in items:
                    if c >= evidence.MIN_CONF:
                        frames.append([round(t, 2), x1 / width, y1 / height, x2 / width, y2 / height, round(c, 2)])
        boxes[step["id"]] = {"object": ev["found_as"], "boxes": frames}

    truth = None
    rid = _recording_id(name)
    if rid:
        from .datasets import captaincook4d as cc4d
        t = cc4d.truth(rid)
        truth = {sid: {k: s[k] for k in ("happened", "start", "end", "errors")} for sid, s in t["steps"].items()}
    return {"name": name, "report": report, "boxes": boxes, "box_interval": 1 / fps, "truth": truth}


def list_procedures() -> list[dict]:
    out = []
    for path in sorted(PROCEDURES.glob("*.json"), key=lambda p: -p.stat().st_mtime):
        try:
            proc = Procedure.load(path)
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
        out.append({"file": path.stem, "name": proc.name, "steps": len(proc.steps)})
    return out


def estimate(procedure: Procedure, seconds: float) -> dict:
    """Rough cost of a check. SAM dominates: one pass over a 2 fps copy per object name, plus hands.

    Calibrated on a 9-step check of a 4-minute video: 15 SAM passes (about 1.3 names per step, hands, and
    a few retries under simpler names), $1.50 in all.
    """
    frames = seconds * evidence.SAM_FPS
    likely = (1.3 * len(procedure.steps) + 3) * frames * api.SAM_USD_PER_FRAME
    most = (2 * len(procedure.steps) + 4) * frames * api.SAM_USD_PER_FRAME
    return {"likely_usd": round(likely + 0.05, 2), "cap_usd": round(max(most, 1.0), 2)}


def save_upload(name: str, stream, length: int) -> dict:
    suffix = Path(name).suffix.lower()
    if suffix not in VIDEO_TYPES:
        raise ValueError(f"only {', '.join(sorted(VIDEO_TYPES))} videos are accepted")
    if not 0 < length <= MAX_UPLOAD:
        raise ValueError("the video is empty or larger than 2 GB")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    stem = f"{author.slug(Path(name).stem)[:40]}-{uuid.uuid4().hex[:6]}"
    raw = UPLOADS / f"{stem}.original{suffix}"
    with raw.open("wb") as f:
        remaining = length
        while remaining:
            chunk = stream.read(min(1 << 20, remaining))
            if not chunk:
                break
            f.write(chunk)
            remaining -= len(chunk)
    # A small copy like the dataset's: 360p, no audio. Keeps uploads, SAM frames and costs down.
    small = UPLOADS / f"{stem}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-an", "-vf", "scale=-2:360",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", str(small)], check=True)
    raw.unlink()
    seconds = video.probe(small)["duration"]
    if seconds > MAX_MINUTES * 60:
        small.unlink()
        raise ValueError(f"videos up to {MAX_MINUTES} minutes only")
    return {"video": stem, "seconds": round(seconds, 1)}


def start_check(procedure_file: str, video_stem: str, cap_usd: float) -> str:
    proc_path, video_path = PROCEDURES / f"{procedure_file}.json", UPLOADS / f"{video_stem}.mp4"
    if not (NAME.match(procedure_file) and NAME.match(video_stem) and proc_path.exists() and video_path.exists()):
        raise ValueError("unknown procedure or video")
    job = uuid.uuid4().hex[:10]
    log = config.RUNS / "logs" / f"{video_stem}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    JOBS[job] = {"status": "running", "run": video_stem, "log": str(log), "started": time.time()}

    def work():
        with log.open("w") as f:
            done = subprocess.run([sys.executable, "-u", "-m", "proofstep", "check", str(proc_path), str(video_path),
                                   "--max-sam-usd", f"{cap_usd:.2f}"], stdout=f, stderr=subprocess.STDOUT, cwd=config.ROOT)
        JOBS[job]["status"] = "done" if done.returncode == 0 and _report_path(video_stem) else "failed"

    threading.Thread(target=work, daemon=True).start()
    return job


def job_status(job: str) -> dict | None:
    info = JOBS.get(job)
    if not info:
        return None
    lines = Path(info["log"]).read_text().splitlines() if Path(info["log"]).exists() else []
    progress = [l.strip() for l in lines if l.strip() and not l.startswith(" ")]
    return {"status": info["status"], "run": info["run"], "elapsed": round(time.time() - info["started"]),
            "progress": progress[-1] if progress else "Starting",
            "error": lines[-1].strip() if info["status"] == "failed" and lines else None}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, content_type: str | None = None):
        size = path.stat().st_size
        start, end = 0, size - 1
        ranged = self.headers.get("Range")
        if ranged and (m := re.match(r"bytes=(\d*)-(\d*)$", ranged.strip())):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            elif m.group(2):
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
        self.send_response(206 if ranged else 200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if ranged:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return  # the browser stops reading when it seeks
                remaining -= len(chunk)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self._file(WEB / "index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            target = (WEB / path.removeprefix("/static/")).resolve()
            if target.is_relative_to(WEB) and target.is_file():
                return self._file(target)
        if path == "/api/runs":
            return self._json(list_runs())
        if path == "/api/procedures":
            return self._json(list_procedures())
        if path.startswith("/api/procedure/"):
            name = path.removeprefix("/api/procedure/")
            target = PROCEDURES / f"{name}.json"
            if NAME.match(name) and target.exists():
                return self._json(json.loads(target.read_text()))
        if path.startswith("/api/job/"):
            info = job_status(path.removeprefix("/api/job/"))
            return self._json(info) if info else self._json({"error": "no such job"}, 404)
        if path.startswith("/api/run/"):
            detail = run_detail(path.removeprefix("/api/run/"))
            return self._json(detail) if detail else self._json({"error": "no such run"}, 404)
        if path.startswith("/video/"):
            report = _report_path(path.removeprefix("/video/"))
            if report:
                src = Path(json.loads(report.read_text())["video"])
                if src.exists():
                    return self._file(src, "video/mp4")
        self._json({"error": "not found"}, 404)

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 100_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        url = urlparse(self.path)
        path = unquote(url.path)
        try:
            if path == "/api/procedure":
                procedure = author.write(self._body_json().get("text", ""))
                name = author.slug(procedure.name)
                procedure.save(PROCEDURES / f"{name}.json")
                return self._json({"file": name, "procedure": json.loads((PROCEDURES / f"{name}.json").read_text())})
            if path == "/api/upload":
                filename = unquote(url.query.removeprefix("name=")) or "video.mp4"
                return self._json(save_upload(filename, self.rfile, int(self.headers.get("Content-Length") or 0)))
            if path == "/api/estimate":
                body = self._body_json()
                procedure = Procedure.load(PROCEDURES / f"{body['procedure']}.json")
                seconds = video.probe(UPLOADS / f"{body['video']}.mp4")["duration"]
                return self._json(estimate(procedure, seconds))
            if path == "/api/check":
                body = self._body_json()
                procedure = Procedure.load(PROCEDURES / f"{body['procedure']}.json")
                seconds = video.probe(UPLOADS / f"{body['video']}.mp4")["duration"]
                cap = estimate(procedure, seconds)["cap_usd"]
                return self._json({"job": start_check(body["procedure"], body["video"], cap), "cap_usd": cap})
        except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError, subprocess.CalledProcessError) as e:
            return self._json({"error": str(e) or e.__class__.__name__}, 400)
        except api.ApiError as e:
            return self._json({"error": str(e)}, 502)
        except SystemExit as e:  # no API key
            return self._json({"error": str(e)}, 400)
        self._json({"error": "not found"}, 404)


def serve(port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"proofstep viewer at http://localhost:{port} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
