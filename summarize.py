"""Optional AI summarizer for digest items (provider-agnostic, fail-soft).

Uses any OpenAI-compatible Chat Completions endpoint, so it works with free
providers like Groq, GitHub Models, or Google Gemini's OpenAI-compat API by
just changing ``AI_BASE_URL`` / ``AI_MODEL``. All items in a digest are
summarized in a single request to conserve rate limits.

Configuration (env vars, read by ``Summarizer.from_env``):
    AI_API_KEY   - provider API key (required to enable summaries)
    AI_BASE_URL  - OpenAI-compatible base, default Groq
    AI_MODEL     - model name, default a small fast Groq model

If the key is missing or the call fails, callers fall back to plain clipping;
summarization must never crash a run.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import List, Optional

import requests

log = logging.getLogger("securcrew")

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.1-8b-instant"
REQUEST_TIMEOUT = 45
SUMMARY_CHUNK = 20  # summarize at most this many items per request for reliability

_SYSTEM_PROMPT = (
    "You are a cybersecurity news editor. Summarize each item in 2-3 short, "
    "factual lines suitable for a LinkedIn company page. No hype, no emojis, "
    "no hashtags. Return ONLY a JSON array of strings, one summary per item, "
    "in the same order."
)

_CLUSTER_PROMPT = (
    "You deduplicate cybersecurity news. Decide which items describe the same "
    "underlying story/event. Output ONLY a JSON array of arrays of 0-based "
    "indices; each index must appear exactly once, and items in the same group "
    "are the same story."
)


class Summarizer:
    """Batch-summarizes items via an OpenAI-compatible chat endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    @classmethod
    def from_env(cls) -> Optional["Summarizer"]:
        """Build from env, or return None if no API key is configured."""
        key = os.environ.get("AI_API_KEY", "").strip()
        if not key:
            return None
        base = os.environ.get("AI_BASE_URL", DEFAULT_BASE_URL).strip()
        model = os.environ.get("AI_MODEL", DEFAULT_MODEL).strip()
        log.info("AI provider: %s | model: %s", base, model)
        return cls(key, base, model)

    def summarize_batch(self, items: List[dict]) -> Optional[List[str]]:
        """Return one summary per item, or None on any failure.

        Large batches are chunked so each request stays small and reliable; a
        None return signals the caller to fall back to plain clipping.
        """
        out: List[str] = []
        for start in range(0, len(items), SUMMARY_CHUNK):
            chunk = items[start:start + SUMMARY_CHUNK]
            part = self._summarize_chunk(chunk)
            if part is None:
                return None
            out.extend(part)
        return out

    def _summarize_chunk(self, items: List[dict]) -> Optional[List[str]]:
        """Summarize a single small batch of items."""
        payload_items = [
            {"title": it.get("title", ""), "text": it.get("summary", "")}
            for it in items
        ]
        user_msg = (
            "Summarize these items. Return a JSON array of "
            f"{len(payload_items)} strings.\n\n"
            + json.dumps(payload_items, ensure_ascii=False)
        )
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.3,
        }

        content = self._chat(body)
        if content is None:
            return None
        summaries = _parse_json_array(content)
        if summaries is None or len(summaries) != len(items):
            log.warning(
                "AI 200 but unparseable/mismatched (%s items, got %s) | %s",
                len(items),
                "None" if summaries is None else len(summaries),
                content[:200],
            )
            return None
        return summaries

    def cluster_duplicates(self, items: List[dict]) -> Optional[List[List[int]]]:
        """Group items that report the same underlying story.

        Returns a list of groups, each a list of 0-based indices, covering every
        item exactly once. Returns None on any failure so the caller can fall
        back to treating each item as its own story.
        """
        if len(items) < 2:
            return [[i] for i in range(len(items))]

        payload_items = [
            {"i": idx, "title": it.get("title", ""), "text": it.get("summary", "")}
            for idx, it in enumerate(items)
        ]
        user_msg = (
            "Group items that report the SAME underlying story or event "
            "(same incident, CVE, breach, or disclosure), even if worded "
            "differently. Return ONLY a JSON array of arrays of 0-based indices; "
            f"every index 0..{len(items) - 1} must appear exactly once.\n\n"
            + json.dumps(payload_items, ensure_ascii=False)
        )
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _CLUSTER_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.0,
        }

        content = self._chat(body)
        if content is None:
            return None
        return _parse_groups(content, len(items))

    def _chat(self, body: dict) -> Optional[str]:
        """POST a chat-completions request; return message content or None."""
        try:
            resp = self._session.post(self._url, json=body, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                log.warning(
                    "AI call failed: HTTP %s from %s | %s",
                    resp.status_code, self._url, (resp.text or "")[:200],
                )
                return None
            return resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            log.warning("AI call error at %s: %s", self._url, exc)
            return None



def _parse_json_array(content: str) -> Optional[List[str]]:
    """Extract a JSON array of strings from a model response, tolerantly."""
    content = content.strip()
    # Strip common ```json ... ``` fences if present.
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", content).strip()
    try:
        data = json.loads(content)
    except ValueError:
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None
    if isinstance(data, list) and all(isinstance(x, str) for x in data):
        return [x.strip() for x in data]
    return None


def _parse_groups(content: str, n: int) -> Optional[List[List[int]]]:
    """Parse a JSON array-of-arrays of indices; validate full coverage of 0..n-1."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", content).strip()
    try:
        data = json.loads(content)
    except ValueError:
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return None

    if not isinstance(data, list):
        return None
    groups: List[List[int]] = []
    seen = set()
    for grp in data:
        if not isinstance(grp, list):
            return None
        ints = []
        for x in grp:
            if not isinstance(x, int) or x < 0 or x >= n or x in seen:
                return None
            seen.add(x)
            ints.append(x)
        if ints:
            groups.append(ints)
    if seen != set(range(n)):
        return None
    return groups

