"""Local viewer for proofstep reports: python -m proofstep serve, then open http://localhost:8765.

Serves the saved reports in runs/, their videos (with byte ranges, so the browser can seek), SAM's boxes
around the evidence object, and the human labels when the video is a CaptainCook4D recording. It reads
only saved results and never calls the API.
"""

import json
import mimetypes
import re
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import api, config, evidence, video

WEB = Path(__file__).resolve().parent / "web"
BOX_PAD = 3.0  # seconds of boxes to send either side of the evidence stretch
NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _report_path(name: str) -> Path | None:
    if not NAME.match(name) or name.endswith("_first_look"):
        return None
    path = config.RUNS / f"{name}.json"
    return path if path.exists() else None


def list_runs() -> list[dict]:
    runs = []
    for path in sorted(config.RUNS.glob("*.json")):
        if path.stem.endswith("_first_look"):
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


def serve(port: int = 8765) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"proofstep viewer at http://localhost:{port} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
