"""Load, save, and prune the committed dedup + counter state.

State shape (state/state.json):
    {
        "seen":    { "<sha1-of-link>": <epoch_seconds>, ... },
        "history": [ { "ts": <epoch>, "norm": "<normalized text>" }, ... ],
        "counts":  { "YYYY-MM-DD": <int>, ... }
    }

The only mutable state in the program is the dict returned by ``load``.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

STATE_PATH = os.path.join("state", "state.json")

_EMPTY_STATE: Dict[str, Any] = {"seen": {}, "history": [], "counts": {}}


def load(path: str = STATE_PATH) -> Dict[str, Any]:
    """Read state from disk, returning an empty structure if absent/corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return json.loads(json.dumps(_EMPTY_STATE))

    # Defensive: guarantee all top-level keys exist with the right types.
    data.setdefault("seen", {})
    data.setdefault("history", [])
    data.setdefault("counts", {})
    return data


def save(state: Dict[str, Any], path: str = STATE_PATH) -> None:
    """Write state to disk with a stable, small, diff-friendly layout."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def prune(state: Dict[str, Any], window_days: int, now: float | None = None) -> None:
    """Drop seen links, fuzzy history, and daily counts older than the window."""
    now = time.time() if now is None else now
    cutoff = now - window_days * 86400

    state["seen"] = {
        link_hash: ts for link_hash, ts in state["seen"].items() if ts >= cutoff
    }
    state["history"] = [
        rec for rec in state["history"] if rec.get("ts", 0) >= cutoff
    ]

    cutoff_day = time.strftime("%Y-%m-%d", time.gmtime(cutoff))
    state["counts"] = {
        day: n for day, n in state["counts"].items() if day >= cutoff_day
    }
