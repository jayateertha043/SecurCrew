"""Tests for queue_store.py: the producer/consumer post queue."""

from __future__ import annotations

import json

import queue_store


def _q():
    return {"pending": [], "posted": []}


def test_load_missing_returns_empty(tmp_path):
    assert queue_store.load(str(tmp_path / "nope.json")) == _q()


def test_load_corrupt_returns_empty(tmp_path):
    p = tmp_path / "queue.json"
    p.write_text("[]", encoding="utf-8")  # valid JSON but wrong shape
    assert queue_store.load(str(p)) == _q()
    p.write_text("{broken", encoding="utf-8")
    assert queue_store.load(str(p)) == _q()


def test_load_partial_fills_defaults(tmp_path):
    p = tmp_path / "queue.json"
    p.write_text('{"pending": [{"id": "x"}]}', encoding="utf-8")
    data = queue_store.load(str(p))
    assert data["pending"] == [{"id": "x"}]
    assert data["posted"] == []


def test_save_roundtrip(tmp_path):
    p = tmp_path / "state" / "queue.json"
    q = {"pending": [{"id": "1", "title": "t"}], "posted": [{"id": "1", "ts": 1.0}]}
    queue_store.save(q, str(p))
    assert json.loads(p.read_text(encoding="utf-8")) == q


def test_pending_ids():
    q = {"pending": [{"id": "a"}, {"id": "b"}], "posted": []}
    assert queue_store.pending_ids(q) == {"a", "b"}


def test_pending_ids_skips_missing_id():
    # a record with no id contributes None (never matches a real sha1 id)
    q = {"pending": [{"id": "a"}, {}], "posted": []}
    assert queue_store.pending_ids(q) == {"a", None}


def test_prune_pending_ttl_and_posted_window():
    now = 1_000_000.0
    q = {
        "pending": [
            {"id": "stale", "added_at": now - 5 * 86400},   # older than 2-day TTL
            {"id": "fresh", "added_at": now - 1000},         # within TTL
            {"id": "missing", },                              # missing -> kept (assume fresh)
        ],
        "posted": [
            {"id": "p1", "ts": now - 10 * 86400},  # older than 7-day window
            {"id": "p2", "ts": now - 1000},        # within window
        ],
    }
    queue_store.prune(q, posted_window_days=7, pending_ttl_days=2, now=now)
    ids = [r["id"] for r in q["pending"]]
    assert "stale" not in ids
    assert "fresh" in ids
    assert "missing" in ids
    posted_ids = [r["id"] for r in q["posted"]]
    assert "p1" not in posted_ids
    assert "p2" in posted_ids