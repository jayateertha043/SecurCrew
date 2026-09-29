"""Tests for collect.py: feed aggregation -> dedup -> original selection -> enqueue."""

from __future__ import annotations

import json

import collect
import dedup
import pipeline as P
import queue_store
from tests.conftest import item as mk_item


def _st():
    return {"seen": {}, "history": []}


def test_select_originals_exact_dup_skipped_and_budget_enforced(monkeypatch):
    monkeypatch.setattr(P, "MAX_ENQUEUE_PER_RUN", 2)
    st = _st()
    entries = [
        {"link": "https://x/1", "title": "one", "summary": "", "published": 30},
        {"link": "https://x/2", "title": "two", "summary": "", "published": 20},
        {"link": "https://x/3", "title": "three", "summary": "", "published": 10},
    ]
    already = set()
    originals = collect.select_originals(entries, st, already)
    assert len(originals) == 2  # capped
    assert [o["link"] for o in originals] == ["https://x/1", "https://x/2"]


def test_select_originals_newest_first():
    st = _st()
    entries = [
        {"link": "https://x/a", "title": "A", "summary": "", "published": 100},
        {"link": "https://x/b", "title": "B", "summary": "", "published": 300},
        {"link": "https://x/c", "title": "C", "summary": "", "published": 200},
    ]
    originals = collect.select_originals(entries, st, set())
    assert [o["link"] for o in originals] == ["https://x/b", "https://x/c", "https://x/a"]


def test_select_originals_already_queued_skipped():
    st = _st()
    entries = [
        {"link": "https://x/v", "title": "V", "summary": "", "published": 50}
    ]
    # pre-seed seen so the exact-dup check also catches it
    st["seen"][__import__("dedup").link_hash("https://x/v")] = 1
    originals = collect.select_originals(entries, st, set())
    assert originals == []


def test_select_originals_fuzzy_dup_against_history_skipped_and_recorded():
    st = _st()
    # history contains a near-identical normalized title
    st["history"].append({"ts": 1, "norm": "microsoft patches critical zero day"})
    entries = [
        {"link": "https://x/z", "title": "Microsoft patches critical zero day flaw",
         "summary": "", "published": 10}
    ]
    originals = collect.select_originals(entries, st, set())
    assert originals == []
    # the dup is recorded so later feeds' copies are skipped cheaply
    assert __import__("dedup").link_hash("https://x/z") in st["seen"]


def test_select_originals_similar_within_run_merged():
    st = _st()
    entries = [
        {"link": "https://x/1", "title": "Ransomware hits hospital network",
         "summary": "", "published": 200},
        {"link": "https://x/2", "title": "Ransomware hits another hospital network",
         "summary": "", "published": 100},  # earlier but near-identical -> dropped
    ]
    originals = collect.select_originals(entries, st, set())
    assert [o["link"] for o in originals] == ["https://x/1"]


def test_select_originals_undated_sorts_last():
    st = _st()
    entries = [
        {"link": "https://x/undated", "title": "U", "summary": "", "published": 0},
        {"link": "https://x/dated", "title": "D", "summary": "", "published": 5},
    ]
    originals = collect.select_originals(entries, st, set())
    assert [o["link"] for o in originals] == ["https://x/dated", "https://x/undated"]


def test_run_enqueues_and_persists(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "USE_AI_SUMMARY", False)
    monkeypatch.setattr(P, "read_feeds", lambda: [("https://f", [])])
    monkeypatch.setattr(
        P,
        "collect_entries",
        lambda feeds: [
            {"link": "https://x/new", "title": "Fresh CVE", "summary": "body",
             "source": "Src", "published": 100, "tags": []}
        ],
    )

    rc = collect.run()
    assert rc == 0

    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 1
    rec = q["pending"][0]
    assert rec["title"] == "Fresh CVE"
    assert rec["ai"] is False
    assert rec["added_at"] > 0

    st = json.loads((tmp_path / "state" / "state.json").read_text(encoding="utf-8"))
    # item marked seen so re-runs don't re-enqueue
    assert __import__("dedup").link_hash("https://x/new") in st["seen"]


def test_run_empty_returns_zero(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "USE_AI_SUMMARY", False)
    monkeypatch.setattr(P, "read_feeds", lambda: [("https://f", [])])
    monkeypatch.setattr(P, "collect_entries", lambda feeds: [])
    assert collect.run() == 0
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert q["pending"] == []


def test_run_skips_already_pending(iso_cwd, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "USE_AI_SUMMARY", False)
    monkeypatch.setattr(P, "read_feeds", lambda: [("https://f", [])])
    link = "https://x/dup"
    monkeypatch.setattr(
        P, "collect_entries", lambda feeds: [
            {"link": link, "title": "Dup", "summary": "", "source": "S",
             "published": 100, "tags": []}
        ],
    )
    # pre-seed a queued item with the same link (its id is the link sha1)
    seed = {"pending": [mk_item(id=dedup.link_hash(link), link=link)], "posted": []}
    queue_store.save(seed, str(tmp_path / "state" / "queue.json"))
    collect.run()
    q = json.loads((tmp_path / "state" / "queue.json").read_text(encoding="utf-8"))
    assert len(q["pending"]) == 1  # not duplicated