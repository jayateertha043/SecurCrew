"""LinkedIn Organization (Company Page) posting client.

Posts are authored as ``urn:li:organization:<id>`` via the Posts REST API,
which makes them **Company Page** posts (not personal-profile posts). Requires
the ``w_organization_social`` scope (Community Management API) and a token owned
by an admin of the page whose app is associated with that organization.
"""

from __future__ import annotations

from typing import Tuple

import requests

POSTS_URL = "https://api.linkedin.com/rest/posts"
LINKEDIN_VERSION = "202401"
REQUEST_TIMEOUT = 30


class LinkedInError(Exception):
    """Raised when a post cannot be created."""


class RetryableError(LinkedInError):
    """Transient failure (HTTP 429 / 5xx) — back off and stop the run."""


class LinkedInClient:
    """Minimal client for creating text + link shares on a Company Page."""

    def __init__(self, token: str, org_urn: str) -> None:
        if not token or not org_urn:
            raise ValueError("LINKEDIN_TOKEN and LINKEDIN_ORG_URN are required")
        self._org_urn = org_urn
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "LinkedIn-Version": LINKEDIN_VERSION,
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
            }
        )

    def post(self, text: str) -> None:
        """Create a Company Page share. Raises on failure.

        The link is included inline in ``text`` (LinkedIn auto-unfurls URLs in
        the commentary), keeping this to text + link only — no media uploads.
        """
        body = {
            "author": self._org_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        try:
            resp = self._session.post(
                POSTS_URL, json=body, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:  # network-level failure
            raise RetryableError(f"network error: {exc}") from exc

        if 200 <= resp.status_code < 300:
            return

        detail = _short(resp.text)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RetryableError(f"HTTP {resp.status_code}: {detail}")
        raise LinkedInError(f"HTTP {resp.status_code}: {detail}")


def _short(text: str, limit: int = 300) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:limit]


def build_urn_from_env(token: str, org_urn: str) -> Tuple[str, str]:
    """Validate and pass through the credential pair (kept for symmetry)."""
    if not token or not org_urn:
        raise ValueError("Missing LinkedIn credentials")
    return token, org_urn
