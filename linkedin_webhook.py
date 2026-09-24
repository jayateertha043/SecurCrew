"""Webhook posting backend — drop-in alternative to the direct LinkedIn API.

Instead of calling ``api.linkedin.com`` (which needs the Community Management
API approval), this POSTs the composed message to an automation webhook
(Zapier, Make, n8n, Postiz, etc.). That service holds the approved LinkedIn
connection and publishes to the SecurCrew Company Page on your behalf.

Interface mirrors ``linkedin.LinkedInClient`` so ``bot.py`` can swap backends
without any other changes: same ``post(text)`` method and same exceptions.
"""

from __future__ import annotations

import requests

from linkedin import LinkedInError, RetryableError

REQUEST_TIMEOUT = 30


class WebhookClient:
    """POSTs ``{"text": ...}`` to an automation webhook that fans out to LinkedIn."""

    def __init__(self, webhook_url: str) -> None:
        if not webhook_url:
            raise ValueError("WEBHOOK_URL is required for the webhook backend")
        self._url = webhook_url
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def post(self, text: str) -> None:
        """Send one item to the webhook. Raises on failure.

        Zapier/Make return 200 with a small JSON ack; anything else is treated
        the same way as the direct client (429/5xx = retryable, else fatal).
        """
        try:
            resp = self._session.post(
                self._url, json={"text": text}, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            raise RetryableError(f"network error: {exc}") from exc

        if 200 <= resp.status_code < 300:
            return

        detail = (resp.text or "").strip().replace("\n", " ")[:300]
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RetryableError(f"HTTP {resp.status_code}: {detail}")
        raise LinkedInError(f"HTTP {resp.status_code}: {detail}")
