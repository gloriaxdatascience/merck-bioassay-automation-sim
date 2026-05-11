import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from rich.logging import RichHandler

LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Rich gives coloured, readable terminal output.
# In a real lab, this would ship to a central log aggregator.
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("lab")


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string. Used on every log entry."""
    return datetime.now(timezone.utc).isoformat()


def log_event(event: dict, log_file: str = "run_log.jsonl") -> None:
    """
    Append a structured JSON event to the run log.

    Why JSONL (newline-delimited JSON)?
    Each line is a valid JSON object. Easy to tail, grep, or load into pandas.
    Real lab systems like LIMS and MES use this pattern for audit trails.
    """
    path = LOG_DIR / log_file
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")
    logger.info(f"[{event.get('source','?')}] {event.get('event','?')} | "
                f"plate={event.get('plate_id','?')} | status={event.get('status','?')}")


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(data: dict, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved JSON → {path}")