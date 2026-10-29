"""Small Meta Model API client: file uploads and streamed responses, with retries, caching and a cost log.

Only the standard library is used, so the pipeline runs without installing anything.
"""

import hashlib
import json
import random
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import config

RETRY_STATUSES = {429, 500, 502, 503, 504}

# USD per 1M tokens: (cached input, input, output)
TOKEN_PRICES = {
    "standard": (0.15, 1.25, 4.25),
    "contributor": (0.002, 0.10, 0.20),
}
SAM_USD_PER_FRAME = 0.20 / 1000

UPLOADS = config.CACHE / "uploads.json"
RESPONSES = config.CACHE / "responses"
COSTS = config.DATA / "costs.jsonl"


class ApiError(RuntimeError):
    pass


def _request(method: str, path: str, *, body: bytes | None = None, headers: dict | None = None, timeout: float = 120):
    """Open a request, retrying rate limits and server errors with backoff (honours Retry-After)."""
    url = config.API_BASE + path
    all_headers = {"Authorization": f"Bearer {config.api_key()}", **(headers or {})}
    for attempt in range(6):
        req = urllib.request.Request(url, data=body, headers=all_headers, method=method)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < 5:
                wait = float(e.headers.get("Retry-After") or 2 ** attempt)
                time.sleep(min(wait, 60) + random.random())
                continue
            detail = e.read().decode(errors="replace")[:500]
            raise ApiError(f"{method} {path} returned HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            if attempt < 5:
                time.sleep(2 ** attempt + random.random())
                continue
            raise ApiError(f"{method} {path} failed: {e.reason}") from None
    raise ApiError(f"{method} {path} kept failing")


def get_json(path: str) -> dict:
    with _request("GET", path) as resp:
        return json.load(resp)


def upload(path: Path, content_type: str = "video/mp4", ttl_seconds: int = 7 * 86400) -> str:
    """Upload a file for use in requests; reuses the file id while it is still valid."""
    stat = path.stat()
    key = f"{config.API_BASE}|{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
    cache = json.loads(UPLOADS.read_text()) if UPLOADS.exists() else {}
    hit = cache.get(key)
    if hit and hit["expires_at"] > time.time() + 3600:
        return hit["id"]

    boundary = uuid.uuid4().hex
    fields = {
        "purpose": "user_data",
        "expires_after[anchor]": "created_at",
        "expires_after[seconds]": str(ttl_seconds),
    }
    head = b"".join(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    )
    head += (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
             f"Content-Type: {content_type}\r\n\r\n").encode()
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()

    print(f"  uploading {path.name} ({stat.st_size / 1e6:.1f} MB)")
    with _request("POST", "/files", body=body, timeout=900,
                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}) as resp:
        info = json.load(resp)
    cache[key] = {"id": info["id"], "expires_at": time.time() + ttl_seconds}
    UPLOADS.parent.mkdir(parents=True, exist_ok=True)
    UPLOADS.write_text(json.dumps(cache, indent=2))
    return info["id"]


def _sse_events(resp):
    """Yield the JSON payload of each server-sent event."""
    data_lines: list[str] = []
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line and data_lines:
            payload, data_lines = "\n".join(data_lines), []
            if payload != "[DONE]":
                yield json.loads(payload)
    if data_lines and data_lines != ["[DONE]"]:
        yield json.loads("\n".join(data_lines))


def stream(body: dict, timeout: float = 900) -> tuple[str, dict]:
    """POST /responses with streaming (long non-streamed requests can hit a 504). Returns (text, final response)."""
    data = json.dumps({**body, "stream": True}).encode()
    text: list[str] = []
    final = None
    with _request("POST", "/responses", body=data, timeout=timeout,
                  headers={"Content-Type": "application/json", "Accept": "text/event-stream"}) as resp:
        for event in _sse_events(resp):
            kind = event.get("type")
            if kind == "response.output_text.delta":
                text.append(event.get("delta", ""))
            elif kind in ("response.completed", "response.incomplete"):
                final = event.get("response") or {}
            elif kind in ("response.failed", "error"):
                raise ApiError(f"response failed: {json.dumps(event)[:500]}")
    if final is None:
        raise ApiError("the stream ended without a completed response")
    if final.get("status") == "incomplete":
        reason = (final.get("incomplete_details") or {}).get("reason", "unknown")
        print(f"  warning: response incomplete ({reason})")
    return "".join(text), final


def token_cost(model: str, usage: dict) -> float:
    cached_price, input_price, output_price = TOKEN_PRICES["contributor" if "contributor" in model else "standard"]
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
    fresh = usage.get("input_tokens", 0) - cached
    return (cached * cached_price + fresh * input_price + usage.get("output_tokens", 0) * output_price) / 1e6


def log_cost(label: str, usd: float, **detail) -> None:
    COSTS.parent.mkdir(parents=True, exist_ok=True)
    with COSTS.open("a") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label, "usd": round(usd, 5), **detail}) + "\n")
    total = sum(json.loads(line)["usd"] for line in COSTS.read_text().splitlines() if line.strip())
    print(f"  cost ${usd:.4f} (all runs so far ${total:.2f})")


def response_cache_path(cache_key: dict) -> Path:
    digest = hashlib.sha256(json.dumps(cache_key, sort_keys=True).encode()).hexdigest()[:24]
    return RESPONSES / f"{digest}.json"


def cached_stream(cache_key: dict, body_fn, label: str, cost_fn) -> tuple[str, dict]:
    """Run a streamed request once per cache_key and reuse the saved answer afterwards.

    body_fn builds the request lazily so cache hits skip uploads; cost_fn(final) prices the call.
    """
    path = response_cache_path(cache_key)
    if path.exists():
        saved = json.loads(path.read_text())
        return saved["text"], saved["response"]
    text, final = stream(body_fn())
    log_cost(label, cost_fn(final), usage=final.get("usage"))
    final = {k: v for k, v in final.items() if k != "output"}  # the text is saved once, below
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": cache_key, "text": text, "response": final}))
    return text, final
