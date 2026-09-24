"""Publisher phase: drain the queue at a human pace, one story per post.

Pops the oldest pending items, posts each as a single Company Page update
(title + 2-3 line summary + source link + hashtags), and enforces the daily
cap. The per-day counter (shared ``state.json``) only increments on a confirmed
2xx; on 429/5xx the run backs off and stops so items stay queued for next time.
"""

from __future__ import annotations

import random
import time
from typing import Dict

import pipeline as P
import queue_store
import site_data
import state as state_mod
from linkedin import LinkedInError, RetryableError

log = P.log


def run() -> int:
    st = state_mod.load()
    state_mod.prune(st, P.PRUNE_WINDOW_DAYS)
    q = queue_store.load()
    queue_store.prune(q, P.PRUNE_WINDOW_DAYS, P.QUEUE_TTL_DAYS)

    if not q["pending"]:
        log.info("queue empty; nothing to publish")
        state_mod.save(st)
        queue_store.save(q)
        return 0

    day = P.today_key()
    posted_today = st["counts"].get(day, 0)
    remaining_today = P.DAILY_CAP - posted_today
    if remaining_today <= 0:
        log.info("daily cap reached (%d/%d)", posted_today, P.DAILY_CAP)
        state_mod.save(st)
        queue_store.save(q)
        return 0

    budget = min(P.PER_RUN_CAP, remaining_today)

    try:
        client = P.build_client()
    except ValueError as exc:
        log.error("missing credentials for backend '%s': %s", P.POST_BACKEND, exc)
        state_mod.save(st)
        queue_store.save(q)
        return 1

    log.info("posting backend: %s | queue=%d budget=%d",
             P.POST_BACKEND, len(q["pending"]), budget)

    posted = 0
    while posted < budget and q["pending"]:
        item = q["pending"][0]  # peek oldest

        if posted > 0:
            delay = random.uniform(*P.DELAY_RANGE)
            log.info("sleeping %.1fs before next post", delay)
            time.sleep(delay)

        try:
            client.post(P.render_post(item))
        except RetryableError as exc:
            log.warning("transient error, stopping run gracefully: %s", exc)
            break
        except LinkedInError as exc:
            # Permanent failure for this item: drop it so it doesn't wedge the queue.
            log.warning("post failed, dropping item: %s", exc)
            q["pending"].pop(0)
            continue

        q["pending"].pop(0)
        record = dict(item)
        record["ts"] = time.time()
        q["posted"].append(record)
        st["counts"][day] = st["counts"].get(day, 0) + 1
        posted += 1
        log.info("posted: %s", item.get("title"))

    log.info("publish complete: %d posted (%d/%d today), %d still queued",
             posted, st["counts"].get(day, 0), P.DAILY_CAP, len(q["pending"]))
    state_mod.save(st)
    queue_store.save(q)
    site_data.write(q)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(run())
