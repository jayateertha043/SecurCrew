"""Shared fixtures for the SecurCrew test suite.

The library is written against *relative* paths (``state/state.json``,
``docs/data/items.json``) and the process CWD, so every run-level test changes
into a throwaway ``tmp_path`` directory. ``load()``/``save()``/``prune()`` and
``site_data.write()`` then touch the tmp tree instead of the committed state —
keeping the real ``state/`` and ``docs/`` pristine.
"""

from __future__ import annotations

import time

import pytest

import queue_store
import state as state_mod


@pytest.fixture
def iso_cwd(tmp_path, monkeypatch):
    """chdir into tmp so relative state/queue/site writes stay sandboxed."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


def seed_state(tmp_path, *, seen=None, history=None, counts=None):
    """Write a state.json into the (already chdir'd) tmp dir."""
    data = {
        "seen": seen or {},
        "history": history if history is not None else [],
        "counts": counts or {},
    }
    state_mod.save(data, str(tmp_path / "state" / "state.json"))
    return data


def seed_queue(tmp_path, *, pending=None, posted=None):
    """Write a queue.json into the (already chdir'd) tmp dir and return it."""
    data = {"pending": pending or [], "posted": posted or []}
    queue_store.save(data, str(tmp_path / "state" / "queue.json"))
    return data


def item(**kw) -> dict:
    """Build a minimal queue/pending record with sane defaults.

    ``added_at`` defaults to "now" so ``prune`` (which drops pending items older
    than ``QUEUE_TTL_DAYS``) treats a seeded queue as fresh rather than stale.
    """
    base = {
        "id": kw.pop("id", "abc123"),
        "title": kw.pop("title", "Some infosec story"),
        "link": kw.pop("link", "https://example.com/story"),
        "summary": kw.pop("summary", "A short summary."),
        "source": kw.pop("source", "Example Feed"),
        "published": kw.pop("published", 0.0),
        "tags": kw.pop("tags", ["#infosec"]),
        "ai": kw.pop("ai", False),
        "added_at": kw.pop("added_at", time.time()),
    }
    base.update(kw)
    return base


class RecordingClient:
    """Fake posting backend: records posts, optionally fails in configured ways."""

    def __init__(self, *, fail_retry=False, fail_fatal=False):
        self.posted: list[str] = []
        self.fail_retry = fail_retry
        self.fail_fatal = fail_fatal

    def post(self, text: str) -> None:
        if self.fail_retry:
            from linkedin import RetryableError

            self.fail_retry = False  # retryable once, then success
            raise RetryableError("transient 429")
        if self.fail_fatal:
            from linkedin import LinkedInError

            self.fail_fatal = False  # fatal once (first item), then success
            raise LinkedInError("permanent 400")
        self.posted.append(text)