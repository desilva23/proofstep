"""Settings, read from the environment and an optional .env file in the repo root."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
RUNS = ROOT / "runs"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=value lines; exported variables take precedence."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if value:
            os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

API_BASE = os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1")
SPARK_MODEL = os.environ.get("PROOFSTEP_SPARK_MODEL", "muse-spark-1.3-contributor")
SAM_MODEL = "sam-3.1"


def api_key() -> str:
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        raise SystemExit("MODEL_API_KEY is not set. Export it, or copy .env.example to .env and fill it in.")
    return key
