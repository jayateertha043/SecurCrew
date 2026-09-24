"""Deduplication: exact (SHA-1 of link) and fuzzy (normalized text similarity).

Fuzzy matching normalizes title + description (lowercase, strip URLs,
punctuation, and stopwords) and compares against recently posted items using
``rapidfuzz.fuzz.token_set_ratio``.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, Iterable, List

from rapidfuzz import fuzz

# Small, high-frequency stopword set — enough to stop them dominating the ratio.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "have", "in", "is", "it", "its", "of", "on", "or", "that", "the", "to",
    "was", "were", "will", "with", "new", "how", "why", "what",
}

_URL_RE = re.compile(r"https?://\S+")
_NON_WORD_RE = re.compile(r"[^a-z0-9\s]")
_WS_RE = re.compile(r"\s+")


def link_hash(link: str) -> str:
    """Stable SHA-1 hex digest of an entry link for exact dedup."""
    return hashlib.sha1(link.strip().encode("utf-8")).hexdigest()


def normalize(*parts: str) -> str:
    """Lowercase, drop URLs/punctuation/stopwords; return a token string."""
    text = " ".join(p for p in parts if p)
    text = text.lower()
    text = _URL_RE.sub(" ", text)
    text = _NON_WORD_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    tokens = [t for t in text.split(" ") if t and t not in _STOPWORDS]
    return " ".join(tokens)


def is_exact_dup(link: str, state: Dict[str, Any]) -> bool:
    """True if this link's hash was already seen."""
    return link_hash(link) in state["seen"]


def is_fuzzy_dup(norm_text: str, state: Dict[str, Any], threshold: int) -> bool:
    """True if ``norm_text`` is >= threshold similar to any history record."""
    if not norm_text:
        return False
    for rec in state["history"]:
        other = rec.get("norm", "")
        if other and fuzz.token_set_ratio(norm_text, other) >= threshold:
            return True
    return False


def is_similar_to_any(norm_text: str, norms: Iterable[str], threshold: int) -> bool:
    """True if ``norm_text`` is >= threshold similar to any string in ``norms``."""
    if not norm_text:
        return False
    for other in norms:
        if other and fuzz.token_set_ratio(norm_text, other) >= threshold:
            return True
    return False


def record_posted(
    link: str, norm_text: str, state: Dict[str, Any], now: float | None = None
) -> None:
    """Persist an entry as seen (exact) and remembered (fuzzy)."""
    now = time.time() if now is None else now
    state["seen"][link_hash(link)] = now
    state["history"].append({"ts": now, "norm": norm_text})
