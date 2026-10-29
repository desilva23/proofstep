"""Export chosen reports as a static copy of the viewer, for hosting anywhere (GitHub Pages serves docs/).

    python -m proofstep export 8_3_360p 8_50_360p --out docs

Each run becomes api/run/<name>.json plus a compressed video/<name>.mp4. Local file paths are left out.
A run can be published under another name and title with name=public:title, for example
"salad-test-8b68ff=typed-salad-12_17:12_17 · salad, procedure typed in plain words".
"""

import json
import shutil
import subprocess
from pathlib import Path

from . import serve

FOOTER = """
  <footer class="site-note">
    A published copy of proofstep's results: the reports and the videos they were run on. Nothing here calls
    an API. Videos are from <a href="https://github.com/CaptainCook4D">CaptainCook4D</a> (Peddi et al., NeurIPS 2024,
    Apache 2.0), shrunk for the web. Code, method and full scorecards: <a href="https://github.com/desilva23/proofstep">github.com/desilva23/proofstep</a>.
  </footer>
"""

NOTE_CSS = """
.site-note { max-width: 1500px; margin: 0 auto; padding: 0 24px 32px; color: var(--muted); font-size: 12.5px; }
.site-note a { color: var(--focus); }
"""


def _parse(spec: str) -> tuple[str, str, str | None]:
    name, _, rest = spec.partition("=")
    public, _, title = rest.partition(":")
    return name, public or name, title or None


def export(specs: list[str], out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "api" / "run").mkdir(parents=True)
    (out / "video").mkdir()
    (out / "static").mkdir()

    runs = []
    for spec in specs:
        name, public, title = _parse(spec)
        detail = serve.run_detail(name)
        if detail is None:
            raise SystemExit(f"no saved report called {name}")
        report = detail["report"]
        src = Path(report["video"])
        report["video"] = f"{public}.mp4"
        detail["name"] = public
        (out / "api" / "run" / f"{public}.json").write_text(json.dumps(detail))
        # Smaller than the working copy, and with the index first so playback starts before the download ends.
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf", "scale=-2:360",
                        "-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(out / "video" / f"{public}.mp4")], check=True)
        runs.append({"name": public, "title": title, "procedure": report["procedure"], "counts": report["counts"],
                     "recording": serve._recording_id(name)})
        size = (out / "video" / f"{public}.mp4").stat().st_size / 1e6
        print(f"  {public}: report and {size:.1f} MB video")
    (out / "api" / "runs.json").write_text(json.dumps(runs))

    for f in ("app.js", "style.css"):
        shutil.copy(serve.WEB / f, out / "static" / f)
    with (out / "static" / "style.css").open("a") as f:
        f.write(NOTE_CSS)
    page = (serve.WEB / "index.html").read_text()
    page = page.replace('<script src="static/app.js"></script>',
                        '<script>window.PROOFSTEP_STATIC = true;</script>\n  <script src="static/app.js"></script>')
    page = page.replace("</main>", "</main>\n" + FOOTER)
    (out / "index.html").write_text(page)
    (out / ".nojekyll").write_text("")  # serve files as they are
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    print(f"Wrote {out} ({total:.1f} MB)")
