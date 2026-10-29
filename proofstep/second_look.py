"""Stage 4: a second look at each "can't verify", on short clips where the problem is.

Asking Spark the same question about the whole video again doesn't help: its answers never changed
between runs. These are narrower questions about short clips:

- Spark placed the step in time, but SAM never saw its object in hand. Usually a naming miss ("milk jug"
  matches nothing). Spark names what is in the person's hands in plain words, SAM searches again, and
  the rules run again.
- Spark placed the step, but SAM only matched a generic stand-in name ("box" for "salt box"). Spark looks
  closely at that moment; only a "yes" verifies the step.
- Spark said the step was skipped, but SAM saw its object in hand. Spark looks closely at every such
  moment. A "yes" at any of them verifies the step: both witnesses agree on a specific moment. If every
  moment is something else, the step is missing: each sighting now has a positive explanation. Anything
  short of that stays can't verify.

One "no" is never enough on its own. In 8_50 the chocolate went in at 3:03, while the moment SAM flagged
(3:21) only showed the bag being put away. proofstep changes its mind on evidence found, never on
evidence not found, which is why every sighting must be explained before a step is called missing.
"""

import copy
from pathlib import Path

from . import decide, evidence, video, watch
from .decide import CANT_VERIFY, MISSING, VERIFIED, clock
from .procedure import Procedure

# Each moment is looked at twice, and only an agreed answer counts. A short clip catches brief actions
# (the two chips in 8_3 at 2:42, which a 60 s clip missed); a wide one catches an action that happens
# well before a put-away or after a pick-up. Seconds before, seconds after, longest clip:
NARROW = (5.0, 10.0, 45.0)
WIDE = (20.0, 20.0, 60.0)
MIN_CLIP = 12.0
MAX_SIGHTINGS = 4        # more unexplained moments than this and "missing" can't be concluded

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

Another check saw a {obj} in the person's hand around {at:.0f} seconds into this clip. Watch closely, including brief actions that last only a second: is step {sid} actually performed in this clip?
- answer: "yes" if you see the step's action performed, even if with a different ingredient, container or amount than written; "no" if you can see the step's action is not performed in this clip; "cannot_tell" if the view does not show enough.
- time_sec: when the step happens, in seconds from the start of this clip; null if it does not.
- substitution: if the step is performed with something different from what is written (for example powdered sugar instead of white sugar, or a plate instead of a mug), say what; otherwise null.
- what_happens: one or two sentences on what the person does with the {obj}."""

LOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": ["yes", "no", "cannot_tell"]},
        "time_sec": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "substitution": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "what_happens": {"type": "string"},
    },
    "required": ["answer", "time_sec", "substitution", "what_happens"],
    "additionalProperties": False,
}




def _window(a: float, b: float, duration: float, shape: tuple[float, float, float]) -> tuple[float, float]:
    before, after, longest = shape
    start, end = max(0.0, a - before), min(duration, b + after)
    if end - start > longest:
        middle = (a + b) / 2
        start, end = max(0.0, middle - longest / 2), min(duration, middle + longest / 2)
    if end - start < MIN_CLIP:
        grow = (MIN_CLIP - (end - start)) / 2
        start, end = max(0.0, start - grow), min(duration, end + grow)
    return round(start, 1), round(end, 1)


def _merge(sightings: list[dict], duration: float) -> list[dict]:
    """Drop sightings already covered by the wide clip of a longer one (sightings come longest first)."""
    kept: list[tuple[tuple[float, float], dict]] = []
    for s in sightings:
        if not any(w[0] <= s["from"] and s["to"] <= w[1] for w, _ in kept):
            kept.append((_window(s["from"], s["to"], duration, WIDE), s))
    return [s for _, s in kept]


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

    def look(step, sighting) -> dict:
        """Ask about one moment on a short and a wide clip; the verdict is "yes" or "no" only if both agree."""
        looks = []
        for shape in (NARROW, WIDE):
            window = _window(sighting["from"], sighting["to"], duration, shape)
            answer = ask_clip(window, LOOK_PROMPT, LOOK_SCHEMA, "second_look_step", step,
                              obj=sighting["found_as"], at=(sighting["from"] + sighting["to"]) / 2 - window[0])
            t = answer.get("time_sec")
            looks.append({
                "clip": window, "answer": answer.get("answer"),
                "time": None if t is None else window[0] + min(max(float(t), 0.0), window[1] - window[0]),
                "substitution": answer.get("substitution"), "what_happens": (answer.get("what_happens") or "").strip(),
            })
        short, wide = looks
        verdict = short["answer"] if short["answer"] == wide["answer"] in ("yes", "no") else "unsure"
        if verdict == "yes":
            time = short["time"] if short["time"] is not None else wide["time"]
            what = short["what_happens"]
        elif verdict == "no":
            time, what = None, wide["what_happens"]
        else:
            time = next((l["time"] for l in looks if l["answer"] == "yes"), None)
            what = (f"On a short clip Spark says {short['answer']} ({short['what_happens']}); "
                    f"on a wider one, {wide['answer']} ({wide['what_happens']})")
        substitution = (short["substitution"] or wide["substitution"]) if verdict == "yes" else None
        return {"object": sighting["found_as"], "seen_at": sighting["from"], "verdict": verdict, "time": time,
                "what_happens": what, "substitution": substitution, "looks": looks}

    def note_substitution(step, result) -> str:
        # Done, but not as written: a different flag from "missing" (8_50 uses powdered sugar, 12_41 vinegar).
        if result["substitution"]:
            step["substitution"] = result["substitution"].strip()
            return f" Substitution: {step['substitution']}."
        return ""

    # 1. Naming misses: Spark placed the step in time, but SAM found nothing near then, under any name.
    claims = copy.deepcopy(spark)
    renamed = {}
    for s in report["steps"]:
        claim = claims["steps"][s["id"]]
        if s["status"] != CANT_VERIFY or claim["status"] != "done" or claim["start"] is None or s["evidence"]:
            continue
        window = _window(claim["start"], claim["end"], duration, WIDE)
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

    for s in report["steps"]:
        if s["status"] != CANT_VERIFY or not s["evidence"]:
            continue
        ev = s["evidence"]

        # 2. Weak match: Spark placed the step, SAM matched only a generic stand-in name near then.
        if not s["sightings"]:
            print(f"Second look at {s['id']} ({clock(ev['from'])}): is it done here?")
            result = look(s, ev)
            s["second_look"] = {"kind": "confirm", **result}
            if result["verdict"] == "yes":
                s.update(status=VERIFIED, at=s["spark"]["start"],
                         reason=f"Spark saw it at {clock(s['spark']['start'])}. SAM matched only a '{ev['found_as']}' "
                                f"in hand at {clock(ev['from'])}-{clock(ev['to'])}, and on close looks Spark sees the "
                                f"step done there: {result['what_happens']}{note_substitution(s, result)}")
            else:
                s["reason"] += f" Close looks didn't confirm it. {result['what_happens']}"
            continue

        # 3. Disagreement: Spark didn't place the step, but SAM saw its object in hand. Check every moment.
        sightings = _merge(s["sightings"], duration)
        results = []
        for sighting in sightings[:MAX_SIGHTINGS]:
            print(f"Second look at {s['id']} ({clock(sighting['from'])}): is it done here?")
            results.append(look(s, sighting))
            if results[-1]["verdict"] == "yes":
                break
        s["second_look"] = {"kind": "sightings", "checked": results, "sightings": len(sightings)}
        said = "skipped" if s["spark"]["status"] == "not_done" else "unclear"
        found = next((r for r in results if r["verdict"] == "yes"), None)
        if found:
            at = found["time"] if found["time"] is not None else found["seen_at"]
            s.update(status=VERIFIED, look_at=at, at=at,
                     reason=f"Spark first said {said}, but SAM saw the {found['object']} in hand near "
                            f"{clock(found['seen_at'])}. On close looks at that moment, Spark sees it done at "
                            f"{clock(at)}: {found['what_happens']}{note_substitution(s, found)}")
        elif (s["spark"]["status"] == "not_done" and len(sightings) <= MAX_SIGHTINGS
              and all(r["verdict"] == "no" for r in results)):
            moments = ", ".join(clock(r["seen_at"]) for r in results)
            s.update(status=MISSING, look_at=None,
                     reason=f"Spark saw it skipped. SAM saw the {results[0]['object']} in hand {len(results)} time(s) "
                            f"(around {moments}); on close looks at each, Spark says none of them is this step: "
                            f"{results[0]['what_happens']}")
        else:
            unsure = next((r for r in results if r["verdict"] == "unsure"), None)
            if unsure:
                s.update(look_at=unsure["time"] if unsure["time"] is not None else unsure["seen_at"])
                s["reason"] += f" Close looks at {clock(unsure['seen_at'])} disagree. {unsure['what_happens']}"
            elif len(sightings) > MAX_SIGHTINGS:
                s["reason"] += f" {len(sightings)} moments to check, too many to rule out."
            else:
                s["reason"] += " Close looks say none of these moments is this step, but Spark couldn't tell either way."

    return decide.summarize(procedure, report["steps"], spark["other_mistakes"], duration)
