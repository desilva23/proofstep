"""CaptainCook4D (Peddi et al., NeurIPS 2024): egocentric cooking videos with step and error labels.

Videos are Apache 2.0 and annotations MIT; everyone filmed gave written consent.
https://github.com/CaptainCook4D
"""

import argparse
import json
import shutil
import subprocess
import urllib.request
from collections import Counter
from pathlib import Path

from .. import config
from ..procedure import Procedure, Step

ANNOTATIONS_REPO = "https://github.com/CaptainCook4D/annotations"
LINKS_URL = "https://raw.githubusercontent.com/CaptainCook4D/downloader/main/metadata/download_links.json"

HOME = config.DATA / "captaincook4d"
ANNOTATIONS = HOME / "annotations"  # a shallow clone of ANNOTATIONS_REPO
TASK_GRAPHS = ANNOTATIONS / "task_graphs"
LINKS = HOME / "download_links.json"
VIDEOS = HOME / "videos"

# Label fixes, each checked frame by frame against the video.
# 8_3: the cinnamon and chocolate labels are swapped. The chocolate chip bag is handled at 146-171 s
# and the ground-cinnamon jar at 172-226 s, the reverse of the annotation (checked Oct 26, 2026).
LABEL_SWAPS = {
    "8_3": [("Add-Add 1/5 teaspoon cinnamon to the mug", "Add-Add 2 pieces of chocolate to the mug")],
}


def recordings() -> dict[str, dict]:
    data = json.loads((ANNOTATIONS / "annotation_json" / "error_annotations.json").read_text())
    return {r["recording_id"]: r for r in data}


def task_graph_names() -> list[str]:
    return sorted(p.stem for p in TASK_GRAPHS.glob("*.json"))


def _step_text(description: str) -> str:
    # "Add-Add 1/5 teaspoon cinnamon to the mug" -> "Add 1/5 teaspoon cinnamon to the mug"
    return description.split("-", 1)[1].strip() if "-" in description else description.strip()


def procedure_from_task_graph(name: str) -> tuple[Procedure, dict[str, str]]:
    """Build a Procedure from a recipe task graph. Returns it with a map from annotation description to step id.

    Steps are numbered in topological order, ties broken by graph node id, so the numbering is stable.
    """
    graph = json.loads((TASK_GRAPHS / f"{name}.json").read_text())
    nodes = {int(k): v for k, v in graph["steps"].items() if v not in ("START", "END")}
    edges = [(a, b) for a, b in graph["edges"] if a in nodes and b in nodes]

    preds = {n: {a for a, b in edges if b == n} for n in nodes}
    ready, order = sorted(n for n in nodes if not preds[n]), []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for nxt in nodes:
            if node in preds[nxt]:
                preds[nxt].discard(node)
                if not preds[nxt]:
                    ready.append(nxt)
        ready.sort()
    if len(order) != len(nodes):
        raise ValueError(f"task graph {name} has a cycle")

    sid = {node: f"S{i}" for i, node in enumerate(order, 1)}
    steps = [Step(id=sid[n], text=_step_text(nodes[n])) for n in order]
    rules = sorted(((sid[a], sid[b]) for a, b in edges), key=lambda r: (int(r[0][1:]), int(r[1][1:])))
    return Procedure(name=name, steps=steps, rules=rules), {nodes[n]: sid[n] for n in order}


def recipe_for(recording: dict) -> str:
    """Find the task graph that shares the most step descriptions with this recording.

    Two of the 384 recordings carry a step label that is not in any graph, so this is a best match.
    """
    wanted = {s["description"] for s in recording["step_annotations"]}
    overlap = {name: len(wanted & set(json.loads((TASK_GRAPHS / f"{name}.json").read_text())["steps"].values()))
               for name in task_graph_names()}
    name = max(overlap, key=overlap.get)
    if overlap[name] * 2 < len(wanted):
        raise LookupError(f"no task graph matches recording {recording['recording_id']}")
    return name


def truth(recording_id: str) -> dict:
    """Human labels for one recording, keyed by step id: happened, start, end, error tags and notes."""
    rec = recordings()[recording_id]
    name = recipe_for(rec)
    _, sid_of = procedure_from_task_graph(name)
    swap = {}
    for a, b in LABEL_SWAPS.get(recording_id, []):
        swap[a], swap[b] = b, a

    steps, unmatched = {}, []
    for ann in rec["step_annotations"]:
        description = swap.get(ann["description"], ann["description"])
        if description not in sid_of:
            unmatched.append(description)
            continue
        errors = ann.get("errors") or []
        happened = ann["start_time"] >= 0
        steps[sid_of[description]] = {
            "happened": happened,
            "start": ann["start_time"] if happened else None,
            "end": ann["end_time"] if happened else None,
            "errors": [e["tag"] for e in errors],
            "notes": [e.get("description", "") for e in errors],
            "label_corrected": description != ann["description"],
        }
    return {"recording_id": recording_id, "recipe": name, "has_errors": rec["is_error"], "steps": steps,
            "unmatched_labels": unmatched}


def video_path(recording_id: str) -> Path:
    return VIDEOS / f"{recording_id}_360p.mp4"


def _download(url: str, dest: Path, timeout: float = 60) -> None:
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "proofstep"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, part.open("wb") as f:
        shutil.copyfileobj(resp, f, 1 << 20)
    part.rename(dest)


def fetch_annotations() -> None:
    # One shallow clone is much faster than fetching the files one by one from raw.githubusercontent.com.
    if not TASK_GRAPHS.exists():
        HOME.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--depth", "1", ANNOTATIONS_REPO, str(ANNOTATIONS)], check=True)
    _download(LINKS_URL, LINKS)


def fetch_video(recording_id: str) -> Path:
    dest = video_path(recording_id)
    if not dest.exists():
        links = json.loads(LINKS.read_text())
        print(f"  downloading {recording_id} (360p)")
        _download(links[recording_id]["gopro_360p"], dest, timeout=300)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description="Download CaptainCook4D labels and videos, and write recipe procedures.")
    ap.add_argument("recordings", nargs="*", help="recording ids to download, e.g. 8_50 8_3")
    ap.add_argument("--list", metavar="RECIPE", help="list the recordings of one recipe with their labelled errors")
    args = ap.parse_args()

    fetch_annotations()
    out = config.ROOT / "procedures"
    out.mkdir(exist_ok=True)
    for name in task_graph_names():
        procedure_from_task_graph(name)[0].save(out / f"{name}.json")
    print(f"{len(task_graph_names())} recipe procedures written to {out}")

    if args.list:
        for rid, rec in sorted(recordings().items(), key=lambda kv: tuple(map(int, kv[0].split("_")))):
            if recipe_for(rec) != args.list:
                continue
            tags = Counter(e["tag"] for s in rec["step_annotations"] for e in s.get("errors") or [])
            summary = ", ".join(f"{t} x{n}" if n > 1 else t for t, n in tags.items()) or "no errors"
            print(f"  {rid:>6}  {summary}")
    for rid in args.recordings:
        fetch_video(rid)
        print(f"  {rid}: {recipe_for(recordings()[rid])}, video at {video_path(rid)}")


if __name__ == "__main__":
    main()
