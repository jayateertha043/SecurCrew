"""Load, save, and prune the committed post queue (state/queue.json).

Queue shape:
    {
        "pending": [ { "id", "title", "link", "summary", "source",
                       "published", "added_at" }, ... ],   # FIFO, oldest first
        "posted":  [ { "id", "link", "ts" }, ... ]          # audit / recent log
    }

``pending`` is the producer/consumer buffer: ``collect.py`` appends, and
``publish.py`` pops from the front.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

QUEUE_PATH = os.path.join("state", "queue.json")

_EMPTY: Dict[str, Any] = {"pending": [], "posted": []}


def load(path: str = QUEUE_PATH) -> Dict[str, Any]:
    """Read the queue, returning an empty structure if absent/corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(_EMPTY))
    data.setdefault("pending", [])
    data.setdefault("posted", [])
    return data


def save(queue: Dict[str, Any], path: str = QUEUE_PATH) -> None:
    """Write the queue with a stable, diff-friendly layout."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(queue, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def pending_ids(queue: Dict[str, Any]) -> set:
    """Ids currently waiting in the queue (used to avoid re-enqueueing)."""
    return {rec.get("id") for rec in queue["pending"]}


def prune(
    queue: Dict[str, Any],
    posted_window_days: int,
    pending_ttl_days: int,
    now: float | None = None,
) -> None:
    """Drop stale pending items and old posted-log entries."""
    now = time.time() if now is None else now
    posted_cutoff = now - posted_window_days * 86400
    pending_cutoff = now - pending_ttl_days * 86400

    queue["pending"] = [
        rec for rec in queue["pending"] if rec.get("added_at", now) >= pending_cutoff
    ]
    queue["posted"] = [
        rec for rec in queue["posted"] if rec.get("ts", 0) >= posted_cutoff
    ]
