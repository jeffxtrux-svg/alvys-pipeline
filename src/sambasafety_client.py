"""SambaSafety REST API client — zero-cost integration.

Wraps just the endpoints we need for the daily scorecard, all in the
"License Monitoring" product family (which is free under the License
Monitoring subscription you already pay for). MVR products (Activity
Indicator, Intelligent MVR, Transactional MVR, etc.) cost state fees
per **order placed** — but **reading already-placed orders is free**,
which is the trick that lets us assemble a full driver-compliance
view without incurring any per-refresh cost.

Endpoints used (all GET, all part of the standard subscription):

  GET /organization/v1/groups?page=1&size=50
  GET /organization/v1/groups/{groupId}/people?page=1&size=50
  GET /organization/v1/people/{personId}/licenses
  GET /organization/v1/licenses/{licenseId}/status
  GET /reports/v1/people/{personId}/motorvehiclereports
  GET /reports/v1/motorvehiclereports/{mvrId}

Auth: SambaSafety supports two equivalent schemes (per their Postman
collection). Pick at construction time:

  * ``bearer`` (default) — ``Authorization: Bearer <jwt>``. Use this
    when the token in your envelope looks like a JWT
    (``eyJhbGciOiJIUzI1NiJ9.…``). SambaSafety also exposes a
    ``POST /oauth2/v1/token`` endpoint that returns the same shape, but
    if your envelope already contains a JWT you can send it directly.
  * ``apikey`` — ``X-Api-Key: <key>``. Use this when SambaSafety gave
    you a non-JWT key (typically a hex string).

The ``SAMBASAFETY_AUTH_SCHEME`` env var picks between them at
runtime; default is ``bearer``. We do NOT call /oauth2/v1/token because
the JWT in the envelope is already the value the bearer header expects.

Production base URL: ``https://api.sambasafety.io``
Demo base URL:       ``https://api-demo.sambasafety.io``

Pagination response shape is uniform:
    { "data": [...], "meta": {"totalPages": N}, "links": {...} }

So a single ``_paginate`` helper covers every list endpoint.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests


log = logging.getLogger(__name__)


_PROD_BASE = "https://api.sambasafety.io"
_DEMO_BASE = "https://api-demo.sambasafety.io"
_DEFAULT_PAGE_SIZE = 50
_REQUEST_TIMEOUT = 30
_INTER_PAGE_DELAY = 0.1   # seconds; SambaSafety rate-limit cushion


class SambaSafetyClient:
    """Thin wrapper around the SambaSafety REST API.

    All list endpoints are streamed via :py:meth:`_paginate`, which yields
    individual records from every page until the API stops returning more.
    All fetch errors are surfaced as ``SambaSafetyError`` so the caller can
    decide whether to soft-fail (matching the rest of the pipeline's
    "fail-soft on optional data" pattern).
    """

    def __init__(self, api_key: str, base_url: str | None = None,
                 timeout: int = _REQUEST_TIMEOUT,
                 auth_scheme: str = "bearer") -> None:
        if not api_key:
            raise SambaSafetyError("api_key is required")
        scheme = (auth_scheme or "bearer").strip().lower()
        if scheme not in ("bearer", "apikey"):
            raise SambaSafetyError(
                f"auth_scheme must be 'bearer' or 'apikey', got {auth_scheme!r}")
        self.base_url = (base_url or _PROD_BASE).rstrip("/")
        self.timeout = timeout
        self.auth_scheme = scheme
        self._headers = {
            "Accept": "application/json",
            "User-Agent": "alvys-pipeline/sambasafety-client",
        }
        if scheme == "bearer":
            self._headers["Authorization"] = f"Bearer {api_key}"
        else:
            self._headers["X-Api-Key"] = api_key

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        resp = requests.get(url, headers=self._headers, params=params,
                            timeout=self.timeout)
        if resp.status_code >= 400:
            body = resp.text[:500] if resp.text else ""
            log.error("GET %s -> HTTP %s: %s", path, resp.status_code, body)
            raise SambaSafetyError(
                f"HTTP {resp.status_code} on GET {path}: {body}")
        try:
            return resp.json()
        except ValueError:
            raise SambaSafetyError(f"Non-JSON response from GET {path}")

    def _paginate(self, path: str, params: dict | None = None,
                  page_size: int = _DEFAULT_PAGE_SIZE) -> Iterator[dict]:
        page = 1
        params = dict(params or {})
        while True:
            params["page"] = page
            params["size"] = page_size
            payload = self._get(path, params=params)
            rows = payload.get("data") or []
            for r in rows:
                yield r
            # Stop when this was the last page.
            total = (payload.get("meta") or {}).get("totalPages")
            if not rows:
                return
            if isinstance(total, int) and page >= total:
                return
            # Defensive cap on accidental infinite loop.
            if page >= 200:
                log.warning("_paginate hit 200-page safety cap on %s", path)
                return
            page += 1
            time.sleep(_INTER_PAGE_DELAY)

    # ------------------------------------------------------------------
    # Public API — read-only, no per-call cost
    # ------------------------------------------------------------------
    def list_groups(self) -> list[dict]:
        """All organization groups (used to find the X-Trux group ID)."""
        return list(self._paginate("/organization/v1/groups"))

    def list_people_in_group(self, group_id: str) -> list[dict]:
        """Active monitored drivers in a group."""
        return list(self._paginate(
            f"/organization/v1/groups/{group_id}/people"))

    def list_licenses_for_person(self, person_id: str) -> list[dict]:
        """Licenses on file for a single driver (no pagination on this path)."""
        payload = self._get(f"/organization/v1/people/{person_id}/licenses")
        return payload.get("data") or payload.get("licenses") or []

    def get_license_status(self, license_id: str) -> dict | None:
        """Current monitored status (VALID / SUSPENDED / EXPIRED / etc).
        Returns ``None`` on a 404 so the caller can keep going."""
        try:
            return self._get(f"/organization/v1/licenses/{license_id}/status")
        except SambaSafetyError as e:
            if "HTTP 404" in str(e):
                return None
            raise

    def list_mvrs_for_person(self, person_id: str) -> list[dict]:
        """Existing MVR reports for a driver. Each entry has at least
        ``mvrId`` and ``mvrDateTime``. Listing is free; the report content
        is also free to re-read (the state fee was paid when SambaSafety
        first placed the order)."""
        payload = self._get(
            f"/reports/v1/people/{person_id}/motorvehiclereports")
        return payload.get("data") or []

    def get_mvr_report(self, mvr_id: str) -> dict | None:
        """Full MVR report content — license expiration, violations,
        risk fields if present. Returns ``None`` on 404."""
        try:
            return self._get(f"/reports/v1/motorvehiclereports/{mvr_id}")
        except SambaSafetyError as e:
            if "HTTP 404" in str(e):
                return None
            raise


class SambaSafetyError(RuntimeError):
    """Raised when the SambaSafety API returns an unrecoverable error
    (4xx other than 404, 5xx, malformed JSON, network failure)."""
