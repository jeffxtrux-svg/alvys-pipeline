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

    # Class-level counter so we only log the first few _get_one failures
    # per process — enough to diagnose endpoint issues without spamming the
    # log for legitimate "this id doesn't exist" cases.
    _GET_ONE_LOG_BUDGET = 3

    def _get_one(self, path: str, params: dict | None = None) -> dict | None:
        """Single-resource GET. Returns the `data` dict from the response,
        or None on any HTTP error. Used by detail endpoints (e.g. fetching
        an individual safety event to pick up coachedBy)."""
        try:
            url = f"{BASE_URL}{path}"
            resp = self._session.get(
                url, headers=self._headers(), params=(params or {}), timeout=30
            )
            if resp.status_code != 200:
                if SamsaraClient._GET_ONE_LOG_BUDGET > 0:
                    SamsaraClient._GET_ONE_LOG_BUDGET -= 1
                    log.warning("DIAG _get_one %s → HTTP %d: %s",
                                path, resp.status_code, resp.text[:200])
                return None
            payload = resp.json()
            d = payload.get("data")
            if not isinstance(d, dict):
                if SamsaraClient._GET_ONE_LOG_BUDGET > 0:
                    SamsaraClient._GET_ONE_LOG_BUDGET -= 1
                    log.warning("DIAG _get_one %s → 200 but no data dict; "
                                "payload keys=%s", path, list(payload.keys()))
            return d if isinstance(d, dict) else None
        except Exception as e:
            if SamsaraClient._GET_ONE_LOG_BUDGET > 0:
                SamsaraClient._GET_ONE_LOG_BUDGET -= 1
                log.warning("DIAG _get_one %s → exception: %s", path, e)
            return None

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

    def fetch_users(self) -> list[dict]:
        """Organization users (admins/managers/coaches). Used by the
        scorecard to resolve `coachedBy.id` → coach name on SafetyEvents
        — Samsara doesn't surface `coachedBy.name` directly in our
        tenant's response, so we look it up from the user directory.

        Tries `/users` (current) and falls back to `/fleet/users` (older
        path) before returning empty; either failure is fail-soft so a
        missing scope can't kill the refresh."""
        log.info("Fetching users (org admins/coaches)…")
        for path in ("/users", "/fleet/users"):
            items = self._safe_get(path)
            if items:
                log.info("Total users (%s): %d", path, len(items))
                return items
        log.info("Total users: 0 (no /users path returned data)")
        return []

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
        """Active OBD diagnostic fault codes (DTC / check-engine / warning lights).

        Samsara retired the `nativeObdDtcCodes` stat type from
        /fleet/vehicles/stats in 2025.  The endpoint returns 400 for that type,
        which is caught here and logged at INFO so the alerts job stays green
        while DTC data is unavailable.
        """
        log.info("Fetching active fault codes…")
        try:
            items = self._get_pages(
                "/fleet/vehicles/stats", {"types": "nativeObdDtcCodes"}
            )
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            msg = ""
            try:
                msg = exc.response.json().get("message", "")
            except Exception:
                pass
            if code == 400 and "nativeObdDtcCodes" in msg:
                log.info(
                    "DTC fault-code endpoint returned 400 (stat type retired by Samsara)"
                    " — skipping DTC check."
                )
            else:
                log.warning("GET /fleet/vehicles/stats → HTTP %s — skipping DTC check.", code)
            items = []
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
        """Harsh braking, speeding, distraction, and other safety events.

        The list endpoint does NOT include coachedBy.{id,name} in its
        response (confirmed via Samsara support 2026-06-08). What it
        DOES carry is `assignedCoach` — the user id of whoever's
        assigned to coach the event. samsara_main resolves that against
        the Users sheet to surface the coach name on the scorecard.

        See: https://developers.samsara.com/reference/getsafetyeventsv2
             docs/knowledge-base/samsara-coaching-attribution.md
        """
        log.info("Fetching safety events %s → %s…", start.date(), end.date())
        # /fleet/safety-events caps page size at 200 (PAGE_LIMIT of 512 -> HTTP 400).
        params = {"startTime": _iso(start), "endTime": _iso(end), "limit": 200}
        items = self._safe_get("/fleet/safety-events", params)
        log.info("Total safety events: %d", len(items))
        # Diagnostic: confirm assignedCoach shows up. Samsara support
        # said it's available on the v2 list response; on first probe
        # the default response returned it on 0/97 events. Try opting
        # in via include= and dump full keys of a coached event so we
        # can see what the API actually exposes for this tenant.
        if items:
            _with = sum(1 for r in items if isinstance(r, dict) and r.get("assignedCoach"))
            log.info("DIAG assignedCoach present on %d / %d safety events (default response)",
                     _with, len(items))
            # Dump top-level keys of a coached event (more likely to
            # carry coach attribution than an un-acted-on event).
            _coached_ev = next(
                (r for r in items if isinstance(r, dict)
                 and str(r.get("coachingState", "")).lower() in ("coached", "dismissed", "recognized")),
                None,
            )
            if _coached_ev:
                _keys = sorted(_coached_ev.keys())
                log.info("DIAG coached-event keys (default response): %s", _keys)
                # Surface any keys mentioning coach/assign/user/actor —
                # in case Samsara renamed the field.
                _suspect = [k for k in _keys
                            if any(t in k.lower() for t in ("coach", "assign", "actor", "user", "review"))]
                if _suspect:
                    log.info("DIAG coach-shaped keys on coached event: %s", _suspect)
                    for k in _suspect:
                        log.info("DIAG   %s = %r", k, _coached_ev.get(k))
                _ev_id = _coached_ev.get("id")
                # Probe 1: opt into assignedCoach via include= param.
                if _ev_id:
                    for _inc in ("assignedCoach", "coachedBy", "assignedCoach,coachedBy"):
                        _probe = self._safe_get(
                            "/fleet/safety-events",
                            {"startTime": _iso(start), "endTime": _iso(end),
                             "limit": 5, "include": _inc},
                        )
                        if _probe:
                            _p = _probe[0]
                            _has = any(k for k in _p.keys()
                                       if any(t in k.lower() for t in ("coach", "assign")))
                            log.info("DIAG include=%s → keys=%s has_coach_key=%s",
                                     _inc, sorted(_p.keys()), _has)
            if _with:
                _sample = next((r for r in items if r.get("assignedCoach")), None)
                if _sample:
                    log.info("DIAG sample assignedCoach value: %r",
                             _sample.get("assignedCoach"))
        return items

    def fetch_safety_event_detail(self, event_id: str) -> dict | None:
        """Single safety event detail — picks up `coachedBy` and other
        fields the list endpoint omits. Tries the v2 path first then the
        v1 fallback. Returns None on any error so the caller can skip
        and keep going.

        NOTE: confirmed dead end on this tenant — both endpoints return
        HTTP 404 for every event id (composite ids of the form
        vehicleId-timestamp aren't accepted by either path). Kept in
        place in case Samsara re-enables it for our account, but the
        coach-name path runs through fetch_safety_audit_log() instead.
        """
        if not event_id:
            return None
        # /fleet/safety-events/{id} is the documented v2 detail endpoint.
        rec = self._get_one(f"/fleet/safety-events/{event_id}")
        if rec is not None:
            return rec
        # v1 fallback in case the v2 detail endpoint isn't enabled for
        # this tenant — same shape but under /v1/fleet/safety/events.
        return self._get_one(f"/v1/fleet/safety/events/{event_id}")

    def fetch_safety_audit_log(self, start_iso: str | None = None) -> list[dict]:
        """Probe the safety-events audit-log feed — Samsara's documented
        change-log for safety events. Likely carries the userId/userName
        that took each action (coached / dismissed / recognized), keyed
        to the event id. URL:
            GET /fleet/safety-events/audit-logs/feed?startTime=ISO

        See:
            https://developers.samsara.com/changelog/get-fleetsafety-eventsaudit-logsfeed-...
            https://developers.samsara.com/reference/getsafetyactivityeventfeed

        First call uses the documented v2 path; if 404 (endpoint isn't
        enabled for our tenant), tries the legacy v1 path. Returns the
        raw list. Diagnostic logging in the caller dumps the first
        record's keys so we can confirm the response shape before
        wiring it into the daily flatten.
        """
        params = {}
        if start_iso:
            params["startTime"] = start_iso
        items = self._safe_get("/fleet/safety-events/audit-logs/feed", params)
        if items:
            log.info("Audit log: %d records from v2 endpoint", len(items))
            return items
        # v1 legacy fallback
        items = self._safe_get("/v1/fleet/safety/events/audit/feed", params)
        if items:
            log.info("Audit log: %d records from v1 fallback", len(items))
        return items

    def fetch_safety_events_stream(self, start_iso: str | None = None) -> list[dict]:
        """Probe the v2 'Get Safety Events Stream' endpoint — successor
        to the legacy list endpoint. Stream endpoints typically carry
        richer payloads than list endpoints, so this might include the
        coachedBy field that /fleet/safety-events omits.

        See: https://developers.samsara.com/reference/getsafetyeventsv2stream

        Tries several path variants since Samsara isn't consistent across
        v2 endpoints. Returns the first non-empty response.
        """
        params = {}
        if start_iso:
            params["startTime"] = start_iso
        for path in ("/fleet/safety-events/stream",
                     "/v2/fleet/safety-events",
                     "/fleet/safety/events/stream"):
            items = self._safe_get(path, params)
            if items:
                log.info("Stream: %d records from %s", len(items), path)
                return items
        log.info("Stream: all probe paths returned empty")
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

    def send_driver_messages(self, driver_ids: list[str], text: str) -> dict | None:
        """Send a message to one or more drivers' Samsara Driver App inbox.

        Endpoint: POST /v1/fleet/messages
            https://developers.samsara.com/reference/v1createmessages

        Token requires the **Write Messages** scope (Driver Workflow
        category in the API token settings). If the scope is missing the
        call returns 403 and we log + return None so the caller can
        carry on with the rest of the run.

        Returns the parsed JSON body on success, None on any failure.
        """
        if not driver_ids or not text:
            return None
        # /v1/ endpoint takes numeric ids; coerce to int where possible
        # since some downstream code passes them as strings.
        _ids: list = []
        for d in driver_ids:
            try:
                _ids.append(int(d))
            except (TypeError, ValueError):
                _ids.append(d)
        url = f"{BASE_URL}/v1/fleet/messages"
        try:
            resp = self._session.post(
                url, headers=self._headers(), timeout=30,
                json={"driverIds": _ids, "text": text},
            )
            if resp.status_code >= 400:
                log.warning("POST /v1/fleet/messages → HTTP %d: %s",
                            resp.status_code, resp.text[:200])
                return None
            log.info("Sent driver message to %d driver(s)", len(_ids))
            return resp.json() if resp.text else {}
        except Exception as e:
            log.warning("POST /v1/fleet/messages → exception: %s", e)
            return None

    def fetch_hos_daily_logs(self, start: datetime.datetime, end: datetime.datetime) -> list[dict]:
        """Per-driver per-day HOS summaries — surfaces log *certification*
        status (the Samsara dashboard's "Missing Certifications" tab).

        Endpoint: GET /fleet/hos/daily-logs
            https://developers.samsara.com/reference/gethosdailylogs

        Each record represents one driver-day with a `certifiedAt` (or
        equivalent) field; missing means the driver hasn't certified
        that day's logs yet. Bounded to start/end dates.

        Samsara enforces ``endDate <= current date`` evaluated in the
        tenant's primary timezone. Late-evening runs that pass a UTC
        ``now`` of tomorrow-already (e.g. 9pm Central = next-day UTC)
        get HTTP 400. Clamp endDate to today in America/Chicago to
        match XFreight's tenant timezone and avoid the silent placeholder
        write that follows when the call comes back empty.
        """
        from zoneinfo import ZoneInfo
        chi_today = datetime.datetime.now(ZoneInfo("America/Chicago")).date()
        end_date = min(end.date(), chi_today)
        log.info("Fetching HOS daily logs %s → %s (end clamped from %s)…",
                 start.date(), end_date, end.date())
        params = {
            "startDate": start.date().isoformat(),
            "endDate": end_date.isoformat(),
        }
        items = self._safe_get("/fleet/hos/daily-logs", params)
        log.info("Total HOS daily logs: %d", len(items))
        if items:
            _r0 = items[0]
            if isinstance(_r0, dict):
                log.info("DIAG HOS daily-log keys: %s", sorted(_r0.keys()))
                _cert_keys = {k: _r0.get(k) for k in _r0.keys()
                              if any(t in k.lower() for t in ("cert", "sign", "approve"))}
                log.info("DIAG HOS daily-log cert-shaped fields: %s", _cert_keys)
                # Prior probe showed no top-level cert flag; the cert
                # status is almost certainly inside logMetaData. Dump it
                # in full so we can wire whatever the actual flag is.
                _meta = _r0.get("logMetaData")
                log.info("DIAG HOS daily-log full first record (truncated): %r",
                         str(_r0)[:1000])
                if isinstance(_meta, dict):
                    log.info("DIAG HOS daily-log logMetaData keys: %s",
                             sorted(_meta.keys()))
                    log.info("DIAG HOS daily-log logMetaData full: %r",
                             str(_meta)[:800])
        return items

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
                # Diagnostic: dump first record keys + any time-shaped values
                # so we can confirm the scorecard's date column lookup
                # (`violationStartTime` / `startTime` / `time`) actually
                # matches the live response shape. Prior probe showed
                # top-level is just {"violations": [...]} — so dump the
                # full record + the first nested violation's keys/values.
                _r0 = items[0]
                if isinstance(_r0, dict):
                    log.info("DIAG HOS violation keys: %s", sorted(_r0.keys()))
                    log.info("DIAG HOS violation full record (truncated): %r",
                             str(_r0)[:800])
                    _viol_list = _r0.get("violations") or []
                    if isinstance(_viol_list, list) and _viol_list:
                        _v0 = _viol_list[0]
                        if isinstance(_v0, dict):
                            log.info("DIAG HOS nested violation[0] keys: %s",
                                     sorted(_v0.keys()))
                            log.info("DIAG HOS nested violation[0] full: %r",
                                     str(_v0)[:600])
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

    def fetch_engine_state_history(self, start: datetime.datetime,
                                   end: datetime.datetime) -> list[dict]:
        """Per-vehicle engine state transitions via `GET /fleet/vehicles/stats/history`.

        Returns the raw stat-history records (one per vehicle) with an
        ``engineStates`` array of `{time, value}` transitions across the window.
        Callers aggregate seconds in each state (Idle / On / Off) per vehicle.

        Samsara caps the request window — page through in <=7-day chunks to stay
        well under the limit. The endpoint accepts ms-since-epoch timestamps.
        """
        log.info("Fetching engine state history (%s -> %s)…", start.date(), end.date())
        all_items: dict[str, dict] = {}
        chunk = datetime.timedelta(days=7)
        cur = start
        while cur < end:
            chunk_end = min(cur + chunk, end)
            params = {
                "types": "engineStates",
                "startTime": cur.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endTime": chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            try:
                items = self._safe_get("/fleet/vehicles/stats/history", params)
            except Exception as exc:
                log.warning("Engine state history chunk %s -> %s failed: %s",
                            cur.date(), chunk_end.date(), exc)
                cur = chunk_end
                continue
            # Merge transitions per vehicle id across chunks.
            for rec in items or []:
                vid = rec.get("id")
                if not vid:
                    continue
                slot = all_items.setdefault(vid, {"id": vid, "name": rec.get("name"),
                                                  "engineStates": []})
                states = (rec.get("engineStates") or [])
                if isinstance(states, list):
                    slot["engineStates"].extend(states)
                # Preserve other top-level keys (vehicle name, etc.) if newer chunk has them
                if not slot.get("name"):
                    slot["name"] = rec.get("name")
            cur = chunk_end
        log.info("Total vehicles with engine state history: %d", len(all_items))
        return list(all_items.values())

    def _raw_get_json(self, path: str, params: dict | None = None) -> dict | None:
        """Single GET that returns the parsed JSON body (dict) or None on any
        non-200 / error. Unlike _get_pages it does NOT assume a paginated
        ``{"data": [...]}`` envelope — used by endpoints (like the v1 safety
        score) that return a bare object."""
        url = f"{BASE_URL}{path}"
        try:
            resp = self._session.get(url, headers=self._headers(),
                                     params=params or {}, timeout=120)
            if resp.status_code != 200:
                log.warning("GET %s → HTTP %d: %s", path, resp.status_code, resp.text[:200])
                return None
            return resp.json()
        except Exception as e:
            log.warning("GET %s → %s — skipping", path, e)
            return None

    @staticmethod
    def _extract_score_record(payload: dict | None) -> dict | None:
        """Pull the per-driver score object out of whatever envelope the API
        returned. Handles bare ``{"safetyScore": ...}`` (v1), ``{"data": {...}}``
        and ``{"data": [{...}]}`` (modern) shapes."""
        if not isinstance(payload, dict):
            return None
        data = payload.get("data", payload)
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) else None

    def fetch_driver_safety_scores(self, driver_ids: list[str],
                                   start: datetime.datetime,
                                   end: datetime.datetime) -> list[dict]:
        """Per-driver composite safety score.

        Samsara has shuffled this endpoint's path over API versions — the
        plain ``/fleet/drivers/{id}/safety/score`` now returns a bare
        ``404 page not found`` for every driver. So we follow the codebase's
        "discover by fallback" pattern: probe a list of candidate path
        templates with the first driver, keep whichever one actually returns
        a score, then loop the rest of the drivers on that path.

        Returns the score JSON per driver with ``driverId`` stamped in so the
        caller can match back to the Drivers sheet. Fail-soft: if no candidate
        works the list comes back empty and the brief shows "n/a" rather than
        crashing.
        """
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        # (path_template, params_builder) candidates, highest-confidence first.
        # v1 is the long-stable legacy endpoint (bare object, startMs/endMs);
        # the non-v1 path is kept for forward-compat if Samsara restores it.
        candidates = [
            ("/v1/fleet/drivers/{id}/safety/score",
             lambda did: {"startMs": start_ms, "endMs": end_ms}),
            ("/fleet/drivers/{id}/safety/score",
             lambda did: {"startMs": start_ms, "endMs": end_ms}),
        ]
        log.info("Fetching driver safety scores for %d drivers (%s -> %s)…",
                 len(driver_ids), start.date(), end.date())
        if not driver_ids:
            log.info("Total driver safety score records: 0 (no drivers)")
            return []

        # --- Discover a working path with the first driver ---
        probe_id = driver_ids[0]
        chosen = None
        first_rec = None
        for tmpl, build in candidates:
            payload = self._raw_get_json(tmpl.format(id=probe_id), build(probe_id))
            rec = self._extract_score_record(payload)
            if rec is not None:
                chosen = (tmpl, build)
                first_rec = rec
                log.info("Driver safety score: using endpoint %s", tmpl)
                break
        if chosen is None:
            log.warning("Driver safety score: no candidate endpoint returned data "
                        "(tried %s) — scores unavailable this run",
                        ", ".join(c[0] for c in candidates))
            return []

        tmpl, build = chosen
        out: list[dict] = []
        first_rec["driverId"] = probe_id
        out.append(first_rec)
        for did in driver_ids[1:]:
            rec = self._extract_score_record(
                self._raw_get_json(tmpl.format(id=did), build(did)))
            if not rec:
                continue
            rec["driverId"] = did
            out.append(rec)
            time.sleep(0.05)  # stay under the rate limit
        log.info("Total driver safety score records: %d", len(out))
        return out

    def fetch_coaching_sessions(self) -> list[dict]:
        """All coaching sessions (pending + completed).

        Includes self-coaching and manager-led sessions with driver name,
        behaviors, status, assignedAt, and dueAt. Returns empty list if the
        coaching module is not enabled on this Samsara account.
        """
        log.info("Fetching coaching sessions…")
        items = self._safe_get("/coaching/sessions")
        log.info("Total coaching sessions: %d", len(items))
        return items

    def fetch_training_assignments(self) -> list[dict]:
        """All driver training assignments (any status).

        Returns driver name, course name, assignedAt, dueAt, completedAt,
        and status (notStarted/inProgress/completed). Returns empty list if
        the training module is not enabled on this Samsara account.
        """
        log.info("Fetching training assignments…")
        items = self._safe_get("/training/assignments")
        log.info("Total training assignments: %d", len(items))
        return items
