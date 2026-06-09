"""
Alvys API client.

Handles OAuth2 client_credentials auth (Auth0-style, requires JSON body
with audience parameter), pagination, and the three /search endpoints:
loads/search, trips/search, fuel/search.

Reference: https://docs.alvys.com/
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)

AUTH_URL = "https://auth.alvys.com/oauth/token"
AUDIENCE = "https://api.alvys.com/public/"

API_VERSION = "1"
BASE_URL = f"https://integrations.alvys.com/api/p/v{API_VERSION}"

PAGE_SIZE = 100


class AlvysClient:
    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = None
        self._token_expires_at: float = 0
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Auth — Auth0-style: JSON body, audience required
    # ------------------------------------------------------------------
    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token

        log.info("Requesting new Alvys access token")
        resp = self._session.post(
            AUTH_URL,
            json={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "audience": AUDIENCE,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if resp.status_code != 200:
            log.error("Auth failed [%d]: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()

        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)

        if "scope" in data:
            log.info("Token scopes: %s", data["scope"])
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # POST /<resource>/search paginator
    # ------------------------------------------------------------------
    def _paginate_search(self, path: str, body: dict) -> Iterator[dict]:
        page = 0
        total_yielded = 0

        while True:
            req_body = dict(body)
            req_body["page"] = page
            req_body["pageSize"] = PAGE_SIZE

            url = f"{BASE_URL}{path}"
            resp = self._session.post(
                url, headers=self._headers(), json=req_body, timeout=120,
            )
            if resp.status_code != 200:
                log.error("%s page %d failed [%d]: %s",
                          path, page, resp.status_code, resp.text[:500])
            resp.raise_for_status()

            payload = resp.json()

            def _get(d: dict, *keys: str) -> Any:
                for k in keys:
                    if k in d:
                        return d[k]
                return None

            if isinstance(payload, list):
                items = payload
                total = None
            elif isinstance(payload, dict):
                items = _get(payload, "Items", "items", "data", "results") or []
                total = _get(payload, "Total", "TotalCount", "total", "totalCount")
            else:
                items = []
                total = 0

            if not items and page == 0:
                log.warning("First page empty on %s. Response keys: %s",
                            path, list(payload.keys()) if isinstance(payload, dict) else "(not a dict)")

            if not items:
                break

            for item in items:
                yield item
            total_yielded += len(items)

            log.info("  page %d: %d records (running total: %d%s)",
                     page, len(items), total_yielded,
                     f" of {total}" if total else "")

            if len(items) < PAGE_SIZE:
                break
            if total is not None and total_yielded >= total:
                break

            page += 1
            time.sleep(0.2)

    ALL_LOAD_STATUSES = [
        "Open", "Queued", "Covered", "Dispatched", "In Transit",
        "Released", "Invoiced", "Completed", "Cancelled",
    ]
    ALL_TRIP_STATUSES = [
        "Open", "Covered", "Dispatched", "In Transit", "Delivered",
        "Released", "Invoiced", "Completed", "Cancelled",
    ]

    def fetch_loads(self, start_date: str) -> list[dict]:
        log.info("Fetching loads from %s onward", start_date)
        end_date = time.strftime("%Y-%m-%dT23:59:59Z")
        body = {
            "status": self.ALL_LOAD_STATUSES,
            "updatedAtRange": {"start": f"{start_date}T00:00:00Z", "end": end_date},
        }
        items = list(self._paginate_search("/loads/search", body))
        log.info("Total loads fetched: %d", len(items))
        return items

    def fetch_trips(self, start_date: str) -> list[dict]:
        log.info("Fetching trips from %s onward", start_date)
        end_date = time.strftime("%Y-%m-%dT23:59:59Z")
        body = {
            "status": self.ALL_TRIP_STATUSES,
            "updatedAtRange": {"start": f"{start_date}T00:00:00Z", "end": end_date},
        }
        items = list(self._paginate_search("/trips/search", body))
        log.info("Total trips fetched: %d", len(items))
        return items

    def fetch_fuel(self, start_date: str) -> list[dict]:
        log.info("Fetching fuel transactions from %s onward", start_date)
        end_date = time.strftime("%Y-%m-%dT23:59:59Z")
        body = {
            "transactionRange": {"start": f"{start_date}T00:00:00Z", "end": end_date},
        }
        items = list(self._paginate_search("/fuel/search", body))
        log.info("Total fuel transactions fetched: %d", len(items))
        return items

    # ------------------------------------------------------------------
    # GET paginator
    # ------------------------------------------------------------------
    def _paginate_get(self, path: str, params: dict | None = None) -> list[dict]:
        all_items: list[dict] = []
        page = 0
        while True:
            req_params = dict(params or {})
            req_params["page"] = page
            req_params["pageSize"] = PAGE_SIZE
            url = f"{BASE_URL}{path}"
            resp = self._session.get(
                url, headers=self._headers(), params=req_params, timeout=120,
            )
            if resp.status_code != 200:
                log.error("GET %s page %d failed [%d]: %s",
                          path, page, resp.status_code, resp.text[:500])
            resp.raise_for_status()
            payload = resp.json()

            if isinstance(payload, list):
                items = payload
                total = None
            elif isinstance(payload, dict):
                items = (payload.get("Items") or payload.get("items") or
                         payload.get("data") or payload.get("results") or [])
                total = payload.get("Total") or payload.get("total")
            else:
                items = []
                total = 0

            if not items:
                break
            all_items.extend(items)
            log.info("  page %d: %d records (running total: %d%s)",
                     page, len(items), len(all_items),
                     f" of {total}" if total else "")
            if len(items) < PAGE_SIZE:
                break
            if total is not None and len(all_items) >= total:
                break
            page += 1
            time.sleep(0.2)
        return all_items

    # ------------------------------------------------------------------
    # Reference-data fetchers
    # ------------------------------------------------------------------
    def _try_search(self, path: str, attempts: list[dict]) -> list[dict]:
        last_err = None
        for body in attempts:
            try:
                return list(self._paginate_search(path, body))
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 400:
                    last_err = e
                    continue
                raise
        raise last_err or RuntimeError(f"No valid filter found for {path}")

    def _fetch_with_fallback(self, get_path: str, search_path: str,
                             search_attempts: list[dict]) -> list[dict]:
        try:
            log.info("Trying GET %s …", get_path)
            return self._paginate_get(get_path)
        except requests.HTTPError as e:
            log.warning("  GET %s failed [%s], falling back to POST %s",
                        get_path, e.response.status_code if e.response else "?",
                        search_path)
            return self._try_search(search_path, search_attempts)

    def fetch_drivers(self) -> list[dict]:
        log.info("Fetching all drivers")
        items = self._fetch_with_fallback(
            "/drivers", "/drivers/search",
            [{"status": ["Active", "Inactive"]}, {"status": ["Active"]}, {}],
        )
        log.info("Total drivers fetched: %d", len(items))
        return items

    def fetch_trucks(self) -> list[dict]:
        log.info("Fetching all trucks")
        items = self._fetch_with_fallback(
            "/trucks", "/trucks/search",
            [{"status": ["Active", "Inactive"]}, {"status": ["Active"]}, {}],
        )
        log.info("Total trucks fetched: %d", len(items))
        return items

    def fetch_trailers(self) -> list[dict]:
        log.info("Fetching all trailers")
        items = self._fetch_with_fallback(
            "/trailers", "/trailers/search",
            [{"status": ["Active", "Inactive"]}, {"status": ["Active"]}, {}],
        )
        log.info("Total trailers fetched: %d", len(items))
        return items

    def fetch_trailer_detail(self, trailer_id: str) -> dict | None:
        """One-shot schema probe — the list endpoint /trailers returns a
        13-field summary that omits InspectionExpirationDate /
        LicenseExpirationDate (visible in the Alvys UI's Trailers list).
        Tries a few detail-endpoint shapes and returns the first that
        works so the discovered field set can be logged."""
        candidates = [
            f"/trailers/{trailer_id}",
            f"/trailer/{trailer_id}",
            f"/trailers/{trailer_id}/details",
            f"/trailers/details/{trailer_id}",
        ]
        for path in candidates:
            try:
                url = f"{BASE_URL}{path}"
                resp = self._session.get(url, headers=self._headers(), timeout=60)
                if resp.status_code == 200:
                    payload = resp.json()
                    # Some endpoints wrap the record in {"Items": [...]} or similar.
                    if isinstance(payload, dict) and isinstance(payload.get("Items"), list):
                        payload = payload["Items"][0] if payload["Items"] else None
                    log.info("  ✓ trailer detail via %s — %d keys",
                             path, len(payload) if isinstance(payload, dict) else 0)
                    return payload
                else:
                    log.info("  %s → HTTP %d", path, resp.status_code)
            except Exception as e:
                log.info("  %s → %s", path, e)
        return None

    def fetch_truck_detail(self, truck_id: str) -> dict | None:
        """Symmetric probe for trucks — the list endpoint returns 24 keys
        including InspectionExpirationDate, but the values are blank on
        most records. The detail endpoint may carry richer per-asset
        compliance data (last-inspection date, etc.)."""
        candidates = [
            f"/trucks/{truck_id}",
            f"/truck/{truck_id}",
            f"/trucks/{truck_id}/details",
            f"/trucks/details/{truck_id}",
        ]
        for path in candidates:
            try:
                url = f"{BASE_URL}{path}"
                resp = self._session.get(url, headers=self._headers(), timeout=60)
                if resp.status_code == 200:
                    payload = resp.json()
                    if isinstance(payload, dict) and isinstance(payload.get("Items"), list):
                        payload = payload["Items"][0] if payload["Items"] else None
                    log.info("  ✓ truck detail via %s — %d keys",
                             path, len(payload) if isinstance(payload, dict) else 0)
                    return payload
                else:
                    log.info("  %s → HTTP %d", path, resp.status_code)
            except Exception as e:
                log.info("  %s → %s", path, e)
        return None

    def fetch_maintenance(self, lookback_days: int = 365) -> list[dict]:
        """Fetch maintenance/inspection records from POST /maintenance/search.
        Returns raw list; field names are logged on first run for schema discovery."""
        from datetime import datetime, timedelta
        log.info("Fetching maintenance records (lookback_days=%d)", lookback_days)
        now = datetime.utcnow()
        start = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%dT00:00:00Z")
        end = now.strftime("%Y-%m-%dT23:59:59Z")
        body = {"dateRange": {"start": start, "end": end}}
        try:
            items = list(self._paginate_search("/maintenance/search", body))
            log.info("Total maintenance records fetched: %d", len(items))
            return items
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            log.warning("maintenance/search → HTTP %s — skipping maintenance data", code)
            return []
        except Exception as e:
            log.warning("maintenance/search failed: %s — skipping maintenance data", e)
            return []

    def fetch_users(self) -> list[dict]:
        log.info("Fetching all users")
        items = self._fetch_with_fallback(
            "/users/list", "/users/search",
            [{"status": ["Active", "Inactive"]}, {"status": ["Active"]}, {}],
        )
        log.info("Total users fetched: %d", len(items))
        return items

    # ------------------------------------------------------------------
    # NEW: Optional reference data — graceful fallback if endpoint missing
    # ------------------------------------------------------------------
    def _try_get_optional(self, paths: list[str]) -> list[dict]:
        """Try each GET path in order; return first success, or empty list."""
        for path in paths:
            try:
                log.info("Trying GET %s …", path)
                items = self._paginate_get(path)
                if items:
                    log.info("  ✓ %s returned %d records", path, len(items))
                    return items
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                log.info("  %s → HTTP %s, trying next", path, code)
                continue
            except Exception as e:
                log.info("  %s → %s, trying next", path, e)
                continue
        return []

    def fetch_offices(self) -> list[dict]:
        """Try /offices, /companies, /tenants for office name lookups."""
        return self._try_get_optional(["/offices", "/companies", "/tenants"])

    def fetch_subsidiaries(self) -> list[dict]:
        """Subsidiaries (InvoiceAs/TenderAs entities — X-TRUX INC etc.)"""
        return self._try_get_optional(["/subsidiaries"])

    def fetch_carriers(self) -> list[dict]:
        """Carrier list for factoring-company and carrier-name lookups."""
        items = self._try_get_optional(["/carriers"])
        if items:
            return items
        try:
            return self._try_search(
                "/carriers/search",
                [{"status": ["Active"]}, {"status": ["Active", "Inactive"]}, {}],
            )
        except Exception as e:
            log.warning("  /carriers/search failed: %s", e)
            return []

    def fetch_customers(self) -> list[dict]:
        """Customer list for AM/SM/CSR + invoicing-method lookups.
        
        API requires `Statuses` field (capital S, plural) per error response:
          {"Statuses":["The Statuses field is required."]}
        """
        items = self._try_get_optional(["/customers"])
        if items:
            return items
        for body in [
            {"Statuses": ["Active", "Inactive"]},
            {"Statuses": ["Active"]},
        ]:
            try:
                log.info("Trying POST /customers/search with %s …", body)
                return list(self._paginate_search("/customers/search", body))
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                log.info("  /customers/search %s → HTTP %s, trying next", body, code)
                continue
            except Exception as e:
                log.info("  /customers/search %s → %s, trying next", body, e)
                continue
        log.warning("  customers: all attempts failed")
        return []

    def fetch_invoices(self, start_date: str) -> list[dict]:
        """Invoice list for Carrier Invoice Number / Due Date / Customer Due Date.

        API error response told us the spec:
          - Required: at least one of {Status, PONumbers, CustomerId, LoadNumbers, OrderNumbers}
          - Status valid values: Draft, AwaitingPayment, Paid
        """
        items = self._try_get_optional(["/invoices"])
        if items:
            return items
        for body in [
            {"Status": ["Draft", "AwaitingPayment", "Paid"]},
            {"Status": ["AwaitingPayment", "Paid"]},
            {"Status": ["Paid"]},
        ]:
            try:
                log.info("Trying POST /invoices/search with Status=%s …", body["Status"])
                return list(self._paginate_search("/invoices/search", body))
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else "?"
                log.info("  /invoices/search %s → HTTP %s, trying next",
                         body["Status"], code)
                continue
            except Exception as e:
                log.info("  /invoices/search %s → %s, trying next",
                         body["Status"], e)
                continue
        log.warning("  invoices: all attempts failed")
        return []

