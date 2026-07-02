"""Detention alerts — Teams card when a driver sits at a pickup/delivery 2+ hours.

Detection is from Alvys stop timestamps: a stop with ArrivedAt set and no
DepartedAt means the driver is on site. When time on the detention clock
crosses the 2-hour free-time window (industry standard — the same convention
settlement_checker._detect_detention_hours already uses) a card posts to the
Operations Teams channel with everything needed to pursue detention with the
customer: customer/broker name, driver, truck, load #, facility + city,
appointment vs. actual arrival, time on site so far, and when the free-time
window ended.

Eligibility (owner rule, 2026-07-02): a LATE arrival voids detention — no
card fires.
  - APPT stop: the driver must arrive at/before the appointment time.
  - FCFS / WINDOW stop: the driver must arrive by the window End. Open-ended
    FCFS (no End) and date-only windows have no hard deadline — can't be late.
  - Early arrival never voids, but the detention clock starts at the
    appointment / window-open time, not at the early arrival — you can't bill
    a customer for a driver waiting before the dock was due to see him.

When the stop closes out (DepartedAt gets set) a follow-up card posts the
final arrive → depart times, total time on site, and the billable detention
(time beyond the free window) so the invoice can be raised while the event
is fresh.

State (which stops have already been alerted) lives in detention_state.json
in the same OneDrive folder as eta_state.json, so the every-15-min ETA run
stays idempotent: one alert card per stop crossing the threshold, one
closeout card when it departs — never a repeat.

Called from src.xfreight_etas.main() (fail-soft: a detention error never
blocks the ETA publish). Not a standalone entry point.

Env:
  TEAMS_DETENTION_WEBHOOK (optional)  — dedicated webhook for detention cards;
                                        falls back to TEAMS_OPERATIONS_WEBHOOK
                                        (the Operations channel). Selection
                                        happens in xfreight_etas.main().
  DETENTION_THRESHOLD_MIN (optional)  — free-time minutes before a stop counts
                                        as detention. Default 120.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("detention_alerts")

CT = ZoneInfo("America/Chicago")
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_STATE_FILE = "detention_state.json"
_FREE_TIME_MIN_DEFAULT = 120     # 2h free time — matches settlement_checker
# An arrival this old with no departure is a data gap (dispatch never marked
# the stop departed), not a live detention event — mirrors the ETA tracker's
# stale-appointment guard. Skipped stops are logged, never alerted.
_STALE_ARRIVAL_HOURS = 24


# ----------------------------------------------------------------------
# Small local helpers (kept local — xfreight_etas imports this module, so
# importing back from it would be circular)
# ----------------------------------------------------------------------
def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _fmt_dt_ct(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(CT).strftime("%a %b %d, %I:%M%p").replace("AM", "am").replace("PM", "pm")


def _fmt_mins(minutes: int | None) -> str:
    if minutes is None:
        return "—"
    minutes = max(0, int(minutes))
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def _is_midnight(iso: str | None) -> bool:
    dt = _parse_iso(iso)
    return dt is not None and (dt.hour, dt.minute, dt.second) == (0, 0, 0)


def _is_date_only_window(begin: str | None, end: str | None) -> bool:
    """Alvys emits date-only stop windows as Begin==End==00:00:00 local."""
    if not end or not _is_midnight(end):
        return False
    return (not begin) or (begin == end) or _is_midnight(begin)


def _is_brokered(load: dict) -> bool:
    return str(load.get("BrokerageStatus") or "").lower() == "brokered"


def _g(d: dict | None, *path: str, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


# ----------------------------------------------------------------------
# Stop schedule helpers
# ----------------------------------------------------------------------
def _stop_arrival_deadline(stop: dict) -> datetime | None:
    """Latest on-time arrival for detention eligibility. Arriving after this
    VOIDS detention (owner rule — customers don't pay when the driver was
    late). APPT → the appointment time; WINDOW/FCFS → the window End when one
    exists. None = can't be late (open-ended FCFS, window with no End,
    date-only window — a calendar date carries no hard time to be late by)."""
    stype = (stop.get("ScheduleType") or "").upper()
    if stype == "APPT":
        return _parse_iso(stop.get("AppointmentDate"))
    win = stop.get("StopWindow") or {}
    begin, end = win.get("Begin"), win.get("End")
    if _is_date_only_window(begin, end):
        return None
    return _parse_iso(end) if end else None


def _stop_scheduled_open(stop: dict) -> datetime | None:
    """Earliest the detention clock can start: the APPT time, or the window
    Begin. A driver who arrives before this waits on his own time — free time
    counts from here, not from the early arrival."""
    stype = (stop.get("ScheduleType") or "").upper()
    if stype == "APPT":
        return _parse_iso(stop.get("AppointmentDate"))
    win = stop.get("StopWindow") or {}
    begin, end = win.get("Begin"), win.get("End")
    if _is_date_only_window(begin, end):
        return None
    return _parse_iso(begin) if begin else None


def _stop_appt_display(stop: dict) -> str:
    """Human string for the Appt fact on the card."""
    stype = (stop.get("ScheduleType") or "").upper()
    if stype == "APPT" and stop.get("AppointmentDate"):
        return _fmt_dt_ct(_parse_iso(stop.get("AppointmentDate"))) or "—"
    win = stop.get("StopWindow") or {}
    begin, end = win.get("Begin"), win.get("End")
    if _is_date_only_window(begin, end):
        d = _parse_iso(end or begin)
        return f"{d:%a %b %d} (any time)" if d else "—"
    b, e = _parse_iso(begin), _parse_iso(end)
    if b and e and begin != end:
        return f"{_fmt_dt_ct(b)} – {_fmt_dt_ct(e)}"
    one = e or b or _parse_iso(stop.get("AppointmentDate"))
    return _fmt_dt_ct(one) or "—"


def _stop_type_label(stop: dict, idx: int, n_stops: int) -> str:
    raw = str(stop.get("StopType") or "").strip()
    if raw:
        low = raw.lower()
        if low == "pickup":
            return "Pickup"
        if low in ("delivery", "drop", "dropoff", "drop off", "consignee"):
            return "Delivery"
        return raw
    if idx == 0:
        return "Pickup"
    if idx == n_stops - 1:
        return "Delivery"
    return "Stop"


# ----------------------------------------------------------------------
# Trip join (truck / driver / sales agent for a load)
# ----------------------------------------------------------------------
def _trip_context(load: dict, trips_by_load: dict, trucks_by_id: dict | None,
                  drivers_by_id: dict | None, users_by_id: dict | None) -> dict:
    load_num = str(load.get("LoadNumber") or "")
    trip = trips_by_load.get(load_num) if load_num else None
    truck_name = None
    driver_name = None
    if trip:
        truck_obj = trip.get("Truck") or {}
        if isinstance(truck_obj, dict):
            truck_name = (truck_obj.get("TruckNum") or truck_obj.get("TruckNumber")
                          or truck_obj.get("Number") or truck_obj.get("Name"))
            if not truck_name and trucks_by_id:
                tid = truck_obj.get("Id")
                if tid:
                    truck_name = trucks_by_id.get(str(tid))
        d1 = trip.get("Driver1") or {}
        if isinstance(d1, dict):
            driver_name = (d1.get("FullName") or d1.get("Name") or d1.get("DisplayName"))
            if not driver_name and drivers_by_id:
                did = d1.get("Id")
                if did:
                    driver_name = drivers_by_id.get(str(did))
    return {
        "truck_name": str(truck_name) if truck_name else "",
        "driver_name": str(driver_name or ""),
        "sales_agent": (users_by_id or {}).get(
            str(load.get("CustomerSalesAgentId") or "")) or "",
    }


# ----------------------------------------------------------------------
# Detection
# ----------------------------------------------------------------------
def find_detention_stops(loads: list[dict], trips_by_load: dict,
                         trucks_by_id: dict | None = None,
                         drivers_by_id: dict | None = None,
                         users_by_id: dict | None = None,
                         now: datetime | None = None,
                         free_time_min: int = _FREE_TIME_MIN_DEFAULT) -> list[dict]:
    """All stops currently in billable detention: ArrivedAt set, no
    DepartedAt, driver arrived ON TIME (a late arrival voids detention — no
    card), and detention-clock time ≥ free_time_min. The clock starts at the
    later of arrival and the appointment / window-open time. Arrivals older
    than _STALE_ARRIVAL_HOURS are data gaps (never marked departed), not live
    events — skipped with a log line."""
    now = now or datetime.now(timezone.utc)
    rows: list[dict] = []
    for load in loads:
        load_no = str(load.get("LoadNumber") or load.get("Number") or "")
        if not load_no:
            continue
        stops = load.get("Stops") or []
        ctx: dict | None = None
        for idx, stop in enumerate(stops):
            arrived = _parse_iso(stop.get("ArrivedAt"))
            if arrived is None or stop.get("DepartedAt"):
                continue
            dwell_min = int((now - arrived).total_seconds() // 60)
            if dwell_min > _STALE_ARRIVAL_HOURS * 60:
                log.info("detention: load %s stop %d arrived %.1fh ago with no "
                         "departure — stale data, not alerting", load_no, idx,
                         dwell_min / 60)
                continue
            deadline = _stop_arrival_deadline(stop)
            if deadline and arrived > deadline:
                # Late arrival voids detention: an APPT missed, or an
                # FCFS/WINDOW arrival after the window closed. Never card.
                log.info("detention: load %s stop %d — driver arrived %s, after "
                         "the %s deadline %s; detention void, not alerting",
                         load_no, idx, _fmt_dt_ct(arrived),
                         (stop.get("ScheduleType") or "stop"), _fmt_dt_ct(deadline))
                continue
            open_dt = _stop_scheduled_open(stop)
            clock_start = max(arrived, open_dt) if open_dt else arrived
            clock_min = int((now - clock_start).total_seconds() // 60)
            if clock_min < free_time_min:
                continue
            if ctx is None:
                ctx = _trip_context(load, trips_by_load, trucks_by_id,
                                    drivers_by_id, users_by_id)
            rows.append({
                "key": f"{load_no}#{idx}",
                "load_no": load_no,
                "stop_idx": idx,
                "customer_name": load.get("CustomerName") or "",
                "brokered": _is_brokered(load),
                "truck_name": ctx["truck_name"],
                "driver_name": ctx["driver_name"],
                "sales_agent": ctx["sales_agent"],
                "stop_type": _stop_type_label(stop, idx, len(stops)),
                "facility": _g(stop, "CompanyName") or _g(stop, "Address", "Street") or "",
                "city": _g(stop, "Address", "City") or "",
                "stop_state": _g(stop, "Address", "State") or "",
                "appt_display": _stop_appt_display(stop),
                "arrived_dt": arrived,
                "clock_start_dt": clock_start,
                "early_arrival": clock_start > arrived,
                "dwell_min": dwell_min,
                "detention_min": clock_min - free_time_min,
                "free_end_dt": clock_start + timedelta(minutes=free_time_min),
            })
    return rows


# ----------------------------------------------------------------------
# Card builders
# ----------------------------------------------------------------------
def _mention_block(users: list[dict]) -> tuple[dict | None, list[dict]]:
    if not users:
        return None, []
    mention_text = ("🔔 " + " ".join(f"<at>{u['name']}</at>" for u in users)
                    + " — detention to collect")
    block = {"type": "TextBlock", "text": mention_text, "wrap": True,
             "size": "Small", "weight": "Bolder"}
    entities = [{"type": "mention", "text": f"<at>{u['name']}</at>",
                 "mentioned": {"id": u["id"], "name": u["name"]}} for u in users]
    return block, entities


def _row_facts(r: dict) -> list[dict]:
    loc = f"{r.get('city', '')}, {r.get('stop_state', '')}".strip(", ")
    stop_desc = " — ".join(x for x in (r.get("stop_type"), r.get("facility")) if x) or "—"
    arrived = _fmt_dt_ct(r.get("arrived_dt")) or "—"
    if r.get("early_arrival"):
        arrived += "  (early — clock from appt/window open)"
    return [
        {"title": "Load #", "value": str(r.get("load_no") or "—")},
        {"title": "Broker" if r.get("brokered") else "Customer",
         "value": r.get("customer_name") or "—"},
        {"title": "Stop", "value": stop_desc},
        {"title": "Location", "value": loc or "—"},
        {"title": "Appt", "value": r.get("appt_display") or "—"},
        {"title": "Arrived", "value": arrived},
        {"title": "Sales Agent", "value": r.get("sales_agent") or "—"},
    ]


def build_detention_card(rows: list[dict], free_time_min: int,
                         mention_users: list[dict] | None = None) -> dict:
    """Adaptive Card for stops that just crossed the free-time window."""
    mention_block, entities = _mention_block(mention_users or [])
    free_h = free_time_min / 60
    free_str = f"{free_h:g}h"
    body: list[dict] = [
        {"type": "TextBlock", "text": "⏱️ Detention Alert — Collect Detention",
         "weight": "Bolder", "size": "Large", "color": "Attention", "wrap": True},
        {"type": "TextBlock",
         "text": (f"{len(rows)} driver(s) on site past the {free_str} free-time "
                  f"window, all arrived on time (late arrivals never fire this "
                  f"card) — document the times below and pursue detention with "
                  f"the customer — as of {datetime.now(CT):%I:%M %p CT}"),
         "size": "Small", "spacing": "None", "wrap": True},
    ]
    if mention_block:
        body.append(mention_block)
    for i, r in enumerate(sorted(rows, key=lambda x: -(x.get("dwell_min") or 0))):
        p = f"d{i}"
        items: list[dict] = [
            {
                "type": "ColumnSet",
                "columns": [
                    {"type": "Column", "width": "stretch",
                     "items": [{"type": "TextBlock",
                                "text": (f"**Truck {r.get('truck_name') or '—'}** — "
                                         f"{r.get('driver_name') or '—'}"),
                                "wrap": True}]},
                    {"type": "Column", "width": "auto",
                     "items": [{"type": "TextBlock",
                                "text": f"**{_fmt_mins(r.get('dwell_min'))} on site**",
                                "color": "Attention", "weight": "Bolder",
                                "wrap": False}]},
                ],
            },
            {"type": "FactSet", "spacing": "Small",
             "facts": _row_facts(r) + [
                 {"title": "Clock started", "value": _fmt_dt_ct(r.get("clock_start_dt")) or "—"},
                 {"title": "Free time ended", "value": _fmt_dt_ct(r.get("free_end_dt")) or "—"},
                 {"title": "Detention so far", "value": _fmt_mins(r.get("detention_min"))},
             ]},
            {"type": "TextBlock",
             "text": "✅ On-time arrival — detention is billable.",
             "wrap": True, "size": "Small", "color": "Good", "spacing": "Small"},
        ]
        items.extend([
            {"type": "ActionSet", "spacing": "Small", "actions": [
                {"type": "Action.ToggleVisibility", "title": "📞 Notified Customer",
                 "targetElements": [f"{p}_cust"]},
                {"type": "Action.ToggleVisibility", "title": "🧾 Detention Billed",
                 "targetElements": [f"{p}_bill"]},
                {"type": "Action.ToggleVisibility", "title": "🚫 Not Billable",
                 "targetElements": [f"{p}_skip"]},
            ]},
            {"type": "TextBlock", "id": f"{p}_cust", "isVisible": False,
             "text": "✅ Customer notified", "color": "Good",
             "size": "Small", "spacing": "None", "wrap": False},
            {"type": "TextBlock", "id": f"{p}_bill", "isVisible": False,
             "text": "✅ Detention billed", "color": "Good",
             "size": "Small", "spacing": "None", "wrap": False},
            {"type": "TextBlock", "id": f"{p}_skip", "isVisible": False,
             "text": "🚫 Marked not billable", "color": "Warning",
             "size": "Small", "spacing": "None", "wrap": False},
        ])
        body.append({"type": "Container", "separator": True,
                     "spacing": "Medium", "items": items})
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "msteams": {"width": "Full", **({"entities": entities} if entities else {})},
    }


def build_closeout_card(rows: list[dict], free_time_min: int) -> dict:
    """Adaptive Card for previously-alerted stops the driver has now left —
    the final arrive/depart times and billable detention for the invoice."""
    free_h = free_time_min / 60
    body: list[dict] = [
        {"type": "TextBlock", "text": "🧾 Detention Closeout — Ready to Bill",
         "weight": "Bolder", "size": "Large", "color": "Accent", "wrap": True},
        {"type": "TextBlock",
         "text": (f"{len(rows)} stop(s) departed — final times below for the "
                  f"detention invoice — as of {datetime.now(CT):%I:%M %p CT}"),
         "size": "Small", "spacing": "None", "wrap": True},
    ]
    for r in sorted(rows, key=lambda x: -(x.get("billable_min") or 0)):
        facts = _row_facts(r) + [
            {"title": "Clock started", "value": _fmt_dt_ct(r.get("clock_start_dt")) or "—"},
            {"title": "Departed", "value": _fmt_dt_ct(r.get("departed_dt")) or "—"},
            {"title": "Total on site", "value": _fmt_mins(r.get("total_min"))},
        ]
        body.append({
            "type": "Container", "separator": True, "spacing": "Medium",
            "items": [
                {"type": "TextBlock",
                 "text": (f"**Truck {r.get('truck_name') or '—'}** — "
                          f"{r.get('driver_name') or '—'}"),
                 "wrap": True},
                {"type": "FactSet", "spacing": "Small", "facts": facts},
                {"type": "TextBlock",
                 "text": (f"**Billable detention: {_fmt_mins(r.get('billable_min'))}** "
                          f"(beyond {free_h:g}h free from clock start)"),
                 "wrap": True, "color": "Attention", "spacing": "Small"},
            ],
        })
    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "msteams": {"width": "Full"},
    }


# ----------------------------------------------------------------------
# OneDrive state (same pattern as eta_state.json)
# ----------------------------------------------------------------------
def _load_state(token: str, user_upn: str, folder: str) -> dict:
    path = f"{folder}/{_STATE_FILE}"
    url = f"{_GRAPH_BASE}/users/{user_upn}/drive/root:/{path}:/content"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code != 404:
            log.warning("Detention state load HTTP %d", resp.status_code)
    except Exception as exc:
        log.warning("Detention state load failed: %s", exc)
    return {}


def _save_state(token: str, user_upn: str, folder: str, state: dict) -> None:
    path = f"{folder}/{_STATE_FILE}"
    url = f"{_GRAPH_BASE}/users/{user_upn}/drive/root:/{path}:/content"
    try:
        resp = requests.put(
            url,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            data=json.dumps(state, default=str).encode(),
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            log.warning("Detention state save HTTP %d: %s",
                        resp.status_code, resp.text[:200])
    except Exception as exc:
        log.warning("Detention state save failed: %s", exc)


def _state_entry(r: dict, now: datetime) -> dict:
    """The fields persisted per alerted stop — enough to render the closeout
    card even if the trip join looks different by the time the driver leaves."""
    return {
        "load_no": r["load_no"],
        "stop_idx": r["stop_idx"],
        "arrived": r["arrived_dt"].isoformat() if r.get("arrived_dt") else "",
        "clock_start": r["clock_start_dt"].isoformat() if r.get("clock_start_dt") else "",
        "alerted_at": now.isoformat(),
        "customer_name": r.get("customer_name", ""),
        "brokered": bool(r.get("brokered")),
        "truck_name": r.get("truck_name", ""),
        "driver_name": r.get("driver_name", ""),
        "sales_agent": r.get("sales_agent", ""),
        "stop_type": r.get("stop_type", ""),
        "facility": r.get("facility", ""),
        "city": r.get("city", ""),
        "stop_state": r.get("stop_state", ""),
        "appt_display": r.get("appt_display", ""),
        "early_arrival": bool(r.get("early_arrival")),
    }


# ----------------------------------------------------------------------
# Sync — detect, post on change, persist
# ----------------------------------------------------------------------
def sync_detention_alerts(webhook_url: str, token: str, user_upn: str, folder: str, *,
                          loads: list[dict], trips_by_load: dict,
                          trucks_by_id: dict | None = None,
                          drivers_by_id: dict | None = None,
                          users_by_id: dict | None = None,
                          resolve_mentions=None,
                          now: datetime | None = None,
                          free_time_min: int | None = None) -> None:
    """Post detention alert/closeout cards to Teams, at most once per stop.

    - A stop crosses the free-time window → one alert card (batched when
      several cross in the same run), with optional @mentions.
    - A previously-alerted stop gets DepartedAt → one closeout card with the
      billable detention.
    - A previously-alerted stop that vanishes from the fetch window, or sits
      past _STALE_ARRIVAL_HOURS with no departure, is dropped from state with
      a log line (data gap — there's no reliable departure time to bill from).
    - No change → no post.

    resolve_mentions: zero-arg callable returning [{"id", "name"}] — called
    lazily, only on runs that actually post a new alert (Graph lookups are
    not spent on quiet runs).
    """
    if free_time_min is None:
        try:
            free_time_min = int(os.environ.get("DETENTION_THRESHOLD_MIN", "").strip()
                                or _FREE_TIME_MIN_DEFAULT)
        except ValueError:
            free_time_min = _FREE_TIME_MIN_DEFAULT
    now = now or datetime.now(timezone.utc)

    state = _load_state(token, user_upn, folder)
    alerted: dict = dict(state.get("alerted") or {})

    current = find_detention_stops(loads, trips_by_load, trucks_by_id,
                                   drivers_by_id, users_by_id, now, free_time_min)
    curr_by_key = {r["key"]: r for r in current}

    # --- Closeouts: alerted stops no longer in live detention ------------
    loads_by_no = {str(L.get("LoadNumber") or L.get("Number") or ""): L for L in loads}
    closeouts: list[dict] = []
    expired: list[str] = []
    for key, info in alerted.items():
        if key in curr_by_key:
            continue  # still on site, still under the stale cap
        load = loads_by_no.get(str(info.get("load_no") or ""))
        stop = None
        if load:
            stops = load.get("Stops") or []
            i = info.get("stop_idx")
            if isinstance(i, int) and 0 <= i < len(stops):
                stop = stops[i]
        departed = _parse_iso(stop.get("DepartedAt")) if stop else None
        arrived = (_parse_iso((stop or {}).get("ArrivedAt"))
                   or _parse_iso(info.get("arrived")))
        if departed and arrived:
            # Bill from the detention clock start (appt/window open when the
            # driver arrived early), not the raw arrival.
            clock_start = _parse_iso(info.get("clock_start")) or arrived
            total_min = int((departed - arrived).total_seconds() // 60)
            clock_total = int((departed - clock_start).total_seconds() // 60)
            closeouts.append({
                **info, "key": key,
                "arrived_dt": arrived, "departed_dt": departed,
                "clock_start_dt": clock_start,
                "total_min": total_min,
                "billable_min": max(0, clock_total - free_time_min),
            })
        else:
            expired.append(key)

    def _post(card: dict) -> bool:
        payload = {
            "type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                             "content": card}],
        }
        try:
            resp = requests.post(webhook_url, json=payload, timeout=15)
            if resp.status_code not in (200, 202):
                log.warning("Detention webhook HTTP %d: %s",
                            resp.status_code, resp.text[:300])
                return False
            return True
        except Exception as exc:
            log.warning("Detention webhook failed: %s", exc)
            return False

    if closeouts:
        log.info("Detention: posting closeout for %s",
                 [c["key"] for c in closeouts])
        _post(build_closeout_card(closeouts, free_time_min))
        for c in closeouts:
            alerted.pop(c["key"], None)
    for key in expired:
        log.info("Detention: dropping %s from state — load left the fetch window "
                 "or arrival went stale with no departure recorded", key)
        alerted.pop(key, None)

    new_rows = [r for k, r in curr_by_key.items() if k not in alerted]
    if new_rows:
        mention_users = resolve_mentions() if resolve_mentions else []
        log.info("Detention: alerting %d new stop(s): %s",
                 len(new_rows), [r["key"] for r in new_rows])
        _post(build_detention_card(new_rows, free_time_min, mention_users))
        for r in new_rows:
            alerted[r["key"]] = _state_entry(r, now)
    elif not closeouts and not expired:
        log.info("Detention: no change (%d stop(s) already alerted, still on site)",
                 len(alerted))

    _save_state(token, user_upn, folder, {
        "alerted": alerted,
        "last_run": now.isoformat(),
    })
