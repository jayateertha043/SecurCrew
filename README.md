# SecurCrew — LinkedIn Company Page RSS Auto-Poster

A zero-cost bot that aggregates infosec / cybersecurity / bug-bounty news from
many RSS/Atom feeds, keeps **one original per story**, and posts a short
AI-written summary to the **SecurCrew LinkedIn Company Page** (a LinkedIn
**Organization** — "Company Page" and "Organization" are the same entity in the
API). It runs entirely on **GitHub Actions**, buffers stories in a committed
`state/queue.json`, deduplicates aggressively, caps posts per day, and paces
posts like a human.

> **Company Page, not personal profile.** Posts are authored as
> `urn:li:organization:<ORG_ID>` using the `w_organization_social` scope. The
> bot never uses `w_member_social` (which would post to a personal profile).

---

## How it works

A **producer/consumer queue** decouples collection from posting, communicating
through a committed `state/queue.json`:

**1. Collector (`collect.py`)** — runs each cycle:
- Reads feeds from [`feeds.txt`](feeds.txt), parses with `feedparser`, skips
  erroring feeds.
- **Layered deduplication:**
  - *Exact* — SHA-1 of the link (`state.seen`).
  - *Fuzzy* — `rapidfuzz.token_set_ratio` ≥ **85** vs. recent history clusters
    near-verbatim reposts across feeds.
  - *AI clustering (optional)* — one cheap batched call groups paraphrased
    reposts that fuzzy matching misses, so only **one original** per story
    survives. Within a group the **earliest-published** item wins.
- **AI summary (optional)** — the surviving originals get a factual 2–3 line
  summary in one batched call (fail-soft: falls back to clipping the feed text).
- Appends each original to `state/queue.json` `pending`.

**2. Publisher (`publish.py`)** — runs on the posting schedule:
- Pops the oldest queued items and posts **one story per post** (title +
  summary + source attribution + hashtags).
- **Daily cap** (`state.counts[YYYY-MM-DD]`) and **per-run cap** throttle
  output; the rest stays queued for later. Counter increments only on a
  confirmed 2xx.
- **Human-like pacing** — randomized `45–120 s` sleep between posts.

**Pruning** — old `seen`/`history`/`counts`, the `posted` log (7 days), and
stale unposted `pending` items (2 days) are dropped so state stays tiny.

> The two phases run as **independent scheduled workflows**: the **Collector**
> (`collect.yml`) fills the queue and the website data, and the **Publisher**
> (`post.yml`) drains the queue to LinkedIn. The website therefore works even if
> LinkedIn is never configured, and a publishing failure never affects the site.

---

## Project layout

```
.
├── .github/workflows/collect.yml # RSS -> queue + site data (no LinkedIn needed)
├── .github/workflows/post.yml    # queue -> LinkedIn (publisher only)
├── feeds.txt                    # feed URLs, one per line (# comments allowed)
├── collect.py                   # aggregate -> dedup -> pick original -> summarize -> enqueue
├── publish.py                   # drain queue -> post one story per item
├── bot.py                       # thin runner: collect then publish (manual/combined)
├── pipeline.py                  # shared tunables + feed/render/backend helpers
├── queue_store.py               # load/save/prune state/queue.json
├── linkedin.py                  # Organization (Company Page) API client
├── linkedin_webhook.py          # webhook backend (Zapier/Make/n8n) — no API approval
├── summarize.py                 # AI dedup-clustering + summaries (OpenAI-compatible)
├── dedup.py                     # exact + fuzzy dedup + normalization
├── state.py                     # load/save/prune state.json
├── site_data.py                 # emit docs/data/items.json for the Pages UI
├── requirements.txt             # feedparser, requests, rapidfuzz
├── state/state.json             # committed dedup + counter state
├── state/queue.json             # committed post queue (pending + posted log)
├── docs/                        # GitHub Pages UI (index.html, styles.css, app.js, data/)
└── README.md
```

---

## Setup

> **Two posting backends.** `bot.py` can publish either directly via the
> LinkedIn Organization API (`POST_BACKEND=api`, the default) **or** by handing
> the composed message to an automation webhook (`POST_BACKEND=webhook`). The
> webhook path lets a partner tool (Zapier / Make / n8n / Postiz) publish to the
> Company Page, so you **don't need Community Management API approval**. All the
> feed aggregation, dedup, pacing, and daily-cap logic is identical either way.
>
> - Steps **1–5** below configure the **API** backend.
> - The **[Webhook backend](#webhook-backend-no-linkedin-api-approval)** section
>   configures the alternative.

### 1. Create a LinkedIn Developer app and associate it with the Company Page

1. Go to <https://www.linkedin.com/developers/apps> and **Create app**.
2. Under **App settings → Company**, select the **SecurCrew** Company Page. The
   app **must be associated with that organization**, and you must be a **Page
   admin** — otherwise posting returns `403`.
3. Verify the app from the Page (LinkedIn prompts a Page admin to confirm).

### 2. Request the Community Management API product (`w_organization_social`)

1. In the app's **Products** tab, request **Community Management API**.
2. This grants the **`w_organization_social`** scope used to post as the
   organization. **This approval is the main gate** — you must be a Page admin
   and may need to complete LinkedIn's access request form. Do **not** rely on
   `w_member_social`; that only posts to a personal profile.

### 3. Find the Organization URN

The author value must be `urn:li:organization:<id>`.

- **Via API** (with a token that has org access):
  ```bash
  curl -s 'https://api.linkedin.com/rest/organizationAcls?q=roleAssignee' \
    -H "Authorization: Bearer $LINKEDIN_TOKEN" \
    -H "LinkedIn-Version: 202401" \
    -H "X-Restli-Protocol-Version: 2.0.0"
  ```
  The response contains `organization` values like `urn:li:organization:12345678`.
- **Via the Page admin URL:** open the SecurCrew Company Page admin view; the URL
  contains the numeric organization id (`.../company/12345678/admin/`). Build the
  URN as `urn:li:organization:12345678`.

### 4. Get an access token (and know the refresh caveat)

1. Use LinkedIn's OAuth flow (Authorization Code) to obtain an access token that
   includes the `w_organization_social` scope. LinkedIn's token tools /
   3-legged OAuth flow in the developer portal can generate one for testing.
2. **Tokens expire in ~60 days.** When it expires, re-run the OAuth flow (or use
   the refresh token, if your app was granted one) to mint a new access token,
   then **update the `LINKEDIN_TOKEN` repository secret** (Step 5). Posting will
   `401`/`403` once the token lapses until you rotate it.

### 5. Add repository secrets

In **GitHub → repo → Settings → Secrets and variables → Actions**, add:

| Secret | Value |
| --- | --- |
| `LINKEDIN_TOKEN` | The OAuth access token with `w_organization_social`. |
| `LINKEDIN_ORG_URN` | `urn:li:organization:<id>` for the SecurCrew Page. |

These are read as environment variables by `bot.py`; nothing is hardcoded.

### 6. Keep the repo public

Public repositories get **unlimited GitHub Actions minutes**, keeping this
permanently free. The state commits are tiny.

---

## AI summaries (free, optional)

Collected items are rewritten into clean 2–3 line summaries by any
OpenAI-compatible LLM, and the same endpoint powers the optional dedup-clustering
pass. It's **fail-soft**: if AI is unavailable or a call fails, the collector
falls back to fuzzy-only dedup and clipping the raw feed text — a run never
breaks over AI.

**Default: GitHub Models — zero setup.** The Collector workflow is preconfigured
to use **GitHub Models** via the built-in `GITHUB_TOKEN` (`permissions: models:
read`). No account, no key, no secret to rotate — it just works when Actions run.

**Providers** (all OpenAI-compatible; override the default by setting the
secret/variables below):

| Provider | `AI_BASE_URL` | Example `AI_MODEL` | Auth |
| --- | --- | --- | --- |
| **GitHub Models** (default) | `https://models.github.ai/inference` | `openai/gpt-4o-mini` | built-in `GITHUB_TOKEN` |
| **Groq** | `https://api.groq.com/openai/v1` | `llama-3.1-8b-instant` | free `AI_API_KEY`, no card |
| **Google Gemini** | `https://generativelanguage.googleapis.com/v1beta/openai` | `gemini-1.5-flash` | free `AI_API_KEY` |

**To keep the default (GitHub Models):** do nothing.

**To switch providers**, in **Settings → Secrets and variables → Actions**:
1. Add **secret** `AI_API_KEY` = your provider key.
2. Add **variables** `AI_BASE_URL` and `AI_MODEL` for that provider.
3. The workflow's `${{ secrets.AI_API_KEY || secrets.GITHUB_TOKEN }}` fallbacks
   mean any value you set overrides the GitHub Models default.

**To disable AI** entirely, set variable `USE_AI_SUMMARY=0` (uses fuzzy dedup +
clipping).

All originals in a collect run are summarized in **one** API call, and dedup
clustering is **one** more — bounded and cheap even on free rate limits.

---

## Webhook backend (no LinkedIn API approval)

If you can't get (or don't want) Community Management API access, run the bot in
**webhook mode**. The bot keeps doing all the aggregation/dedup/pacing/cap work,
but instead of calling `api.linkedin.com` it POSTs each composed message as
`{"text": "..."}` to an automation tool that already has an approved LinkedIn
Company Page connection.

**1. Build the automation (example: Zapier)**
- Trigger: **Webhooks by Zapier → Catch Hook** → copy the hook URL.
- Action: **LinkedIn Pages → Create Company Update** (or Buffer/Hootsuite/Make/
  n8n equivalent). Map the incoming `text` field to the post body, and select
  the **SecurCrew** Company Page. (You authorize the Page inside Zapier's own
  OAuth — no developer approval needed on your side.)
- **Make / n8n / Postiz** work the same way: a webhook/catch node → a LinkedIn
  "create page post" node.

**2. Add secrets / variables in GitHub**

| Name | Type | Value |
| --- | --- | --- |
| `POST_BACKEND` | **Variable** (Settings → Variables) | `webhook` |
| `WEBHOOK_URL` | **Secret** | The catch-hook URL from your automation |

Leave `POST_BACKEND` unset (or `api`) to use the direct LinkedIn API instead.

**3. That's it** — the workflow already passes `POST_BACKEND` and `WEBHOOK_URL`
through to the publisher. Run it locally with:
```bash
POST_BACKEND=webhook WEBHOOK_URL=https://hooks.zapier.com/... python publish.py
```

> Trade-off: you rely on the automation tool's free-tier task limits and its
> scheduling, but you keep full control of *what* gets posted (dedup, pacing,
> caps all still run in the collector/publisher). Avoid unofficial scraping
> libraries or headless-browser automation — they violate LinkedIn's ToS and
> risk a page ban.

---

## Running

- **Automatic:** two independent workflows on separate schedules — **Collector**
  (`collect.yml`, twice daily at 06:00 & 18:00 UTC) aggregates feeds into the
  saved store (queue + site data), and **Publisher** (`post.yml`, hourly at :40)
  paces posts from that store. They share a concurrency group so commits never
  collide.
- **Manual:** open the **Actions** tab → *SecurCrew Collector* or *SecurCrew
  LinkedIn Publisher* → **Run workflow** (`workflow_dispatch`).
- **Locally (dry test of parsing/dedup/queue):**
  ```bash
  pip install -r requirements.txt
  python collect.py          # aggregate + dedup + enqueue into state/queue.json
  python publish.py          # drain the queue and post (needs valid credentials)
  # or run both at once:
  python bot.py
  ```
  (Real posts require valid credentials and Page admin access.)

---

## Adding / removing feeds

Edit [`feeds.txt`](feeds.txt). Each line is a feed URL with **optional per-feed
hashtags**:

```
<url> [#tag1 #tag2 ...]
```

Example:
```
https://googleprojectzero.blogspot.com/feeds/posts/default #vulnerability #0day
```

Tokens after the URL that start with `#` are added to that feed's posts on top
of the base `#infosec #cybersecurity #bugbounty` (duplicates are removed), and
they also show as chips on the web UI. Full-line `#` comments are ignored, and
malformed/unreachable feeds are skipped automatically. Aggregators (e.g.
r/netsec, tldrsec) are intentionally excluded to avoid cross-source duplicates.

## Tuning the caps and behavior

All knobs are constants at the top of [`pipeline.py`](pipeline.py):

| Constant | Meaning | Default |
| --- | --- | --- |
| `SIMILARITY_THRESHOLD` | Fuzzy-dup ratio (0–100) | `85` |
| `PER_RUN_CAP` | Max posts published per run | `2` |
| `DAILY_CAP` | Posts per UTC day (queue holds the rest) | `20` |
| `DELAY_RANGE` | Randomized delay between posts (s) | `(45, 120)` |
| `PRUNE_WINDOW_DAYS` | Age at which seen/counts/posted-log prune | `7` |
| `QUEUE_TTL_DAYS` | Age at which unposted queued items are dropped | `2` |
| `MAX_ENQUEUE_PER_RUN` | Cap on items added to the queue per collect | `60` |

AI behavior is env-driven: set `AI_API_KEY` to enable dedup-clustering +
summaries, or `USE_AI_SUMMARY=0` to disable and use fuzzy-only + clipping.

---

## State files

Two committed files, both seeded empty:

[`state/state.json`](state/state.json) — dedup + counters:
```json
{ "seen": {}, "history": [], "counts": {} }
```
- `seen` — `{ sha1(link): epoch }` for exact dedup.
- `history` — `[{ ts, norm }]` normalized text for fuzzy dedup.
- `counts` — `{ "YYYY-MM-DD": n }` daily post counters.

[`state/queue.json`](state/queue.json) — the post queue:
```json
{ "pending": [], "posted": [] }
```
- `pending` — FIFO list of ready-to-post originals (title, link, summary,
  source, published, added_at).
- `posted` — recent audit log (`id`, `link`, `ts`), pruned after 7 days.

The counter increments **only on a confirmed 2xx**. On `429`/`5xx` the publisher
backs off and stops, leaving items queued rather than retry-hammering.

---

## Web UI (GitHub Pages)

The [`docs/`](docs) folder is a static site that displays the collected stories
and their AI summaries — no build step, no framework, just HTML/CSS/JS.

**Independent of Actions and LinkedIn.** GitHub Pages *serves* the static files
itself (via "Deploy from a branch") — it does **not** need your workflows to run.
The site's content comes from the **Collector** workflow (RSS aggregation), so it
works fully even if LinkedIn posting is never set up. A publishing failure never
touches the site.

**How it's fed:** the Collector writes [`docs/data/items.json`](docs/data/items.json)
(via `site_data.py`) from the queue, newest first. The page renders cards with a
status badge, source, summary, time-ago, plus search and filters. (The Publisher
also refreshes it to flip items to "posted", but the site never depends on that.)

**Enable it:**
1. Push the repo to GitHub (merge into `main`).
2. **Settings → Pages → Build and deployment → Source: Deploy from a branch.**
3. Select branch **`main`** and folder **`/docs`**, then **Save**.
4. The UI goes live at `https://<user>.github.io/<repo>/` (or your custom
   domain — see [`docs/CNAME`](docs/CNAME)).

Feed content is untrusted, so the UI inserts all text via DOM APIs (never
`innerHTML`) to prevent XSS.

**Preview locally:**
```bash
python -m http.server -d docs 8000   # then open http://localhost:8000
```

---

## Out of scope

No database, no paid hosting, no image/media uploads (text + link posts only,
authored as the Company Page), no analytics dashboard. The GitHub Pages UI is
read-only — it displays the feed but does not control posting.
