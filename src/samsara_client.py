"""
Samsara Fleet API client.

Auth: Authorization: Token <api_token>  (NOT Bearer)
Pagination: cursor-based via `after` param / `pagination.endCursor` in response.

Reference: https://developers.samsara.com/reference/
"""
from __future__ import annotations

import datetime
import logging
import time

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://api.samsara.com"
PAGE_LIMIT = 512


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ms(dt: datetime.datetime) -> int:
    return int(dt.timestamp() * 1000)


class SamsaraClient:
    def __init__(self, api_token: str):
        self._token = api_token
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _get_pages(self, path: str, params: dict | None = None) -> list[dict]:
        """Cursor-paginate a GET endpoint. Returns all records from `data`."""
        req_params = dict(params or {})
        req_params.setdefault("limit", PAGE_LIMIT)
        url = f"{BASE_URL}{path}"
        all_items: list[dict] = []
        page_num = 0

        while True:
            resp = self._session.get(
                url, headers=self._headers(), params=req_params, timeout=120
            )
            if resp.status_code != 200:
                log.error("GET %s failed [%d]: %s", path, resp.status_code, resp.text[:500])
            resp.raise_for_status()

            payload = resp.json()
            data = payload.get("data", [])
            if isinstance(data, list):
                all_items.extend(data)
                page_num += 1
                log.info("  page %d: %d records (running: %d)", page_num, len(data), len(all_items))
                if not data:
                    break
            elif isinstance(data, dict):
                all_items.append(data)
                break
            else:
                break

            pagination = payload.get("pagination", {})
            if not pagination.get("hasNextPage", False):
                break
            cursor = pagination.get("endCursor")
            if not cursor:
                break
            req_params["after"] = cursor
            time.sleep(0.1)

        return all_items

    def _safe_get(self, path: str, params: dict | None = None) -> list[dict]:
        """Like _get_pages but returns empty list on HTTP errors rather than raising."""
        try:
            return self._get_pages(path, params)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            log.warning("GET %s → HTTP %s — skipping (check API token scope)", path, code)
            return []
        except Exception as e:
            log.warning("GET %s → %s — skipping", path, e)
            return []

    # ------------------------------------------------------------------
    # Reference / roster data (no time filter needed)
    # ------------------------------------------------------------------

    def fetch_vehicles(self) -> list[dict]:
        log.info("Fetching vehicles…")
        items = self._safe_get("/fleet/vehicles")
        log.info("Total vehicles: %d", len(items))
        return items

    def fetch_drivers(self) -> list[dict]:
        log.info("Fetching drivers…")
        items = self._safe_get("/fleet/drivers")
        log.info("Total drivers: %d", len(items))
        return items

    # ------------------------------------------------------------------
    # Current snapshots
    # ------------------------------------------------------------------

    def fetch_vehicle_stats(self) -> list[dict]:
        """Current odometer, fuel %, engine state, GPS for all vehicles.

        Samsara limits to 4 stat types per request — we make two calls and
        merge the results by vehicle ID.
        """
        log.info("Fetching vehicle stats (batch 1/2: odometer + fuel + engine + GPS)…")
        batch1 = self._safe_get("/fleet/vehicles/stats", {
            "types": "obdOdometerMeters,fuelPercents,engineStates,gpsOdometerMeters",
        })
        log.info("Fetching vehicle stats (batch 2/2: engine seconds)…")
        batch2 = self._safe_get("/fleet/vehicles/stats", {
            "types": "syntheticEngineSeconds",
        })

        # Merge batch2 into batch1 by vehicle id
        b2_by_id = {r.get("id"): r for r in batch2}
        for rec in batch1:
            extra = b2_by_id.get(rec.get("id"), {})
            for k, v in extra.items():
                if k not in rec:
                    rec[k] = v

        combined = batch1 if batch1 else batch2
        log.info("Total vehicle stat records: %d", len(combined))
        return combined

    def fetch_locations(self) -> list[dict]:
        """Current GPS position for all vehicles."""
        log.info("Fetching current vehicle locations…")
        items = self._safe_get("/fleet/vehicles/locations")
        log.info("Total location records: %d", len(items))
        return items

    def fetch_fault_codes(self) -> list[dict]:
        """Active OBD diagnostic fault codes (DTC / check-engine / warning lights)."""
        log.info("Fetching active fault codes…")
        items = self._safe_get(
            "/fleet/vehicles/stats", {"types": "nativeObdDtcCodes"}
        )
        log.info("Total fault-code vehicle records: %d", len(items))
        return items

    # ------------------------------------------------------------------
    # Time-range data
    # ------------------------------------------------------------------

    def fetch_trips(
        self,
        start: datetime.datetime,
        end: datetime.datetime,
        vehicle_ids: list[str] | None = None,
    ) -> list[dict]:
        """Trip records via the legacy v1 endpoint `GET /fleet/trips`. The old
        per-vehicle path `/fleet/vehicles/{id}/trips` returns 404.
        """
        log.info("Fetching trips %s → %s…", start.date(), end.date())
        if not vehicle_ids:
            log.warning("No vehicle IDs provided — skipping trips")
            return []
        # v1 legacy /v1/fleet/trips is **per-vehicle** (singular ``vehicleId`` +
        # ms timestamps). The response doesn't use the standard {"data": [...]}
        # envelope, so we can't share _get_pages — try common v1 shapes.
        all_trips: list[dict] = []
        url = f"{BASE_URL}/v1/fleet/trips"
        for vid in vehicle_ids:
            try:
                resp = self._session.get(
                    url, headers=self._headers(),
                    params={"vehicleId": vid, "startMs": _ms(start), "endMs": _ms(end)},
                    timeout=60,
                )
                if resp.status_code != 200:
                    log.warning("GET /v1/fleet/trips vehicleId=%s → HTTP %d", vid, resp.status_code)
                    continue
                payload = resp.json()
            except Exception as e:
                log.warning("GET /v1/fleet/trips vehicleId=%s → %s", vid, e)
                continue
            # Pull trips from any of the common v1 wrappers; flatten a vehicles[].trips
            # nesting if present.
            trips = payload.get("trips") or payload.get("vehicleTrips") or payload.get("data") or []
            if not trips:
                vehicles = payload.get("vehicles") or []
                if isinstance(vehicles, list):
                    for v in vehicles:
                        if isinstance(v, dict):
                            trips.extend(v.get("trips") or [])
            for t in trips:
                if isinstance(t, dict):
                    t.setdefault("vehicleId", vid)
            all_trips.extend(trips)
            time.sleep(0.05)
        log.info("Total trips: %d (from /v1/fleet/trips, per-vehicle)", len(all_trips))
        return all_trips

    def fetch_safety_events(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """Harsh braking, speeding, distraction, and other safety events."""
        log.info("Fetching safety events %s → %s…", start.date(), end.date())
        # /fleet/safety-events caps page size at 200 (PAGE_LIMIT of 512 -> HTTP 400).
        params = {"startTime": _iso(start), "endTime": _iso(end), "limit": 200}
        items = self._safe_get("/fleet/safety-events", params)
        log.info("Total safety events: %d", len(items))
        return items

    def fetch_hos_logs(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """ELD / Hours of Service log entries."""
        log.info("Fetching HOS logs %s → %s…", start.date(), end.date())
        params = {"startTime": _iso(start), "endTime": _iso(end)}
        for path in ["/fleet/hos/logs", "/fleet/drivers/hos-logs"]:
            items = self._safe_get(path, params)
            if items:
                log.info("Total HOS log entries: %d (from %s)", len(items), path)
                return items
        log.info("Total HOS log entries: 0")
        return []

    def fetch_hos_violations(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """HOS *violations* (driving/shift/break/cycle-limit breaches).

        Distinct from fetch_hos_logs: logs are raw duty-status entries; this
        returns the actual rule violations. Tries the documented endpoint plus
        fallbacks, matching the connector's endpoint-discovery pattern.
        Requires the token's Hours-of-Service scope.
        """
        log.info("Fetching HOS violations %s → %s…", start.date(), end.date())
        params = {"startTime": _iso(start), "endTime": _iso(end)}
        for path in [
            "/fleet/hos/violations",
            "/fleet/drivers/hos-violations",
            "/fleet/hos-violations",
        ]:
            items = self._safe_get(path, params)
            if items:
                log.info("Total HOS violations: %d (from %s)", len(items), path)
                return items
        log.info("Total HOS violations: 0")
        return []

    def fetch_dvirs(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """Driver Vehicle Inspection Reports (read).

        Uses GET /fleet/dvirs/history (Read DVIRs scope). The old POST /fleet/dvirs
        is the *create* endpoint and returns 401 'requires DVIRs write permissions'.
        """
        log.info("Fetching DVIRs %s → %s…", start.date(), end.date())
        # /fleet/dvirs/history rejects windows longer than 30 days, so page the
        # range in <=30-day chunks. (POST /fleet/dvirs is create-only -> 405 on GET.)
        all_items: list[dict] = []
        chunk = datetime.timedelta(days=29)
        win_start = start
        while win_start < end:
            win_end = min(win_start + chunk, end)
            all_items.extend(self._safe_get("/fleet/dvirs/history", {
                "startTime": _iso(win_start), "endTime": _iso(win_end), "limit": 200,
            }))
            win_start = win_end
        log.info("Total DVIRs: %d (from /fleet/dvirs/history)", len(all_items))
        return all_items

    def fetch_ifta(self, year: int, month: int) -> list[dict]:
        """IFTA per-vehicle fuel & mileage report via `GET /fleet/reports/ifta/vehicle`
        (singular). The endpoint takes ``year`` (int) and ``month`` as the **full
        month name** ("January".."December") — passing an integer returns 400
        "value of month must be one of \"January\", ..."."""
        month_name = datetime.date(year, month, 1).strftime("%B")
        log.info("Fetching IFTA %d-%s…", year, month_name)
        items = self._safe_get("/fleet/reports/ifta/vehicle", {"year": year, "month": month_name})
        if items:
            log.info("  IFTA: got %d records from /fleet/reports/ifta/vehicle", len(items))
            return items
        log.warning("IFTA: no data for %d-%s", year, month_name)
        return []
