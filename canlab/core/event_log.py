"""Structured JSONL event log (P2.3 trust infrastructure).

One JSON object per line, appended to ~/.canlab/logs/events-YYYYMMDD.jsonl.
Intended for after-the-fact troubleshooting: what happened, in which function,
how long it took, and what failed.

Usage:
    from core.event_log import log_event
    log_event("can.connect", iface="pcan", bitrate=500000)
    log_event("ai.analysis", id="0x2C4", provider="DeepSeek",
              duration_ms=1823, ok=True)
    log_event("log.load", path="drive.csv", frames=5000, duration_ms=120)

Failures to write must never break the app — logging is best-effort.
"""
import json
import os
import threading
import time
import traceback
from datetime import datetime, timezone

_LOCK = threading.Lock()
_LOG_DIR = os.path.join(os.path.expanduser("~"), ".canlab", "logs")


def log_dir() -> str:
    return _LOG_DIR


def _log_path(now: float) -> str:
    day = datetime.fromtimestamp(now).strftime("%Y%m%d")
    return os.path.join(_LOG_DIR, f"events-{day}.jsonl")


def log_event(event_type: str, *, level: str = "info",
              func: str = "", duration_ms=None, error: str = "",
              **fields) -> dict:
    """Append one structured event. Returns the event dict written.

    event_type: dotted category, e.g. "log.load", "can.connect", "ai.analysis"
    level:      "info" | "warning" | "error"
    func:       originating function/method name
    duration_ms: optional elapsed time
    error:      exception message; traceback is captured automatically
    """
    now = time.time()
    event = {
        "ts":      round(now, 3),
        "iso":     datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "type":    event_type,
        "level":   level,
    }
    if func:
        event["func"] = func
    if duration_ms is not None:
        event["duration_ms"] = round(float(duration_ms), 1)
    if error:
        event["error"] = error
        event["level"] = "error"
        event["traceback"] = traceback.format_exc(limit=8)
    event.update({k: v for k, v in fields.items() if v is not None})

    line = json.dumps(event, ensure_ascii=False, default=str)
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        with _LOCK:
            with open(_log_path(now), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except (OSError, ValueError):
        pass  # never let logging break the app
    return event


def read_events(path: str = None, limit: int = 1000) -> list:
    """Read back events (newest last). For tests and future log viewer."""
    path = path or _log_path(time.time())
    events = []
    try:
        with open(path, encoding="utf-8") as fh:
            for ln, raw in enumerate(fh):
                if ln >= limit:
                    break
                raw = raw.strip()
                if raw:
                    events.append(json.loads(raw))
    except OSError:
        pass
    return events
