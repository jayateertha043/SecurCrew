"""Tests for publish.py: queue draining, daily cap, pacing, error handling."""

from __future__ import annotations

import json

import pipeline as P
import publish
import queue_store
import state as state_mod
from tests.conftest import RecordingClient
from tests.conftest import item as mk_item

# --- happy path --------------------------------------------------------------


def test_publish_posts_up_to_budget(iso_cwd, tmp_path, monkeypatch):
    now = 1_000_000.0
    monkeypatch.setattr(P, "today_key", lambda n=now: "2026-09-29")
    monkeypatch.setattr(P, "build_client", lambda: RecordingClient())
    monkeypatch.setattr(P, "DELAY_RANGE", (0, 0))  # no sleeping in tests
    monkeypatch.setattr(publish.time, "time", lambda: now)
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)

    client = RecordingClient()
    monkeypatch.setattr(P, "build_client", lambda: client)
    seed = {
        "pending": [mk_item(id="1", title="First"), mk_item(id="2", title="Second"),
                    mk_item(id="3", title="Third")],
        "posted": [],
    }
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    state_mod.save({"seen": {}, "history": [], "counts": {}},
                   str(tmp_path / "state" / "state.json"))

    rc = publish.run()
    assert rc == 0
    assert [t for t in client.posted]  # posted at least one
    # PER_RUN_CAP = 2 -> posts exactly 2 items
    assert len(client.posted) == 2
    assert "First" in client.posted[0]
    assert "Second" in client.posted[1]

    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 1  # Third still queued
    assert len(q["posted"]) == 2
    st = json.loads((tmp_path / "state" / "state.json").read_text(encoding="utf-8"))
    assert st["counts"]["2026-09-29"] == 2


def test_publish_empty_queue(iso_cwd, tmp_path):
    rc = publish.run()
    assert rc == 0


def test_publish_daily_cap_stops(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "today_key", lambda: "2026-09-29")
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)

    client = RecordingClient()
    monkeypatch.setattr(P, "build_client", lambda: client)
    seed = {"pending": [mk_item(id="1", title="A")], "posted": []}
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    # already hit the daily cap
    state_mod.save({"seen": {}, "history": [],
                    "counts": {"2026-09-29": P.DAILY_CAP}},
                   str(tmp_path / "state" / "queue.json").replace("queue", "state"))
    rc = publish.run()
    assert rc == 0
    assert client.posted == []
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 1  # untouched


def test_publish_missing_credentials_returns_1(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "today_key", lambda: "2026-09-29")

    def raise_missing():
        raise ValueError("LINKEDIN_TOKEN and LINKEDIN_ORG_URN are required")

    monkeypatch.setattr(P, "build_client", raise_missing)
    seed = {"pending": [mk_item(id="1", title="A")], "posted": []}
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    state_mod.save({"seen": {}, "history": [], "counts": {}},
                   str(tmp_path / "state" / "state.json"))
    assert publish.run() == 1
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 1  # creds missing -> run aborted before post


def test_publish_retryable_error_keeps_item_and_stops(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "today_key", lambda: "2026-09-29")
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    # fail with a retryable error immediately -> back off, item stays queued
    client = RecordingClient(fail_retry=True)
    monkeypatch.setattr(P, "build_client", lambda: client)
    seed = {"pending": [mk_item(id="1", title="A")], "posted": []}
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    state_mod.save({"seen": {}, "history": [], "counts": {}},
                   str(tmp_path / "state" / "state.json"))
    rc = publish.run()
    assert rc == 0  # transient -> graceful stop, not error
    assert client.posted == []
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 1  # item NOT dropped (will retry next run)


def test_publish_linkedin_error_drops_item(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "today_key", lambda: "2026-09-29")
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    client = RecordingClient(fail_fatal=True)
    monkeypatch.setattr(P, "build_client", lambda: client)
    seed = {
        "pending": [
            mk_item(id="bad", title="Bad"),
            mk_item(id="good", title="Good", link="https://x/2"),
        ],
        "posted": [],
    }
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    state_mod.save({"seen": {}, "history": [], "counts": {}},
                   str(tmp_path / "state" / "state.json"))
    rc = publish.run()
    assert rc == 0
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    # permanent failure drops the bad item; good item processed (and posted)
    ids = [r["id"] for r in q["pending"]]
    assert "bad" not in ids
    assert any("Good" in t for t in client.posted)


# --- dry-run ----------------------------------------------------------------


def test_publish_dry_run_posts_nothing_and_does_not_write(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "today_key", lambda: "2026-09-29")
    called = {"build_client": False}
    monkeypatch.setattr(
        P, "build_client", lambda: called.__setitem__("build_client", True) or RecordingClient()
    )
    seed = {
        "pending": [mk_item(id="1", title="One"), mk_item(id="2", title="Two")],
        "posted": [],
    }
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    state_mod.save({"seen": {}, "history": [], "counts": {}},
                   str(tmp_path / "state" / "state.json"))

    rc = publish.run(dry_run=True)
    assert rc == 0
    assert called["build_client"] is False  # no backend needed for a preview
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 2  # untouched
    assert q["posted"] == []
    st = json.loads((tmp_path / "state" / "state.json").read_text(encoding="utf-8"))
    assert st["counts"] == {}


def test_publish_dry_run_respects_daily_cap(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "today_key", lambda: "2026-09-29")
    seed = {"pending": [mk_item(id="1", title="A")], "posted": []}
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    state_mod.save({"seen": {}, "history": [], "counts": {
        "2026-09-29": P.DAILY_CAP}}, str(tmp_path / "state" / "state.json"))
    # dry-run still short-circuits on the daily cap (nothing to preview)
    assert publish.run(dry_run=True) == 0


def test_publish_main_cli_routes_dry_run(iso_cwd, tmp_path, monkeypatch):
    """`python publish.py --dry-run` (and the console script) route to dry-run."""
    monkeypatch.setattr(P, "today_key", lambda: "2026-09-29")
    called = {"build_client": False}
    monkeypatch.setattr(
        P, "build_client", lambda: called.__setitem__("build_client", True) or RecordingClient()
    )
    seed = {"pending": [mk_item(id="1", title="One")], "posted": []}
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    state_mod.save({"seen": {}, "history": [], "counts": {}},
                   str(tmp_path / "state" / "state.json"))

    rc = publish.main(["--dry-run"])
    assert rc == 0
    assert called["build_client"] is False
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 1  # untouched