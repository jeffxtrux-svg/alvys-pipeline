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
        """Current odometer, fuel %, engine state, GPS for all vehicles."""
        log.info("Fetching vehicle stats…")
        types = ",".join([
            "obdOdometerMeters",
            "fuelPercents",
            "engineStates",
            "gpsOdometerMeters",
            "syntheticEngineSeconds",
        ])
        items = self._safe_get("/fleet/vehicles/stats", {"types": types})
        log.info("Total vehicle stat records: %d", len(items))
        return items

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

    def fetch_trips(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """Trip records for all vehicles in the given UTC window."""
        log.info("Fetching trips %s → %s…", start.date(), end.date())
        params = {"startTime": _iso(start), "endTime": _iso(end)}
        for path in ["/fleet/vehicles/trips", "/fleet/trips"]:
            items = self._safe_get(path, params)
            if items:
                log.info("Total trips: %d (from %s)", len(items), path)
                return items
        log.info("Total trips: 0")
        return []

    def fetch_safety_events(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """Harsh braking, speeding, distraction, and other safety events."""
        log.info("Fetching safety events %s → %s…", start.date(), end.date())
        params = {"startTime": _iso(start), "endTime": _iso(end)}
        for path in ["/fleet/safety/events", "/safety/events"]:
            items = self._safe_get(path, params)
            if items:
                log.info("Total safety events: %d (from %s)", len(items), path)
                return items
        log.info("Total safety events: 0")
        return []

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

    def fetch_dvirs(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """Driver Vehicle Inspection Reports (pre/post-trip inspections)."""
        log.info("Fetching DVIRs %s → %s…", start.date(), end.date())
        params = {"startTime": _iso(start), "endTime": _iso(end)}
        for path in ["/fleet/dvirs", "/fleet/maintenance/dvirs"]:
            items = self._safe_get(path, params)
            if items:
                log.info("Total DVIRs: %d (from %s)", len(items), path)
                return items
        log.info("Total DVIRs: 0")
        return []

    def fetch_ifta(self, year: int, month: int) -> list[dict]:
        """IFTA fuel & mileage report for a given month. Tries multiple known paths."""
        log.info("Fetching IFTA %d-%02d…", year, month)
        params = {"year": year, "month": month}
        for path in [
            "/fleet/reports/ifta/vehicles",
            "/fleet/ifta/vehicle-reports",
            "/fleet/ifta/summaries",
        ]:
            items = self._safe_get(path, params)
            if items:
                log.info("  IFTA: got %d records from %s", len(items), path)
                return items
        log.warning("IFTA: no data from any known endpoint for %d-%02d", year, month)
        return []
