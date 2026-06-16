"""Ramp API client — OAuth2 client-credentials, fetches open bills.

Each XFreight legal entity (X-Trux Inc, X-Linx Inc) has its own Ramp
business account with separate client_id / client_secret credentials.
Instantiate one RampClient per entity and each call returns only that
entity's data.

Required env per entity (set via GitHub Secrets):
    RAMP_XTRUX_CLIENT_ID / RAMP_XTRUX_CLIENT_SECRET
    RAMP_XLINX_CLIENT_ID / RAMP_XLINX_CLIENT_SECRET
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

log = logging.getLogger("ramp_client")

_TOKEN_URL = "https://api.ramp.com/developer/v1/token"
_BILLS_URL = "https://api.ramp.com/developer/v1/bills"

# Statuses that represent unpaid / open bills.
_OPEN_STATUSES = {"DRAFT", "APPROVED", "SCHEDULED", "PROCESSING", "FAILED"}

# Vendors excluded from cash-flow AP (intercompany / non-operational).
_EXCLUDE_VENDORS = {"n&j trailers", "n&j properties", "n and j trailers"}


class RampClient:
    def __init__(self, client_id: str, client_secret: str, entity_name: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.entity_name = entity_name
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _ensure_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token
        log.info("Fetching Ramp token for %s…", self.entity_name or "entity")
        resp = requests.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": "bills:read"},
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        if resp.status_code != 200:
            log.error("Ramp token failed [%s]: %s", resp.status_code, resp.text[:300])
            resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600) - 60
        log.info("Ramp token acquired for %s", self.entity_name)
        return self._access_token  # type: ignore[return-value]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Accept": "application/json",
        }

    def fetch_open_bills(self) -> list[dict[str, Any]]:
        """Return all open (unpaid) bills for this entity, excluding intercompany."""
        bills: list[dict] = []
        params: dict[str, Any] = {"page_size": 100}
        while True:
            resp = requests.get(_BILLS_URL, headers=self._headers(), params=params, timeout=60)
            if resp.status_code != 200:
                log.error(
                    "Ramp bills fetch failed [%s] for %s: %s",
                    resp.status_code, self.entity_name, resp.text[:300],
                )
                resp.raise_for_status()
            data = resp.json()
            page = data.get("data", [])
            for bill in page:
                status = (bill.get("payment_status") or bill.get("status") or "").upper()
                if status not in _OPEN_STATUSES:
                    continue
                vendor = (
                    bill.get("vendor", {}).get("name", "")
                    if isinstance(bill.get("vendor"), dict)
                    else str(bill.get("vendor_name") or "")
                ).strip().lower()
                if vendor in _EXCLUDE_VENDORS:
                    continue
                bills.append(bill)
            # Pagination: Ramp uses a cursor-based `next` pointer.
            nxt = (data.get("page") or {}).get("next")
            if not nxt:
                break
            params["start"] = nxt
        log.info("%s: %d open bills after filtering", self.entity_name, len(bills))
        return bills
