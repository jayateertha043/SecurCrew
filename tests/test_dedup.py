"""Tests for dedup.py: exact (SHA-1) and fuzzy (rapidfuzz) deduplication."""

from __future__ import annotations

import time

import pytest

import dedup


def _state():
    return {"seen": {}, "history": []}


def test_link_hash_stable_and_content_based():
    h1 = dedup.link_hash("https://example.com/abc")
    h2 = dedup.link_hash("https://example.com/abc")
    h3 = dedup.link_hash("https://example.com/xyz")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 40  # sha1 hex


def test_link_hash_strips_whitespace():
    assert dedup.link_hash("  https://example.com/a  ") == dedup.link_hash(
        "https://example.com/a"
    )


def test_normalize_lowercases():
    assert dedup.normalize("Patch Tuesday Log4Shell") == "patch tuesday log4shell"


def test_normalize_strips_urls():
    n = dedup.normalize("see https://evil.example/x?q=1 for details")
    assert "http" not in n
    assert "evil" not in n


def test_normalize_strips_punctuation_and_stopwords():
    n = dedup.normalize("The NEW patch for: 'API' — review the release!")
    assert "patch" in n
    assert "api" in n
    assert "review" in n
    for stop in ("the", "new", "for"):
        assert stop not in n.split()


def test_normalize_multiple_parts():
    n = dedup.normalize("Breach at Corp A", "", "updated details")
    assert n.startswith("breach")


def test_is_exact_dup():
    st = _state()
    assert not dedup.is_exact_dup("https://x/1", st)
    st["seen"][dedup.link_hash("https://x/1")] = 100.0
    assert dedup.is_exact_dup("https://x/1", st)
    assert not dedup.is_exact_dup("https://x/2", st)


def test_is_fuzzy_dup_empty_norm_is_false():
    assert not dedup.is_fuzzy_dup("", {"history": []}, 85)


def test_is_fuzzy_dup_threshold():
    st = {"history": [{"ts": 1, "norm": "critical zero day in nginx"}]}
    # a superset re-statement of the same story should exceed threshold 85
    assert dedup.is_fuzzy_dup("critical zero day in nginx discovered", st, 85)
    # unrelated text should not
    assert not dedup.is_fuzzy_dup("coffee machine firmware update", st, 85)
    # a high threshold rejects even a close (but not identical) match
    assert not dedup.is_fuzzy_dup("nginx zero-day", st, 95)


def test_is_similar_to_any():
    norms = ["patch tuesday microsoft", "ransomware campaign"]
    assert dedup.is_similar_to_any("patch tuesday microsoft", norms, 85)
    assert not dedup.is_similar_to_any("unrelated topic", norms, 85)
    assert not dedup.is_similar_to_any("", norms, 85)


def test_record_posted_adds_seen_and_history():
    st = _state()
    dedup.record_posted("https://x/1", "some norm", st, now=500.0)
    assert dedup.link_hash("https://x/1") in st["seen"]
    assert st["seen"][dedup.link_hash("https://x/1")] == 500.0
    assert st["history"][-1] == {"ts": 500.0, "norm": "some norm"}


def test_record_posted_uses_now_when_not_given():
    st = _state()
    dedup.record_posted("https://x", "norm", st)
    assert st["history"][-1]["ts"] == pytest.approx(time.time(), abs=5)