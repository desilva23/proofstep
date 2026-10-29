"""Stage 1: Muse Spark watches the whole video and claims, step by step, what happened and when.

It also names the physical objects a camera would see handled in each step. SAM needs those names:
in testing "cinnamon" matched nothing in any frame, while "spice jar" found the jar.
"""

import json
from pathlib import Path

from . import api, config, video
from .procedure import Procedure

STATUSES = ("done", "not_done", "cannot_tell")

PROMPT = """You are checking a first-person video of someone following a procedure. The video is {duration:.0f} seconds long.

{procedure}

For every step, judge only from what is visible in the video:
- status: "done" if you see it happen, "not_done" if the video shows it was skipped, "cannot_tell" if the video does not let you decide (for example, the action is out of view).
- start_sec and end_sec: when the step happens, in seconds from the start of the video. Use null if it was not done.
- objects: one or two short names for the physical things a camera would see being picked up or used in this step, as they look in this video: containers, packets, tools or appliances (for example "spice jar", "milk carton", "spoon", "microwave"). Name the container, not the ingredient inside it. Pick things that belong to this step rather than the main cup, bowl or pan that most steps use. If the step was not done, name what would have been handled.
- evidence: one sentence on what you saw.

Do not assume a step happened because a later step did. Also list any other mistakes you notice, such as spills, wrong amounts or wrong technique, with the time."""


def _schema(procedure: Procedure) -> dict:
    ids = [s.id for s in procedure.steps]
    number_or_null = {"anyOf": [{"type": "number"}, {"type": "null"}]}
    step = {
        "type": "object",
        "properties": {
            "step_id": {"type": "string", "enum": ids},
            "status": {"type": "string", "enum": list(STATUSES)},
            "start_sec": number_or_null,
            "end_sec": number_or_null,
            "objects": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "string"},
        },
        "required": ["step_id", "status", "start_sec", "end_sec", "objects", "evidence"],
        "additionalProperties": False,
    }
    mistake = {
        "type": "object",
        "properties": {
            "step_id": {"anyOf": [{"type": "string", "enum": ids}, {"type": "null"}]},
            "time_sec": number_or_null,
            "description": {"type": "string"},
        },
        "required": ["step_id", "time_sec", "description"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"steps": {"type": "array", "items": step}, "other_mistakes": {"type": "array", "items": mistake}},
        "required": ["steps", "other_mistakes"],
        "additionalProperties": False,
    }


def _clean_step(raw: dict | None, duration: float) -> dict:
    if raw is None:
        return {"status": "cannot_tell", "start": None, "end": None, "objects": [], "evidence": "Spark gave no answer for this step."}
    start, end = raw.get("start_sec"), raw.get("end_sec")
    if start is not None and end is not None and start > end:
        start, end = end, start
    clamp = lambda t: None if t is None else min(max(float(t), 0.0), duration)
    objects = list(dict.fromkeys(o.strip().lower() for o in raw.get("objects") or [] if o.strip()))[:2]
    status = raw.get("status") if raw.get("status") in STATUSES else "cannot_tell"
    return {"status": status, "start": clamp(start), "end": clamp(end), "objects": objects,
            "evidence": raw.get("evidence", "")}


def watch(procedure: Procedure, video_path: Path, *, model: str | None = None, effort: str = "medium") -> dict:
    model = model or config.SPARK_MODEL
    src = video.for_spark(video_path)
    duration = video.probe(src)["duration"]
    prompt = PROMPT.format(duration=duration, procedure=procedure.describe())
    schema = _schema(procedure)

    def body() -> dict:
        file_id = api.upload(src)
        return {
            "model": model,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_file", "file_id": file_id},
            ]}],
            "reasoning": {"effort": effort},
            "text": {"format": {"type": "json_schema", "name": "procedure_check", "schema": schema}},
            "max_output_tokens": 20000,
        }

    key = {"stage": "watch", "video": f"{src.name}:{src.stat().st_size}", "model": model, "effort": effort,
           "prompt": prompt, "schema": schema}
    print(f"Spark ({model}) watching {video_path.name}")
    text, final = api.cached_stream(key, body, f"watch {video_path.stem}",
                                    lambda f: api.token_cost(model, f.get("usage") or {}))
    try:
        answer = json.loads(text)
    except json.JSONDecodeError as e:
        raise api.ApiError(f"Spark's answer was not valid JSON ({e}); raw text starts: {text[:200]!r}") from None

    by_id = {s.get("step_id"): s for s in answer.get("steps", [])}
    return {
        "model": model,
        "effort": effort,
        "duration": duration,
        "steps": {s.id: _clean_step(by_id.get(s.id), duration) for s in procedure.steps},
        "other_mistakes": answer.get("other_mistakes", []),
        "usage": final.get("usage"),
    }
