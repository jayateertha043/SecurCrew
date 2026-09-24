"""Collector phase: aggregate feeds, dedup, pick the original, summarize, enqueue.

Deduplication is layered for cost and reliability:
  1. Exact  - SHA-1 of the link (already seen -> skip).
  2. Fuzzy  - rapidfuzz clusters reposts of the same story across feeds.
  3. Original selection - within a cluster the earliest-published item wins, so
     we queue the source that broke the story rather than a syndicated copy.

AI is used only to write the 2-3 line summary (one batched call), which is far
cheaper and more deterministic than asking an LLM to dedup hundreds of items.
"""

from __future__ import annotations

import time
from typing import Dict, List

import dedup
import pipeline as P
import queue_store
import site_data
import state as state_mod
from summarize import Summarizer

log = P.log


def _sort_key(item: Dict[str, object]):
    """Known publish dates first (ascending) so the original wins; unknown last."""
    published = float(item.get("published", 0) or 0)
    return (published == 0, published)


def select_originals(
    entries: List[Dict[str, object]], st: Dict, already_queued: set
) -> List[Dict[str, object]]:
    """Return new, deduplicated 'original' items ready to enqueue."""
    originals: List[Dict[str, object]] = []
    run_norms: List[str] = []

    for item in sorted(entries, key=_sort_key):
        if len(originals) >= P.MAX_ENQUEUE_PER_RUN:
            break

        link = str(item["link"])
        item_id = dedup.link_hash(link)
        if item_id in already_queued:
            continue
        if dedup.is_exact_dup(link, st):
            continue

        norm = dedup.normalize(str(item["title"]), str(item.get("summary", "")))

        # Duplicate of something posted recently, or of an earlier original this run.
        if dedup.is_fuzzy_dup(norm, st, P.SIMILARITY_THRESHOLD) or \
                dedup.is_similar_to_any(norm, run_norms, P.SIMILARITY_THRESHOLD):
            # Mark seen so later feeds' copies are skipped without re-evaluating.
            dedup.record_posted(link, norm, st)
            continue

        run_norms.append(norm)
        item["_id"] = item_id
        item["_norm"] = norm
        originals.append(item)

    return originals


def run() -> int:
    st = state_mod.load()
    state_mod.prune(st, P.PRUNE_WINDOW_DAYS)
    q = queue_store.load()
    queue_store.prune(q, P.PRUNE_WINDOW_DAYS, P.QUEUE_TTL_DAYS)

    entries = P.collect_entries(P.read_feeds())
    originals = select_originals(entries, st, queue_store.pending_ids(q))
    log.info("fuzzy pass -> %d candidate original(s)", len(originals))

    if not originals:
        state_mod.save(st)
        queue_store.save(q)
        return 0

    summarizer = Summarizer.from_env() if P.USE_AI_SUMMARY else None
    log.info("AI: %s", "on" if summarizer else "off (fuzzy-only + clipping)")

    # AI clustering pass: collapse paraphrased reposts fuzzy matching misses.
    # Keep the earliest-published item per group; mark the rest as seen dupes.
    if summarizer:
        groups = summarizer.cluster_duplicates(originals)
        if groups is None:
            log.warning("AI clustering failed; keeping fuzzy result")
        elif len(groups) < len(originals):
            kept: List[Dict[str, object]] = []
            for grp in groups:
                members = [originals[i] for i in grp]
                canonical = min(members, key=_sort_key)
                kept.append(canonical)
                for m in members:
                    if m is not canonical:
                        dedup.record_posted(str(m["link"]), str(m["_norm"]), st)
            log.info("AI clustering -> %d original(s) (merged %d dupes)",
                     len(kept), len(originals) - len(kept))
            originals = kept

    summaries = summarizer.summarize_batch(originals) if summarizer else None
    if summarizer and summaries is None:
        log.warning("AI summarize failed; falling back to clipping")

    now = time.time()
    for i, item in enumerate(originals):
        if summaries:
            summary = summaries[i]
        else:
            summary = P.clip(str(item.get("summary", "")))

        q["pending"].append(
            {
                "id": item["_id"],
                "title": item["title"],
                "link": item["link"],
                "summary": summary,
                "source": item.get("source", ""),
                "published": item.get("published", 0),
                "tags": item.get("tags", []),
                "added_at": now,
            }
        )
        # Mark seen now so re-runs before publishing don't re-enqueue it.
        dedup.record_posted(str(item["link"]), str(item["_norm"]), st)

    log.info("queue now holds %d pending item(s)", len(q["pending"]))
    state_mod.save(st)
    queue_store.save(q)
    site_data.write(q)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(run())
