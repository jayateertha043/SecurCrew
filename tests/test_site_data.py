"""Tests for site_data.py: the JSON payload the GitHub Pages UI renders."""

from __future__ import annotations

import json
import time

import site_data


def _posted(item, ts):
    it = dict(item)
    it["ts"] = ts
    return it


def test_build_merges_posted_and_pending(monkeypatch):
    now = time.time()
    monkeypatch.setattr(site_data.time, "time", lambda: now)
    queue = {
        "posted": [
            _posted({"title": "Old", "published": now - 86400, "ts": now - 80000}, now - 80000)
        ],
        "pending": [
            {"title": "New", "published": now - 3600, "added_at": now, "ts": now}
        ],
    }
    payload = site_data.build(queue)
    assert payload["count"] == 2
    titles = [r["title"] for r in payload["items"]]
    # newest first
    assert titles == ["New", "Old"]
    statuses = {r["title"]: r["status"] for r in payload["items"]}
    assert statuses["New"] == "queued"
    assert statuses["Old"] == "posted"


def test_build_drops_undated_and_outside_window(monkeypatch):
    now = time.time()
    monkeypatch.setattr(site_data.time, "time", lambda: now)
    queue = {
        "posted": [],
        "pending": [
            {"title": "NoDate", "published": 0, "added_at": now},
            {"title": "TooOld", "published": now - 10 * 86400, "added_at": now},
            {"title": "Future", "published": now + 999999, "added_at": now},
            {"title": "JustRight", "published": now - 1000, "added_at": now},
        ],
    }
    payload = site_data.build(queue)
    assert [r["title"] for r in payload["items"]] == ["JustRight"]
    assert payload["count"] == 1


def test_build_reflects_rss_publish_not_pending_time(monkeypatch):
    now = time.time()
    monkeypatch.setattr(site_data.time, "time", lambda: now)
    queue = {
        "posted": [],
        "pending": [
            # added earlier but published much more recently -> should sort first
            {"title": "A", "published": now - 500, "added_at": now - 5000},
            {"title": "B", "published": now - 2000, "added_at": now - 100},
        ],
    }
    payload = site_data.build(queue)
    assert [r["title"] for r in payload["items"]] == ["A", "B"]


def test_row_fields():
    row = site_data._row(
        {"title": "T", "summary": "S", "source": "Src", "link": "L",
         "published": 1, "tags": ["#a"], "ai": True},
        "posted", ts=9.0,
    )
    assert row == {
        "title": "T", "summary": "S", "source": "Src", "link": "L",
        "published": 1, "tags": ["#a"], "ai": True, "status": "posted", "ts": 9.0,
    }


def test_write_creates_dirs_and_json(tmp_path):
    queue = {
        "posted": [],
        "pending": [
            {"title": "X", "published": time.time() - 100, "added_at": time.time()}
        ],
    }
    out = tmp_path / "deep" / "items.json"
    site_data.write(queue, str(out))
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["items"][0]["title"] == "X"