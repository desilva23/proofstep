"""Stage 4: a second look at each "can't verify", on the short clip where the problem is.

Asking Spark the same question about the whole video again doesn't help: its answers never changed
between runs. These are narrower questions about a short clip:

- Spark placed the step in time, but SAM never saw its object in hand. Usually a naming miss ("milk jug"
  matches nothing). Spark names what is in the person's hands in plain words, SAM searches again, and
  the rules run again.
- Spark said the step was skipped, but SAM saw its object in hand. Spark looks closely at that moment.
  Performed there -> verified: both witnesses now agree on a specific moment. Otherwise it stays
  can't verify, with Spark's account of the moment. A "no" about one clip can't show the step never
  happened: in 8_50 the chocolate went in at 3:03, a moment both models missed, while the clip SAM
  pointed to (3:21) only showed the bag being put away. proofstep changes its mind on evidence found,
  never on evidence not found.
"""

import copy
from pathlib import Path

from . import decide, evidence, video, watch
from .decide import CANT_VERIFY, VERIFIED, clock
from .procedure import Procedure

BEFORE, AFTER = 5.0, 10.0       # context around the moment; the action often follows the pick-up
MIN_CLIP, MAX_CLIP = 12.0, 45.0

CONTEXT = """This is a {length:.0f}-second clip from a first-person video of someone following this procedure:

{procedure}

"""

NAMES_PROMPT = CONTEXT + """In this clip the person should be doing step {sid}: {text}

Name the things in the person's hands while they do it, as plain one- or two-word nouns an object detector would recognise (for example "bottle", "carton", "jar", "bag", "box", "spoon", "cup"). Give up to three, most important first. If the step is not shown, name what is in their hands anyway."""

NAMES_SCHEMA = {
    "type": "object",
    "properties": {"objects": {"type": "array", "items": {"type": "string"}}},
    "required": ["objects"],
    "additionalProperties": False,
}

LOOK_PROMPT = CONTEXT + """Focus on one step: {sid}: {text}

The person handles the {obj} in this clip. Watch closely, including brief actions that last only a second: is step {sid} actually performed in this clip?
- answer: "yes" if you see it performed, "no" if you can see the {obj} is used for something else or the step is not performed, "cannot_tell" if the view does not show enough.
- time_sec: when the step happens, in seconds from the start of this clip; null if it does not.
- what_happens: one or two sentences on what the person does with the {obj}."""

LOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": ["yes", "no", "cannot_tell"]},
        "time_sec": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "what_happens": {"type": "string"},
    },
    "required": ["answer", "time_sec", "what_happens"],
    "additionalProperties": False,
}


def _window(a: float, b: float, duration: float) -> tuple[float, float]:
    start, end = max(0.0, a - BEFORE), min(duration, b + AFTER)
    if end - start > MAX_CLIP:
        end = start + MAX_CLIP
    if end - start < MIN_CLIP:
        grow = (MIN_CLIP - (end - start)) / 2
        start, end = max(0.0, start - grow), min(duration, end + grow)
    return round(start, 1), round(end, 1)


def resolve(procedure: Procedure, video_path: Path, spark: dict, report: dict, *,
            max_sam_usd: float, model: str | None = None, effort: str = "medium") -> dict:
    src = video.for_spark(video_path)
    duration = spark["duration"]

    def ask_clip(window, template, schema, stage, step, **fields) -> dict:
        prompt = template.format(length=window[1] - window[0], procedure=procedure.describe(),
                                 sid=step["id"], text=step["text"], **fields)
        answer, _ = watch.ask(video.clip(src, *window), prompt, schema, stage=stage, name=stage,
                              label=f"{stage} {video_path.stem} {step['id']}", model=model, effort=effort)
        return answer

    # 1. Naming misses: Spark placed the step in time, but SAM never saw its object in hand near then.
    claims = copy.deepcopy(spark)
    renamed = {}
    for s in report["steps"]:
        claim = claims["steps"][s["id"]]
        if s["status"] != CANT_VERIFY or claim["status"] != "done" or claim["start"] is None:
            continue
        window = _window(claim["start"], claim["end"], duration)
        print(f"Second look at {s['id']} ({clock(window[0])}-{clock(window[1])}): what is in their hands?")
        answer = ask_clip(window, NAMES_PROMPT, NAMES_SCHEMA, "second_look_names", s)
        names = dict.fromkeys(o.strip().lower() for o in answer.get("objects", []) if o.strip())
        new = [n for n in names if n not in claim["objects"]][:3]
        claim["objects"] = claim["objects"] + new
        renamed[s["id"]] = {"kind": "names", "clip": window, "new_objects": new}
    if any(r["new_objects"] for r in renamed.values()):
        sam = evidence.gather(video_path, [o for c in claims["steps"].values() for o in c["objects"]],
                              max_usd=max_sam_usd)
        report = decide.decide(procedure, claims, sam)
    for s in report["steps"]:
        if s["id"] in renamed:
            s["second_look"] = renamed[s["id"]]
            if s["status"] == VERIFIED and renamed[s["id"]]["new_objects"]:
                s["reason"] += f" (A second look named what was in hand: {', '.join(renamed[s['id']]['new_objects'])}.)"

    # 2. Disagreements: Spark didn't place the step, but SAM saw its object in hand.
    for s in report["steps"]:
        ev = s["evidence"]
        if s["status"] != CANT_VERIFY or not ev:
            continue
        window = _window(ev["from"], ev["to"], duration)
        obj = ev["object"]
        print(f"Second look at {s['id']} ({clock(window[0])}-{clock(window[1])}): is it done here?")
        answer = ask_clip(window, LOOK_PROMPT, LOOK_SCHEMA, "second_look_step", s, obj=obj)
        verdict, what = answer.get("answer"), (answer.get("what_happens") or "").strip()
        t = answer.get("time_sec")
        when = None if t is None else window[0] + min(max(float(t), 0.0), window[1] - window[0])
        s["second_look"] = {"kind": "look", "clip": window, "answer": verdict, "time": when, "what_happens": what}
        sighting = f"SAM saw the {obj} in hand at {clock(ev['from'])}-{clock(ev['to'])}"
        said = "skipped" if s["spark"]["status"] == "not_done" else "unclear"
        if verdict == "yes":
            at = when if when is not None else ev["from"]
            s.update(status=VERIFIED, look_at=at, at=at,
                     reason=f"Spark first said {said}, but {sighting}. Looking closely at that moment, Spark sees "
                            f"it done at {clock(at)}: {what}")
        elif verdict == "no":
            s["reason"] += f" Looking closely, Spark says that moment isn't this step: {what}"
        else:
            s["reason"] += f" A closer look at that moment didn't settle it: {what}"

    return decide.summarize(procedure, report["steps"], spark["other_mistakes"], duration)
