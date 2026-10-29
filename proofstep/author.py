"""Turn instructions typed in plain words into a Procedure: numbered steps plus "this before that" rules.

Spark reads the text only (no video), so this costs a fraction of a cent. The rules it proposes are
checked here: every rule must name real steps, and the rules must not loop.
"""

import json
import re

from . import api, config
from .procedure import Procedure, Step

PROMPT = """Turn these instructions into a checklist that someone could verify by watching a video of the work.

Instructions:
\"\"\"
{text}
\"\"\"

- steps: one entry per physical action, in the order given, numbered S1, S2, S3 and so on. Write each as a short command that names what is handled and done ("Add 1 teaspoon of sugar to the mug"). Split instructions that combine two actions; leave out advice, warnings and anything that isn't an action.
- rules: pairs where the first step must happen before the second because the second depends on it (you can't stir before pouring). Don't add a rule just because one step is listed before another, and don't add rules that follow from others (if S1 before S2 and S2 before S3, leave out S1 before S3).
- name: a short name for the procedure, two to five words."""

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "steps": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
            "required": ["id", "text"], "additionalProperties": False}},
        "rules": {"type": "array", "items": {
            "type": "object",
            "properties": {"before": {"type": "string"}, "after": {"type": "string"}},
            "required": ["before", "after"], "additionalProperties": False}},
    },
    "required": ["name", "steps", "rules"],
    "additionalProperties": False,
}

MAX_TEXT = 6000


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "procedure"


def _without_cycles(rules: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Keep rules in order, dropping any that would make the "before" relation loop."""
    kept: list[tuple[str, str]] = []
    for a, b in rules:
        reach, stack = set(), [b]  # adding a -> b loops if a is already reachable from b
        while stack:
            node = stack.pop()
            if node == a:
                break
            if node not in reach:
                reach.add(node)
                stack += [y for x, y in kept if x == node]
        else:
            kept.append((a, b))
    return kept


def write(text: str, *, model: str | None = None) -> Procedure:
    text = text.strip()
    if not text:
        raise ValueError("no instructions given")
    if len(text) > MAX_TEXT:
        raise ValueError(f"instructions are too long ({len(text)} characters; the limit is {MAX_TEXT})")
    model = model or config.SPARK_MODEL
    prompt = PROMPT.format(text=text)
    body = lambda: {
        "model": model,
        "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "reasoning": {"effort": "low"},
        "text": {"format": {"type": "json_schema", "name": "procedure", "schema": SCHEMA}},
        "max_output_tokens": 8000,
    }
    key = {"stage": "author", "model": model, "prompt": prompt, "schema": SCHEMA}
    raw, _ = api.cached_stream(key, body, "write procedure", lambda f: api.token_cost(model, f.get("usage") or {}))
    answer = json.loads(raw)

    # Renumber in order so ids are always S1..Sn, whatever Spark called them.
    renumber, steps = {}, []
    for s in answer.get("steps", []):
        step_text = " ".join(s.get("text", "").split())
        if step_text and s.get("id") not in renumber:
            renumber[s.get("id")] = f"S{len(steps) + 1}"
            steps.append(Step(id=renumber[s["id"]], text=step_text))
    if not steps:
        raise ValueError("Spark found no steps in those instructions")
    rules = [(renumber[r["before"]], renumber[r["after"]]) for r in answer.get("rules", [])
             if r.get("before") in renumber and r.get("after") in renumber and r["before"] != r["after"]]
    rules = _without_cycles(list(dict.fromkeys(rules)))
    return Procedure(name=answer.get("name", "").strip() or "My procedure", steps=steps, rules=rules)
