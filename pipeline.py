"""Shared configuration and helpers for the collect/publish pipeline.

The bot is split into two phases that communicate through ``state/queue.json``:

    collect.py  -> aggregate feeds, dedup, pick the original, summarize, enqueue
    publish.py  -> drain the queue at a human pace and post one story per item

Both import their tunables and shared utilities from here.
"""

from __future__ import annotations

import html
import logging
import os
import sys
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import feedparser
import requests

from linkedin import LinkedInClient
from linkedin_webhook import WebhookClient

# --- Tunables (all knobs live here) -----------------------------------------
FEEDS_FILE = "feeds.txt"
SIMILARITY_THRESHOLD = 85        # fuzzy-dup ratio (0-100) for clustering reposts
PER_RUN_CAP = 2                  # max posts published in a single publish run
DAILY_CAP = 20                   # posts per UTC day (queue holds the rest)
DELAY_RANGE = (45.0, 120.0)      # randomized human-like delay between posts (s)
PRUNE_WINDOW_DAYS = 7            # drop seen/history/counts + posted log older than this
QUEUE_TTL_DAYS = 2               # discard queued-but-unposted items older than this (stale news)
MAX_ENTRIES_PER_FEED = 40        # look deeper per feed since we collect only ~2x/day
MAX_ENQUEUE_PER_RUN = 60         # cap items added to the queue in one collect run
BASE_HASHTAGS = "#infosec #cybersecurity #bugbounty"
SUMMARY_MAX_CHARS = 220          # fallback (non-AI) summary length

# AI summaries: on when an AI_API_KEY is present; disable with USE_AI_SUMMARY=0.
USE_AI_SUMMARY = os.environ.get("USE_AI_SUMMARY", "1").strip().lower() not in {
    "0", "false", "no"
}
# Posting backend: "api" (direct LinkedIn org API) or "webhook" (Zapier/Make/n8n).
POST_BACKEND = os.environ.get("POST_BACKEND", "api").strip().lower()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("securcrew")


def today_key(now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def read_feeds(path: str = FEEDS_FILE) -> List[Tuple[str, List[str]]]:
    """Return (url, tags) pairs, ignoring blanks and ``#`` comment lines.

    Line format: ``<url> [#tag1 #tag2 ...]`` — tokens after the URL that start
    with ``#`` are per-feed hashtags appended to posts for that feed.
    """
    feeds: List[Tuple[str, List[str]]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                url = parts[0]
                tags = [t for t in parts[1:] if t.startswith("#")]
                feeds.append((url, tags))
    except FileNotFoundError:
        log.error("feeds file not found: %s", path)
    return feeds


def _entry_published(entry) -> float:
    """Best-effort epoch of an entry's publish time; 0 if unknown."""
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return time.mktime(parsed)
            except (TypeError, ValueError, OverflowError):
                continue
    return 0.0


# Browser-like UA + Accept so feeds behind anti-bot/CDN don't 403 the runner.
_FEED_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_FEED_HEADERS = {
    "User-Agent": _FEED_UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
}


def _parse_feed(url: str):
    """Fetch a feed with a real UA and redirect-following, then parse.

    Falls back to feedparser's own fetch if the HTTP request fails.
    """
    try:
        resp = requests.get(
            url, headers=_FEED_HEADERS, timeout=20, allow_redirects=True
        )
        resp.raise_for_status()
        return feedparser.parse(resp.content)
    except requests.RequestException:
        return feedparser.parse(url, agent=_FEED_UA)


def collect_entries(feeds: List[Tuple[str, List[str]]]) -> List[Dict[str, object]]:
    """Fetch and flatten entries from every feed. Erroring feeds are skipped."""
    items: List[Dict[str, object]] = []
    for url, tags in feeds:
        try:
            parsed = _parse_feed(url)
        except Exception as exc:  # never let one feed kill the run
            log.warning("feed error (%s): %s", url, exc)
            continue
        if parsed.bozo and not parsed.entries:
            log.warning("feed unreadable, skipping: %s", url)
            continue

        source = html.unescape((parsed.feed.get("title") or "").strip())
        if not source:
            source = urlparse(url).netloc.replace("www.", "") or url
        for entry in parsed.entries[:MAX_ENTRIES_PER_FEED]:
            link = (entry.get("link") or "").strip()
            title = html.unescape((entry.get("title") or "").strip())
            summary = html.unescape((entry.get("summary") or "").strip())
            if link and title:
                items.append(
                    {
                        "link": link,
                        "title": title,
                        "summary": summary,
                        "source": source,
                        "published": _entry_published(entry),
                        "tags": tags,
                    }
                )
    log.info("collected %d entries from %d feeds", len(items), len(feeds))
    return items


def clip(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    """Trim to ``limit`` chars on a word boundary, adding an ellipsis."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip() + "…"


def render_post(item: Dict[str, object]) -> str:
    """One story per post: title, 2-3 line summary, source attribution, tags."""
    title = str(item.get("title", "")).strip()
    link = str(item.get("link", "")).strip()
    summary = str(item.get("summary", "")).strip()
    source = str(item.get("source", "")).strip()

    parts = [title]
    if summary:
        parts.append("")
        parts.append(summary)
    parts.append("")
    attribution = f"Source: {source} — {link}" if source else f"Source: {link}"
    parts.append(attribution)
    parts.append("")
    parts.append(_hashtags(item.get("tags")))
    return "\n".join(parts)


def _hashtags(feed_tags: object) -> str:
    """Merge base hashtags with per-feed tags, de-duplicated, order preserved."""
    seen = set()
    out: List[str] = []
    for tag in BASE_HASHTAGS.split() + list(feed_tags or []):
        key = tag.lower()
        if tag.startswith("#") and key not in seen:
            seen.add(key)
            out.append(tag)
    return " ".join(out)


def build_client():
    """Instantiate the posting backend selected by ``POST_BACKEND``.

    Both clients expose the same ``post(text)`` contract and raise
    ``RetryableError`` / ``LinkedInError``, so callers are backend-agnostic.
    """
    if POST_BACKEND == "webhook":
        return WebhookClient(os.environ.get("WEBHOOK_URL", ""))
    return LinkedInClient(
        os.environ.get("LINKEDIN_TOKEN", ""),
        os.environ.get("LINKEDIN_ORG_URN", ""),
    )
