"""Tests for state.py: load/save/prune of the dedup + counter state."""

from __future__ import annotations

import json
import time

import state


def test_load_missing_returns_empty(tmp_path):
    data = state.load(str(tmp_path / "nope.json"))
    assert data == {"seen": {}, "history": [], "counts": {}}


def test_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json!!", encoding="utf-8")
    assert state.load(str(p)) == {"seen": {}, "history": [], "counts": {}}


def test_load_partial_fills_defaults(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"seen": {"h": 1}}', encoding="utf-8")
    data = state.load(str(p))
    assert data["seen"] == {"h": 1}
    assert data["history"] == []
    assert data["counts"] == {}


def test_save_roundtrip_stable_layout(tmp_path):
    p = tmp_path / "state.json"
    data = {"seen": {"a": 1.0}, "history": [{"ts": 1.0, "norm": "x"}], "counts": {"2026-09-29": 3}}
    state.save(data, str(p))
    raw = p.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw) == data
    # sort_keys=True + indent=2 => stable, diff-friendly
    assert raw.index('"history"') < raw.index('"seen"')  # alphabetical


def test_save_creates_parent_dirs(tmp_path):
    p = tmp_path / "a" / "b" / "state.json"
    state.save({"seen": {}, "history": [], "counts": {}}, str(p))
    assert p.exists()


def test_prune_seen_and_history_by_window():
    now = time.time()
    st = {
        "seen": {"old": now - 30 * 86400, "new": now - 1000},
        "history": [
            {"ts": now - 20 * 86400, "norm": "old"},
            {"ts": now, "norm": "new"},
        ],
        "counts": {"2020-01-01": 5, "2026-09-29": 2},
    }
    state.prune(st, window_days=7, now=now)
    assert st["seen"] == {"new": now - 1000}
    assert st["history"] == [{"ts": now, "norm": "new"}]
    # counts are pruned by date string comparison against the cutoff day
    assert "2020-01-01" not in st["counts"]
    assert "2026-09-29" in st["counts"]


def test_prune_keeps_everything_within_window():
    now = 1_000_000.0
    st = {
        "seen": {"a": now - 100},
        "history": [{"ts": now - 200, "norm": "x"}],
        "counts": {"2026-09-29": 1},
    }
    before = json.dumps(st, sort_keys=True)
    state.prune(st, window_days=7, now=now)
    assert json.dumps(st, sort_keys=True) == before