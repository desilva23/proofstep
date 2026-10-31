"""The open-weight option: Muse Spark Open answers the short-clip questions and writes typed procedures.

Switched on with --open-weights. Muse Spark Open takes text and images, not video, and at most 8 images per
request on Baseten, so a clip becomes 8 evenly spaced frames. That's why the whole-video pass and SAM 3.1
stay on the Meta Model API. Any OpenAI-compatible server works, including your own hardware: set
PROOFSTEP_OPEN_URL, PROOFSTEP_OPEN_MODEL and BASETEN_API_KEY.
"""

import base64
import json
import os
import random
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import api, config, video

URL = os.environ.get("PROOFSTEP_OPEN_URL", "https://inference.baseten.co/v1/chat/completions")
MODEL = os.environ.get("PROOFSTEP_OPEN_MODEL", "meta-models/muse-spark-open")
MAX_IMAGES = 8
MAX_TOKENS = 16000  # reasoning takes most of this; a 4,000 limit left about 1 answer in 25 empty

# USD per token on Baseten
PRICE_INPUT, PRICE_CACHED, PRICE_OUTPUT = 1.25 / 1e6, 0.15 / 1e6, 4.25 / 1e6
COSTS = config.DATA / "costs_open_weights.jsonl"

CLIP_OPENING = re.compile(r"^This is a (\d+)-second clip from a first-person video")


def frame_prompt(prompt: str, count: int) -> str:
    """Reword a question written for a video clip so it fits frames taken from that clip."""
    return CLIP_OPENING.sub(rf"These are {count} frames, in order and evenly spaced, from a \1-second clip "
                            "from a first-person video", prompt, count=1) + (
        "\n\nThe frames are a second or more apart, so judge from what changes between them.")


def json_instruction(schema: dict) -> str:
    return f"\n\nReply with only a JSON object with the keys: {', '.join(schema['properties'])}."


def parse_json(text: str) -> dict:
    """The JSON object in a reply, or {} if there isn't a complete one. An empty answer counts as unsure."""
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        return {}


def _frames(clip: Path) -> list[str]:
    length = video.probe(clip)["duration"]
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf",
                        f"fps={MAX_IMAGES / length:.4f},scale=640:-2", "-frames:v", str(MAX_IMAGES), "-q:v", "4",
                        f"{tmp}/%03d.jpg"], check=True)
        return [base64.b64encode(p.read_bytes()).decode() for p in sorted(Path(tmp).glob("*.jpg"))]


def _log_cost(label: str, usage: dict) -> None:
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    usd = ((usage.get("prompt_tokens", 0) - cached) * PRICE_INPUT + cached * PRICE_CACHED
           + usage.get("completion_tokens", 0) * PRICE_OUTPUT)
    COSTS.parent.mkdir(parents=True, exist_ok=True)
    with COSTS.open("a") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label, "usd": round(usd, 5), "usage": usage}) + "\n")


def _post(content: list[dict]) -> dict:
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        raise SystemExit("BASETEN_API_KEY is not set. Add it to .env to use --open-weights.")
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": content}], "max_tokens": MAX_TOKENS,
                       "response_format": {"type": "json_object"}}).encode()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "proofstep"}
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(URL, data=body, headers=headers, method="POST"), timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in api.RETRY_STATUSES and attempt < 5:
                time.sleep(min(float(e.headers.get("Retry-After") or 2 ** attempt), 60) + random.random())
                continue
            if e.code == 402:
                raise api.ApiError("The inference provider says this account has no credit left (HTTP 402). "
                                   "Finished answers are saved, so re-running continues from here.") from None
            raise api.ApiError(f"{URL} returned HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from None
        except urllib.error.URLError as e:
            if attempt < 5:
                time.sleep(2 ** attempt + random.random())
                continue
            raise api.ApiError(f"{URL} failed: {e.reason}") from None
    raise api.ApiError(f"{URL} kept failing")


def _ask(cache_key: dict, content_fn, label: str) -> tuple[dict, dict]:
    path = api.response_cache_path(cache_key)
    if path.exists():
        saved = json.loads(path.read_text())
        return parse_json(saved["text"]), saved["usage"]
    reply = _post(content_fn())
    text = reply["choices"][0]["message"].get("content") or ""
    usage = reply.get("usage") or {}
    _log_cost(label, usage)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f"{path.stem}.{uuid.uuid4().hex[:8]}.part")
    part.write_text(json.dumps({"key": cache_key, "text": text, "usage": usage}))
    part.replace(path)
    return parse_json(text), usage


def ask_clip(clip: Path, prompt: str, schema: dict, *, stage: str, label: str) -> tuple[dict, dict]:
    """Ask Muse Spark Open about a clip, shown as frames. Returns (answer, usage), like watch.ask."""
    key = {"stage": stage, "backend": "open", "model": MODEL, "clip": f"{clip.name}:{clip.stat().st_size}",
           "prompt": prompt, "schema": schema}

    def content() -> list[dict]:
        images = _frames(clip)
        text = frame_prompt(prompt, len(images)) + json_instruction(schema)
        return [{"type": "text", "text": text}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images]

    return _ask(key, content, label)


def ask_text(prompt: str, schema: dict, *, stage: str, label: str) -> tuple[dict, dict]:
    key = {"stage": stage, "backend": "open", "model": MODEL, "prompt": prompt, "schema": schema}
    return _ask(key, lambda: [{"type": "text", "text": prompt + json_instruction(schema)}], label)
