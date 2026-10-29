"""Stage 3: plain rules combine Spark's claims with SAM's evidence. No model is involved here.

  Spark: done,     SAM: object (by its own name) in hand near then -> verified
  Spark: not done, SAM: never in hand (unexplained)    -> missing
  anything else, including the two disagreeing         -> can't verify, with the moment to look at

Order is only judged between verified steps.
"""

from collections import Counter

from .procedure import Procedure

PAD = 45.0          # Spark's start times were off by 14 s typically and up to 50 s in testing
MIN_HANDLED = 2.0   # seconds of "in hand" that count as evidence

VERIFIED, MISSING, CANT_VERIFY = "verified", "missing", "cant_verify"
NOTHING = {"seen": [], "handled": []}


def clock(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _runs(frames: list[int], fps: float, max_gap: int = 2) -> list[tuple[float, float, int]]:
    """Group frame indices into continuous stretches: (start s, end s, frame count)."""
    runs: list[list[int]] = []
    for i in sorted(frames):
        if runs and i - runs[-1][1] <= max_gap:
            runs[-1][1], runs[-1][2] = i, runs[-1][2] + 1
        else:
            runs.append([i, i, 1])
    return [(a / fps, b / fps, n) for a, b, n in runs]


def _same_thing(a: str, b: str) -> bool:
    """"spoon" and "measuring spoon" are the same thing to SAM; "sugar bag" and "chocolate bag" are not."""
    return f" {a} " in f" {b} " or f" {b} " in f" {a} "


def _best(frames_by_object: dict[str, list[int]], fps: float,
          claimed: tuple[float, float] | None = None) -> tuple[str, float, float] | None:
    """If total in-hand time reaches MIN_HANDLED, pick the stretch to show as evidence.

    With a claimed time, that is the stretch closest to it (ignoring single-frame blips when possible);
    without one, the longest stretch.
    """
    if sum(len(f) for f in frames_by_object.values()) / fps < MIN_HANDLED:
        return None
    runs = [(obj, a, b, n) for obj, frames in frames_by_object.items() for a, b, n in _runs(frames, fps)]
    if claimed is None:
        obj, a, b, _ = max(runs, key=lambda r: r[3])
    else:
        start, end = claimed
        runs = [r for r in runs if r[3] > 1] or runs
        obj, a, b, _ = min(runs, key=lambda r: (max(start - r[2], r[1] - end, 0), -r[3]))
    return obj, a, b


def decide(procedure: Procedure, spark: dict, sam: dict) -> dict:
    fps, duration = sam["fps"], spark["duration"]
    claims = spark["steps"]
    timed = {sid: (c["start"], c["end"]) for sid, c in claims.items()
             if c["status"] == "done" and c["start"] is not None and c["end"] is not None}

    # An object named for several steps (the mug a drink is made in) proves little about any one of them.
    named = Counter(o for c in claims.values() for o in c["objects"])
    common = {o for o, n in named.items() if n >= 3}

    def evidence_objects(sid: str) -> list[str]:
        objects = claims[sid]["objects"]
        return [o for o in objects if o not in common] or objects

    def used_name(obj: str) -> str:
        return sam["objects"].get(obj, {}).get("name_used", obj)

    def label(obj: str) -> str:
        return obj if used_name(obj) == obj else f"{obj} (found as '{used_name(obj)}')"

    def claimed_by_others(sid: str, obj: str, pad: float) -> list[tuple[float, float]]:
        """Time windows of other steps Spark placed in time that use the same object."""
        return [(timed[o][0] - pad, timed[o][1] + pad) for o in timed if o != sid and any(
            _same_thing(used_name(obj), used_name(x)) for x in evidence_objects(o))]

    def outside(frames: list[int], windows: list[tuple[float, float]]) -> list[int]:
        return [i for i in frames if not any(a <= i / fps <= b for a, b in windows)]

    steps = []
    for step in procedure.steps:
        claim = claims[step.id]
        objects = evidence_objects(step.id)
        names = " / ".join(objects) or "its objects"
        evidence = {o: sam["objects"].get(o, NOTHING) for o in objects}
        seen_anywhere = any(e["seen"] for e in evidence.values())

        at = None  # when a verified step happened, for the order check
        sightings = []  # every unexplained in-hand stretch, for the second look to check one by one
        if step.id in timed:
            start, end = timed[step.id]
            lo, hi = start - PAD, end + PAD
            near = {o: outside([i for i in e["handled"] if lo <= i / fps <= hi], claimed_by_others(step.id, o, 0))
                    for o, e in evidence.items()}
            # Only a match under the object's own name proves the step. A match found by retrying with the last
            # word ("box" for "salt box") is too generic: in testing it "confirmed" salt when it was pepper.
            best = _best({o: f for o, f in near.items() if used_name(o) == o}, fps, claimed=(start, end))
            weak = None if best else _best(near, fps, claimed=(start, end))
            if best:
                obj, a, b = best
                status, look_at, at = VERIFIED, a, start
                reason = f"Spark saw it at {clock(start)}-{clock(end)}; SAM saw the {label(obj)} in hand at {clock(a)}-{clock(b)}."
            elif weak:
                best = weak  # recorded as evidence for the second look to check
                obj, a, b = weak
                status, look_at = CANT_VERIFY, a
                reason = (f"Spark says done at {clock(start)}. SAM couldn't find the {obj} by name; its closest match, "
                          f"a '{used_name(obj)}' in hand at {clock(a)}-{clock(b)}, is too generic to count on its own.")
            elif seen_anywhere:
                status, look_at = CANT_VERIFY, start
                reason = f"Spark says done at {clock(start)}, but SAM never saw the {names} in hand near then."
            else:
                status, look_at = CANT_VERIFY, start
                reason = f"Spark says done at {clock(start)}, but SAM could not find the {names} anywhere in the video."
        else:
            # Handling of an object near another timed step that uses the same object belongs to that step.
            unexplained = {o: outside(e["handled"], claimed_by_others(step.id, o, PAD)) for o, e in evidence.items()}
            best = _best(unexplained, fps)
            said = {"not_done": "skipped", "cannot_tell": "it couldn't tell", "done": "done but gave no time"}[claim["status"]]
            if best:
                obj, a, b = best
                status, look_at = CANT_VERIFY, a
                reason = f"Spark says {said}, but SAM saw the {label(obj)} in hand at {clock(a)}-{clock(b)}."
                runs = [(o, ra, rb, n) for o, f in unexplained.items() for ra, rb, n in _runs(f, fps) if n > 1]
                sightings = [{"object": o, "found_as": used_name(o), "from": ra, "to": rb}
                             for o, ra, rb, _ in sorted(runs, key=lambda r: -r[3])] or \
                            [{"object": obj, "found_as": used_name(obj), "from": a, "to": b}]
            elif claim["status"] == "not_done" and seen_anywhere:
                status, look_at = MISSING, None
                reason = f"Spark saw it skipped, and SAM never saw the {names} in hand outside other steps."
            elif claim["status"] == "not_done":
                # SAM never finding the object at all can mean it wasn't there, or that SAM doesn't know the name
                # ("pepper shaker" for a box of pepper). Missing on Spark's word alone would be one witness, not two.
                status, look_at = CANT_VERIFY, None
                reason = (f"Spark saw it skipped, but SAM couldn't find the {names} anywhere in the video, "
                          f"so it can't back that up.")
            else:
                status, look_at = CANT_VERIFY, None
                reason = f"Spark says {said}, and SAM saw no handling of the {names} to settle it."

        steps.append({
            "id": step.id, "text": step.text, "status": status, "look_at": look_at, "at": at, "reason": reason,
            "evidence": {"object": best[0], "found_as": used_name(best[0]), "from": best[1], "to": best[2]}
                        if best else None,
            "sightings": sightings,
            "spark": claim,
            "sam": {"objects": objects, "seen_anywhere": seen_anywhere,
                    "handled_seconds": {o: round(len(e["handled"]) / fps, 1) for o, e in evidence.items()}},
        })

    return summarize(procedure, steps, spark["other_mistakes"], duration)


def summarize(procedure: Procedure, steps: list[dict], other_mistakes: list, duration: float) -> dict:
    """Check order between verified steps and count the results."""
    by_id = {s["id"]: s for s in steps}
    order = []
    for a, b in procedure.rules:
        sa, sb = by_id[a], by_id[b]
        if sa["status"] == sb["status"] == VERIFIED and sb["at"] < sa["at"]:
            order.append({"before": a, "after": b, "at": sb["at"],
                          "reason": f"{b} was done at {clock(sb['at'])}, before {a} ({clock(sa['at'])}); "
                                    f"the procedure needs {a} first."})

    counts = {k: sum(s["status"] == k for s in steps) for k in (VERIFIED, MISSING, CANT_VERIFY)}
    return {"procedure": procedure.name, "duration": duration, "steps": steps, "order_problems": order,
            "other_mistakes": other_mistakes, "counts": counts}
