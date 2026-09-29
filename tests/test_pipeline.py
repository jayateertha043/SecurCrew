"""Tests for pipeline.py: shared config, feed parsing, rendering, clipping."""

from __future__ import annotations

import calendar
import time

import feedparser
import pytest

import pipeline as P

# --- read_feeds -------------------------------------------------------------


def test_read_feeds_parses_url_and_tags(tmp_path):
    f = tmp_path / "feeds.txt"
    f.write_text(
        "# comment\n\n"
        "https://feed.example.com/a #vuln #0day\n"
        "https://feed.example.com/b\n"
    , encoding="utf-8")
    feeds = P.read_feeds(str(f))
    assert feeds == [
        ("https://feed.example.com/a", ["#vuln", "#0day"]),
        ("https://feed.example.com/b", []),
    ]


def test_read_feeds_ignores_non_hash_tokens_after_url(tmp_path):
    f = tmp_path / "feeds.txt"
    f.write_text("https://x.example/rss foo bar #tag\n", encoding="utf-8")
    assert P.read_feeds(str(f)) == [("https://x.example/rss", ["#tag"])]


def test_read_feeds_missing_file_returns_empty(tmp_path):
    assert P.read_feeds(str(tmp_path / "missing.txt")) == []


# --- today_key --------------------------------------------------------------


def test_today_key_uses_utc():
    # Fixed epoch -> known UTC date regardless of host timezone.
    assert P.today_key(now=0.0) == "1970-01-01"
    assert P.today_key(now=1700000000.0) == "2023-11-14"


# --- _entry_published (UTC regression) ---------------------------------------


def _utc_struct(epoch):
    return time.gmtime(epoch)


def test_entry_published_timegm_utc_regression():
    """feedparser publishes are UTC; must convert with timegm, not mktime.

    The bug (original code used time.mktime) shifted timestamps by the host
    UTC offset on non-UTC machines — e.g. a Warsaw host reported this epoch an
    hour early, which pushed items out of the site's 3-day window and mis-
    ordered 'newest first' selection.
    """
    epoch = 1700000000
    entry = {"published_parsed": _utc_struct(epoch)}
    assert P._entry_published(entry) == pytest.approx(epoch, abs=1e-6)
    # sanity: confirm timegm agrees with the struct we built
    assert calendar.timegm(_utc_struct(epoch)) == epoch


def test_entry_published_falls_back_to_updated():
    epoch = 1600000000
    entry = {"updated_parsed": _utc_struct(epoch)}
    assert P._entry_published(entry) == pytest.approx(epoch, abs=1e-6)


def test_entry_published_prefers_published_over_updated():
    entry = {
        "published_parsed": _utc_struct(1500000000),
        "updated_parsed": _utc_struct(1600000000),
    }
    assert P._entry_published(entry) == pytest.approx(1500000000, abs=1e-6)


def test_entry_published_handles_missing_and_bad():
    assert P._entry_published({}) == 0.0
    assert P._entry_published({"published_parsed": None}) == 0.0
    assert P._entry_published({"published_parsed": "garbage"}) == 0.0  # raises -> skip
    assert P._entry_published({"updated_parsed": [1, 2]}) == 0.0


# --- clip -------------------------------------------------------------------


def test_clip_short_text_unchanged():
    assert P.clip("short text") == "short text"


def test_clip_trims_on_word_boundary_with_ellipsis():
    out = P.clip("Lorem ipsum dolor sit amet consectetur", limit=12)
    assert out.endswith("…")
    assert len(out) <= 13  # within budget + ellipsis
    assert "dolor" not in out  # cut on a word boundary, no partial word


def test_clip_collapses_whitespace():
    assert P.clip("  a   b\n c ") == "a b c"


# --- render_post -------------------------------------------------------------


def test_render_post_full():
    text = P.render_post({
        "title": "Big Bug",
        "summary": "A short summary.",
        "source": "Example",
        "link": "https://x/y",
        "tags": ["#vuln"],
    })
    lines = text.split("\n")
    assert lines[0] == "Big Bug"
    assert "A short summary." in text
    assert "Source: Example" in text
    assert "https://x/y" in text


def test_render_post_without_source_uses_link_as_attribution():
    text = P.render_post({
        "title": "T", "summary": "", "source": "",
        "link": "https://x/y", "tags": [],
    })
    assert "Source: https://x/y" in text


def test_render_post_strips_empty_parts():
    text = P.render_post({"title": "Only Title", "link": "https://x", "source": "", "tags": []})
    lines = [l for l in text.split("\n") if l.strip()]
    assert lines[0] == "Only Title"
    assert "Source: https://x" in lines[1]


# --- hashtags ----------------------------------------------------------------


def test_hashtags_merges_base_and_feed_tags_deduped():
    assert P._hashtags(["#vuln", "#infosec"]) == "#infosec #cybersecurity #bugbounty #vuln"


def test_hashtags_case_insensitive_dedupe():
    assert P._hashtags(["#Infosec"]) == "#infosec #cybersecurity #bugbounty"


def test_hashtags_none_ok():
    assert P._hashtags(None) == "#infosec #cybersecurity #bugbounty"


# --- _parse_feed / collect_entries --------------------------------------------


def test_parse_feed_success(monkeypatch):
    calls = {}

    class FakeResp:
        status_code = 200
        content = b'<rss><channel><title>Src</title></channel></rss>'
        def raise_for_status(self):
            return None

    def fake_get(url, **kw):
        calls["get"] = url
        return FakeResp()

    monkeypatch.setattr(P.requests, "get", fake_get)
    parsed = P._parse_feed("https://f/x")
    assert calls["get"] == "https://f/x"
    assert parsed.feed.get("title") == "Src"


def test_parse_feed_network_failure_falls_back_to_feedparser(monkeypatch):
    def boom(url, **kw):
        raise P.requests.RequestException("down")
    monkeypatch.setattr(P.requests, "get", boom)
    parsed = P._parse_feed("https://f/x")  # feedparser fallback simply yields empty
    assert parsed is not None


def test_collect_entries_skips_erroring_feed(monkeypatch):
    def fake_parse(url):
        raise RuntimeError("boom")
    monkeypatch.setattr(P, "_parse_feed", fake_parse)
    assert P.collect_entries([]) == []


def test_collect_entries_skips_bozo_without_entries(monkeypatch):
    class _DummyFeed:
        def create_entry(self, link, title):
            return None
    # build a dummy parsed object by wrapping feedparser.FeedParserDict
    parsed = feedparser.FeedParserDict()
    parsed.bozo = 1
    parsed.entries = []
    parsed.feed = feedparser.FeedParserDict()
    monkeypatch.setattr(P, "_parse_feed", lambda url: parsed)
    assert P.collect_entries([("https://f", [])]) == []


def test_collect_entries_flattens_fields(monkeypatch):
    key = {}

    def fake_parse(url):
        fb = feedparser.FeedParserDict
        parsed = fb()
        parsed.bozo = 0
        parsed.feed = fb(title="Source &amp; Co", link="https://f/feed")
        e = fb()
        e["link"] = "  https://f/story  "
        e["title"] = "  A &amp; B story  "
        e["summary"] = "Body here"
        e["published_parsed"] = time.gmtime(1700000000)
        parsed.entries = [e]
        key["called"] = url
        return parsed

    monkeypatch.setattr(P, "_parse_feed", fake_parse)
    items = P.collect_entries([("https://f/feed", ["#tag"])])
    assert len(items) == 1
    it = items[0]
    assert it["link"] == "https://f/story"
    assert it["title"] == "A & B story"          # html.unescape
    assert it["summary"] == "Body here"
    assert it["source"] == "Source & Co"          # html.unescape
    assert it["published"] == pytest.approx(1700000000, abs=1e-6)
    assert it["tags"] == ["#tag"]


def test_collect_entries_fallback_source_from_netloc(monkeypatch):
    from feedparser import FeedParserDict as fb

    def fake_parse(url):
        parsed = fb()
        parsed.bozo = 0
        parsed.feed = fb(title="")
        e = fb()
        e["link"] = "https://sub.example.com/a"
        e["title"] = "T"
        parsed.entries = [e]
        return parsed

    monkeypatch.setattr(P, "_parse_feed", fake_parse)
    items = P.collect_entries([("https://sub.example.com/feed", [])])
    assert items[0]["source"] == "sub.example.com"


def test_collect_entries_drops_missing_link_or_title(monkeypatch):
    from feedparser import FeedParserDict as fb

    def fake_parse(url):
        parsed = fb()
        parsed.bozo = 0
        parsed.feed = fb(title="S")
        good = fb()
        good["link"] = "https://x/1"; good["title"] = "T"
        no_link = fb()
        no_link["title"] = "No link"
        no_title = fb()
        no_title["link"] = "https://x/3"
        parsed.entries = [good, no_link, no_title]
        return parsed

    monkeypatch.setattr(P, "_parse_feed", fake_parse)
    items = P.collect_entries([("https://f", [])])
    assert [i["link"] for i in items] == ["https://x/1"]