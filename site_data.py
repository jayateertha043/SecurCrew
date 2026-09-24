"""Emit the JSON feed consumed by the GitHub Pages UI (docs/data/items.json).

Merges the queue's ``posted`` (published) and ``pending`` (upcoming) records
into a single, newest-first list the static site renders. Called at the end of
both the collect and publish phases so the site reflects the latest state.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

SITE_DATA_PATH = os.path.join("docs", "data", "items.json")


def _row(item: Dict[str, Any], status: str, ts: float) -> Dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "summary": item.get("summary", ""),
        "source": item.get("source", ""),
        "link": item.get("link", ""),
        "published": item.get("published", 0),
        "tags": item.get("tags", []),
        "status": status,
        "ts": ts,
    }


def build(queue: Dict[str, Any]) -> Dict[str, Any]:
    """Build the site payload from the queue."""
    rows: List[Dict[str, Any]] = []
    for item in queue.get("posted", []):
        rows.append(_row(item, "posted", float(item.get("ts", 0) or 0)))
    for item in queue.get("pending", []):
        rows.append(_row(item, "queued", float(item.get("added_at", 0) or 0)))

    rows.sort(key=lambda r: r["ts"], reverse=True)
    return {"generated_at": time.time(), "count": len(rows), "items": rows}


def write(queue: Dict[str, Any], path: str = SITE_DATA_PATH) -> None:
    """Write the site payload to ``path`` (creating parent dirs)."""
    payload = build(queue)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
