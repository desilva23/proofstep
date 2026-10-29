"""Stage 2: SAM 3.1 looks for physical evidence: when is each named object in someone's hand?

SAM segments one short noun phrase per request across a whole video. Each object Spark named is
segmented once, plus "hand"; a frame counts as "handled" when a confident object box overlaps a
confident hand box. Answers are cached, so re-running with different windows costs nothing.
"""

import re
from pathlib import Path

from . import api, config, video

SAM_FPS = 2
MIN_CONF = 0.5
MIN_OVERLAP = 0.1  # share of the smaller box that must overlap for "in hand"

FRAME = re.compile(r"<(\d+)f>")
BOX = re.compile(r"(\d+)<\|box;([^|]*)\|>")
MASK = re.compile(r"<\|mask;[^|]*\|>")


class TooExpensive(RuntimeError):
    pass


def parse(text: str) -> dict[int, list[tuple[float, float, float, float, float]]]:
    """SAM's wire format -> {frame index: [(x1, y1, x2, y2, confidence), ...]}. Masks are dropped here."""
    text = MASK.sub("", text)  # mask payloads are free-form and could contain something that looks like a frame tag
    frames: dict[int, list] = {}
    parts = FRAME.split(text)
    for i in range(1, len(parts), 2):
        boxes = frames.setdefault(int(parts[i]), [])
        for match in BOX.finditer(parts[i + 1]):
            kv = dict(p.split("=", 1) for p in match.group(2).split(";") if "=" in p)
            boxes.append((float(kv["x1"]), float(kv["y1"]), float(kv["x2"]), float(kv["y2"]), float(kv.get("c", 1.0))))
    return frames


def _overlap(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return w * h / smaller if smaller > 0 else 0.0


def _key(sam_video: Path, concept: str) -> dict:
    return {"stage": "sam", "video": f"{sam_video.name}:{sam_video.stat().st_size}", "concept": concept,
            "model": config.SAM_MODEL}


def segment(sam_video: Path, concept: str, frames: int) -> dict[int, list]:
    def body() -> dict:
        file_id = api.upload(sam_video)
        return {
            "model": config.SAM_MODEL,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": concept},
                {"type": "input_video", "file_id": file_id},
            ]}],
            "metadata": {"include_confidence": "true"},
        }

    text, _ = api.cached_stream(_key(sam_video, concept), body, f"sam {sam_video.stem} '{concept}'",
                                lambda f: frames * api.SAM_USD_PER_FRAME)
    return parse(text)


def is_cached(sam_video: Path, concept: str) -> bool:
    return api.response_cache_path(_key(sam_video, concept)).exists()


def _in_hand(boxes: dict[int, list], hands: dict[int, list]) -> tuple[list[int], list[int]]:
    """Frames where the object is confidently seen, and the subset where it overlaps a hand."""
    seen, handled = [], []
    for idx, found in sorted(boxes.items()):
        confident = [b for b in found if b[4] >= MIN_CONF]
        if not confident:
            continue
        seen.append(idx)
        hand_boxes = [h for h in hands.get(idx, []) if h[4] >= MIN_CONF]
        if any(_overlap(b, h) >= MIN_OVERLAP for b in confident for h in hand_boxes):
            handled.append(idx)
    return seen, handled


def gather(video_path: Path, concepts: list[str], *, max_usd: float = 3.0) -> dict:
    """Segment every concept plus "hand"; return, per concept, the frames it is seen and the frames it is in hand.

    SAM matches plain nouns more reliably than compound names: in testing "measuring spoon", "sugar bag" and
    "milk bottle" found nothing while "spoon" and "mug" did. A name SAM never finds is retried as its last word.
    """
    sam_video = video.for_sam(video_path, SAM_FPS)
    info = video.probe(sam_video)
    frames = info["frames"]
    per_pass = frames * api.SAM_USD_PER_FRAME
    concepts = list(dict.fromkeys(concepts))
    todo = [c for c in ["hand", *concepts] if not is_cached(sam_video, c)]
    budget = max_usd - len(todo) * per_pass
    if budget < 0:
        raise TooExpensive(f"SAM would cost ${len(todo) * per_pass:.2f} for {len(todo)} objects on {video_path.name} "
                           f"(limit ${max_usd:.2f}); raise --max-sam-usd to allow it")
    if todo:
        print(f"SAM looking for {', '.join(repr(c) for c in todo)} in {frames} frames (about ${len(todo) * per_pass:.2f})")

    hands = segment(sam_video, "hand", frames)
    found = {}
    for concept in concepts:
        seen, handled = _in_hand(segment(sam_video, concept, frames), hands)
        found[concept] = {"seen": seen, "handled": handled, "name_used": concept}

    for concept, result in list(found.items()):
        head = concept.split()[-1]
        if result["seen"] or head == concept:
            continue
        if head not in found:
            if not is_cached(sam_video, head):
                if budget < per_pass:
                    print(f"  skipping retry of {concept!r} as {head!r}: over the ${max_usd:.2f} limit")
                    continue
                budget -= per_pass
                print(f"SAM found no {concept!r}; retrying as {head!r}")
            seen, handled = _in_hand(segment(sam_video, head, frames), hands)
            found[head] = {"seen": seen, "handled": handled, "name_used": head}
        if found[head]["seen"]:
            found[concept] = {**found[head], "name_used": head}
    return {"fps": info["fps"] or SAM_FPS, "frames": frames, "objects": found}
