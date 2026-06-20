"""Ramp REST API client — bills (AP), card transactions, users.

Handles OAuth 2.0 client_credentials token flow with auto-refresh.
All endpoints are paginated; _paginate() yields every item transparently.

GitHub Secrets required:
    RAMP_CLIENT_ID      — from Ramp: Settings → Developers → Applications
    RAMP_CLIENT_SECRET  — same app
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests

log = logging.getLogger("ramp_client")

TOKEN_URL = "https://api.ramp.com/developer/v1/token"
BASE_URL  = "https://api.ramp.com/developer/v1"

# Scopes for read-only pipeline access
_SCOPES = " ".join([
    "bills:read",
    "transactions:read",
    "users:read",
    "receipts:read",
    "departments:read",
    "business:read",
])


class RampClient:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id     = client_id
        self.client_secret = client_secret
        self._access_token: str | None = None
        self._expires_at:   float      = 0.0

    # ── auth ─────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        log.info("Refreshing Ramp access token…")
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": _SCOPES},
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        if resp.status_code != 200:
            log.error("Token refresh failed [%s]: %s", resp.status_code, resp.text[:400])
            resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at   = time.time() + data.get("expires_in", 3600) - 60
        log.info("Ramp token refreshed ✓")

    def _token(self) -> str:
        if not self._access_token or time.time() >= self._expires_at:
            self._refresh()
        return self._access_token  # type: ignore[return-value]

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = requests.get(
            f"{BASE_URL}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {self._token()}"},
            params=params or {},
            timeout=60,
        )
        if resp.status_code == 401:
            # Token expired mid-run — force one refresh and retry
            self._access_token = None
            resp = requests.get(
                f"{BASE_URL}/{path.lstrip('/')}",
                headers={"Authorization": f"Bearer {self._token()}"},
                params=params or {},
                timeout=60,
            )
        resp.raise_for_status()
        return resp.json()

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        """Yield every item across all pages using Ramp's cursor pagination."""
        p = dict(params or {})
        p.setdefault("page_size", 100)
        while True:
            data = self._get(path, p)
            items = data.get("data", [])
            yield from items
            # Ramp returns next cursor in page.next
            next_cursor = (data.get("page") or {}).get("next")
            if not next_cursor:
                break
            p["start"] = next_cursor

    # ── public endpoints ─────────────────────────────────────────────────────

    def bills(self, from_date: str | None = None, to_date: str | None = None) -> list[dict]:
        """All AP bills. Dates as YYYY-MM-DD strings."""
        params: dict[str, Any] = {}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        return list(self._paginate("/bills", params))

    def transactions(self, from_date: str | None = None, to_date: str | None = None) -> list[dict]:
        """All card transactions. Dates as YYYY-MM-DD strings."""
        params: dict[str, Any] = {}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        return list(self._paginate("/transactions", params))

    def users(self) -> list[dict]:
        return list(self._paginate("/users"))

    def departments(self) -> list[dict]:
        return list(self._paginate("/departments"))
