"""Stage 5: search where the step must be, to point a person at the right moment.

Watching the whole video, Spark misses brief actions (two chocolate chips dropped in a second). The
procedure says roughly when each step has to happen: after the steps that must come before it, and before
the ones that must come after. So for every step still unresolved, Spark is asked about that window in
short overlapping slices; if nothing turns up, the rest of the video is searched too, since steps are
sometimes done out of order.

A "yes" is checked with an open question on a wider clip: which step of the procedure is the person doing
here? It counts only if Spark names this step unprompted. Asked "is it step S5?", models lean towards yes.

The search points; a person decides. What it finds becomes "can't verify, likely at 2:42", so whoever
checks watches a few seconds instead of the whole video. It never verifies a step by itself: on look-alike
steps (salt and pepper, chopping and peeling) Spark can describe an action that didn't happen, and when the
search was allowed to decide, it passed two skipped steps as done. A step Spark called skipped becomes
missing only with both witnesses: every slice of the whole video clearly shows it isn't done, and SAM saw
nothing in hand that the second look couldn't explain.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import decide, video, watch
from .decide import CANT_VERIFY, MISSING, VERIFIED, clock
from .procedure import Procedure
from .second_look import CONTEXT, LOOK_SCHEMA

SLICE, STRIDE = 20.0, 15.0   # short looks: 20 s, overlapping by 5 s so nothing falls on a boundary
CONFIRM = 40.0               # the wider look that must agree with a "yes"
MARGIN = 10.0                # slack around the window the order rules give
WORKERS = 4
MAX_LOOKS = 120              # per video, to bound cost (about $0.10)

SEARCH_PROMPT = CONTEXT + """Focus on one step: {sid}: {text}

Watch closely, including actions that last only a second. Is step {sid} performed in this clip? Other steps of the procedure handle similar things; answer "yes" only if this step's own action happens here.
- answer: "yes" if you see it performed, even with a different ingredient, container or amount than written; "no" if the clip clearly shows it is not performed here; "cannot_tell" if the view does not show enough.
- time_sec: when the step happens, in seconds from the start of this clip; null if it does not.
- substitution: if it is performed with something different from what is written, say what; otherwise null.
- what_happens: one sentence on what the person does in this clip."""


WHICH_PROMPT = CONTEXT + """Around {at:.0f} seconds into this clip, which step of the procedure is the person performing?
- step_id: the id of that step (S1, S2, ...), or "none" if they aren't performing any step of the procedure then.
- why: one sentence on what you see that identifies it."""


def _which_schema(procedure: Procedure) -> dict:
    return {
        "type": "object",
        "properties": {"step_id": {"type": "string", "enum": [s.id for s in procedure.steps] + ["none"]},
                       "why": {"type": "string"}},
        "required": ["step_id", "why"],
        "additionalProperties": False,
    }


def _slices(lo: float, hi: float) -> list[tuple[float, float]]:
    if hi - lo <= SLICE:
        return [(round(lo, 1), round(hi, 1))]
    starts = []
    t = lo
    while t + SLICE < hi:
        starts.append(t)
        t += STRIDE
    starts.append(hi - SLICE)
    return [(round(a, 1), round(a + SLICE, 1)) for a in starts]


def _sightings_explained(step: dict) -> bool:
    """True when SAM knows the object (saw it somewhere) and either never saw it in hand for this step or the
    second look explained every moment it did. Like the main rules, missing needs SAM to recognise the object."""
    if not step["sam"]["seen_anywhere"]:
        return False
    if not step.get("sightings"):
        return True
    look = step.get("second_look") or {}
    checked = look.get("checked") or []
    return look.get("kind") == "sightings" and len(checked) >= look.get("sightings", 0) \
        and all(c.get("verdict") == "no" for c in checked)


def search(procedure: Procedure, video_path: Path, spark: dict, report: dict, *,
           model: str | None = None, effort: str = "medium") -> dict:
    src = video.for_spark(video_path)
    duration = spark["duration"]
    by_id = {s["id"]: s for s in report["steps"]}
    budget = {"looks": 0}

    def ask(step, window) -> dict:
        budget["looks"] += 1
        prompt = SEARCH_PROMPT.format(length=window[1] - window[0], procedure=procedure.describe(),
                                      sid=step["id"], text=step["text"])
        answer, _ = watch.ask(video.clip(src, *window), prompt, LOOK_SCHEMA, stage="search", name="search",
                              label=f"search {video_path.stem} {step['id']}", model=model, effort=effort)
        t = answer.get("time_sec")
        when = None if t is None else window[0] + min(max(float(t), 0.0), window[1] - window[0])
        return {"clip": window, "answer": answer.get("answer"), "time": when,
                "substitution": answer.get("substitution"), "what_happens": (answer.get("what_happens") or "").strip()}

    def which(step, window, at) -> dict:
        budget["looks"] += 1
        prompt = WHICH_PROMPT.format(length=window[1] - window[0], procedure=procedure.describe(), at=at - window[0])
        answer, _ = watch.ask(video.clip(src, *window), prompt, _which_schema(procedure), stage="search_which",
                              name="which_step", label=f"which {video_path.stem} {step['id']}", model=model, effort=effort)
        return answer

    def expected(sid: str) -> tuple[float, float]:
        """After the verified steps that must come before, before the verified steps that must come after."""
        at = lambda x: by_id[x]["at"] if by_id[x]["status"] == VERIFIED and by_id[x]["at"] is not None else None
        before = [at(a) for a, b in procedure.rules if b == sid and at(a) is not None]
        after = [at(b) for a, b in procedure.rules if a == sid and at(b) is not None]
        lo, hi = max(before, default=0.0) - MARGIN, min(after, default=duration) + MARGIN
        lo, hi = max(0.0, lo), min(duration, hi)
        return (0.0, duration) if hi - lo < SLICE / 2 else (lo, hi)  # contradictory bounds: search everything

    def sweep(step, windows) -> tuple[dict | None, list[dict]]:
        """Short looks over the windows, then a wide look at each "yes" until one agrees."""
        windows = [w for w in windows if budget["looks"] < MAX_LOOKS]
        with ThreadPoolExecutor(WORKERS) as pool:
            looks = list(pool.map(lambda w: ask(step, w), windows))
        for hit in (l for l in looks if l["answer"] == "yes"):
            center = hit["time"] if hit["time"] is not None else sum(hit["clip"]) / 2
            wide = (round(max(0.0, center - CONFIRM / 2), 1), round(min(duration, center + CONFIRM / 2), 1))
            if budget["looks"] >= MAX_LOOKS:
                break
            check = which(step, wide, center)
            if check.get("step_id") == step["id"]:
                return {**hit, "confirmed_by": check}, looks
        return None, looks

    for s in report["steps"]:
        if s["status"] not in (CANT_VERIFY, MISSING) or budget["looks"] >= MAX_LOOKS:
            continue
        lo, hi = expected(s["id"])
        print(f"Searching for {s['id']} between {clock(lo)} and {clock(hi)}")
        found, looks = sweep(s, _slices(lo, hi))
        searched = [(lo, hi)]
        if not found and (lo > 0 or hi < duration):
            # Not where the order says it should be: maybe done out of order.
            rest = [w for w in _slices(0.0, duration) if w[1] <= lo + SLICE / 2 or w[0] >= hi - SLICE / 2]
            if rest:
                print(f"  not there; searching the rest of the video for {s['id']}")
                found, more = sweep(s, rest)
                looks += more
                searched = [(0.0, duration)]
        s["search"] = {"window": [round(lo, 1), round(hi, 1)], "looks": len(looks),
                       "found": found and {k: found[k] for k in ("clip", "time", "what_happens")}}

        whole = searched == [(0.0, duration)] or (lo == 0.0 and hi == duration)
        if found:
            at = found["time"] if found["time"] is not None else found["clip"][0]
            s["search"]["pointer"] = round(at, 1)
            lead = ("proofstep had called it missing, but searching " if s["status"] == MISSING
                    else "Searching ")
            s.update(status=CANT_VERIFY, look_at=at,
                     reason=f"{lead}{clock(lo)}-{clock(hi)}, where the order says it belongs, Spark sees it at "
                            f"{clock(at)}: {found['what_happens']} Asked openly which step is happening then, it "
                            f"names {s['id']}. Likely done: watch from {clock(max(0.0, at - 3))} to confirm.")
        elif s["status"] == CANT_VERIFY and s["spark"]["status"] == "not_done" and whole \
                and looks and all(l["answer"] == "no" for l in looks) and _sightings_explained(s):
            s.update(status=MISSING, look_at=None,
                     reason=f"Spark saw it skipped. Searching the whole video in {len(looks)} short clips, none shows "
                            f"it done. {s['reason']}")
        elif s["status"] == CANT_VERIFY:
            s["reason"] += f" A search of {clock(lo)}-{clock(hi)} in {len(looks)} short clips didn't find it."

    return decide.summarize(procedure, report["steps"], spark["other_mistakes"], duration)
