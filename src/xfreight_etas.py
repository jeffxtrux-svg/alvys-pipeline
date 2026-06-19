"""XFreight ETA report — live X-Trux load tracker, refreshes every 30 min.

Pulls active X-Trux loads from Alvys, current truck GPS from Samsara, and
asks Mapbox Directions API (traffic-aware) for drive time from each truck
to its next undelivered stop. Writes an HTML + Excel snapshot to OneDrive
that overwrites in place, so a single pinned link is always current.

v1 columns (per owner spec, 2026-06-19):
  Shipper | Shipper City | Consignee | Consignee City | Appt | ETA | Delta | Broker

v1 scope:
  - X-Trux entity only
  - Active loads only (Dispatched / In Transit, with an undelivered stop)
  - Trucks with both a matching active Samsara location AND an Alvys load
    are shown; everything else is hidden

Roadmap (deferred — design supports both):
  v2: Customer/broker email notifications when ETA within 45 min of appt
  v2: Contact email + phone column (broker contact if brokered,
      consignee contact if customer-direct)

Env vars (all required unless noted):
  AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET / ONEDRIVE_USER_UPN
  ALVYS_CLIENT_ID / ALVYS_CLIENT_SECRET
  SAMSARA_API_TOKEN
  MAPBOX_TOKEN                       — secret token with directions:read
  TEAMS_ETA_WEBHOOK (optional)       — Power Automate webhook URL; alerts when
                                       any load is 45+ min behind schedule
  ETA_ONEDRIVE_FOLDER (optional)     — default "ETA"
"""

from __future__ import annotations

import io
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from src.alvys_client import AlvysClient
from src.samsara_client import SamsaraClient
from src.onedrive_upload import get_token, ensure_folder, upload_file

log = logging.getLogger("xfreight_etas")

CT = ZoneInfo("America/Chicago")
ACTIVE_STATUSES = ["Dispatched", "In Transit"]
_MAPBOX_BASE = "https://api.mapbox.com/directions/v5/mapbox"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _entity_is_xtrux(office: str | None) -> bool:
    """Mirrors scorecard_email._entity_group — XFreight + X-Trux office names."""
    if not office:
        return False
    s = str(office).upper()
    return "TRUX" in s or "FREIGHT" in s


def _g(d: dict | None, *path: str, default=None):
    """Walk a nested dict by string path; return default if any hop is missing."""
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _parse_iso(s: str | None) -> datetime | None:
    """Parse Alvys/Samsara ISO timestamp into an aware UTC datetime."""
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


def _fmt_delta(minutes: int | None) -> tuple[str, str]:
    """Return (display_text, css_color) for the Delta column."""
    if minutes is None:
        return ("—", "#999")
    if minutes <= -45:
        return (f"{-minutes} min late", "#c41e2a")  # red
    if minutes < 0:
        return (f"{-minutes} min late", "#d97706")  # amber
    if minutes <= 30:
        return (f"{minutes} min early", "#16a34a")  # green
    return (f"{minutes} min early", "#1a1a1a")      # neutral early


# ----------------------------------------------------------------------
# Alvys load extraction
# ----------------------------------------------------------------------
def _next_undelivered_stop(load: dict) -> dict | None:
    """Return the next stop a truck still has to hit (no ArrivedAt). Drops
    are the priority — if the only thing left is the final drop we report
    that; otherwise we report the next pick still pending."""
    stops = load.get("Stops") or []
    for stop in stops:
        if not stop.get("ArrivedAt"):
            return stop
    return None


def _is_brokered(load: dict) -> bool:
    return str(load.get("BrokerageStatus") or "").lower() == "brokered"


def _extract_load_row(load: dict, trucks_by_id: dict, trips_by_load: dict) -> dict | None:
    """Pull the v1 report columns out of one Alvys load record. Returns None
    if the load isn't routable (no truck assignment, no undelivered stop,
    or no geocoded destination).

    Truck assignment lives on the Trip (not the Load). We join by LoadNumber.
    Coordinates are on the Stop under a 'Coordinates' key (not Address.Latitude).
    """
    load_num = str(load.get("LoadNumber") or "")
    trip = trips_by_load.get(load_num) if load_num else None

    truck_name = None
    if trip:
        truck_obj = trip.get("Truck") or {}
        if isinstance(truck_obj, dict):
            # Try the truck name/number directly on the nested object first
            truck_name = (truck_obj.get("TruckNum") or truck_obj.get("TruckNumber")
                         or truck_obj.get("Number") or truck_obj.get("Name"))
            if not truck_name:
                # Fall back to the trucks_by_id lookup via Truck.Id
                truck_id = truck_obj.get("Id")
                if truck_id:
                    truck_name = trucks_by_id.get(str(truck_id)) or None

    if not truck_name:
        return None

    next_stop = _next_undelivered_stop(load)
    if not next_stop:
        return None

    # Coordinates live under the "Coordinates" key, not inside Address
    coords = next_stop.get("Coordinates") or {}
    dest_lat = coords.get("Latitude") if isinstance(coords, dict) else None
    dest_lng = coords.get("Longitude") if isinstance(coords, dict) else None
    if dest_lat is None or dest_lng is None:
        return None

    stops = load.get("Stops") or []
    first_stop = stops[0] if stops else {}
    last_stop = stops[-1] if stops else {}

    return {
        "load_no": load.get("LoadNumber") or load.get("Number"),
        "truck_name": str(truck_name),
        "shipper": _g(first_stop, "CompanyName") or _g(first_stop, "Address", "Street") or "",
        "shipper_city": _g(first_stop, "Address", "City") or "",
        "shipper_state": _g(first_stop, "Address", "State") or "",
        "consignee": _g(last_stop, "CompanyName") or _g(last_stop, "Address", "Street") or "",
        "consignee_city": _g(last_stop, "Address", "City") or "",
        "consignee_state": _g(last_stop, "Address", "State") or "",
        "appt_dt": _parse_iso(next_stop.get("AppointmentDate")),
        "dest_lat": float(dest_lat),
        "dest_lng": float(dest_lng),
        "broker": load.get("CustomerName") if _is_brokered(load) else "",
        "office": _g(load, "Office", "Name") or _g(load, "Trip", "Office", "Name") or "",
    }


# ----------------------------------------------------------------------
# Samsara location join
# ----------------------------------------------------------------------
def _locations_by_truck_name(samsara_locations: list[dict]) -> dict:
    """{truck_name: {lat, lng, ts}} from Samsara /fleet/vehicles/locations."""
    out: dict[str, dict] = {}
    for rec in samsara_locations:
        name = rec.get("name") or rec.get("vehicle", {}).get("name")
        loc = rec.get("location") or {}
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        ts = _parse_iso(loc.get("time") or rec.get("time"))
        if name and lat is not None and lng is not None:
            out[str(name).strip()] = {"lat": float(lat), "lng": float(lng), "ts": ts}
    return out


# ----------------------------------------------------------------------
# Mapbox routing
# ----------------------------------------------------------------------
def _mapbox_duration_seconds(
    token: str, from_lat: float, from_lng: float,
    to_lat: float, to_lng: float, timeout: int = 15,
) -> float | None:
    """Query Mapbox Directions and return drive-time in seconds.

    Tries driving-traffic (requires sk. token) first; falls back to driving
    (works with pk. token) on 401 so the report works immediately with a
    public token and upgrades automatically when rotated to secret token.
    """
    coords = f"{from_lng},{from_lat};{to_lng},{to_lat}"
    params = {"access_token": token, "geometries": "geojson", "overview": "false"}
    for profile in ("driving-traffic", "driving"):
        url = f"{_MAPBOX_BASE}/{profile}/{coords}"
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 401 and profile == "driving-traffic":
                log.info("Mapbox driving-traffic → 401 (pk. token?), retrying with driving")
                continue
            if resp.status_code != 200:
                log.warning("Mapbox %s→%s HTTP %d: %s",
                            profile, coords[:30], resp.status_code, resp.text[:200])
                return None
            routes = (resp.json() or {}).get("routes") or []
            return float(routes[0].get("duration") or 0) if routes else None
        except Exception as e:
            log.warning("Mapbox %s request failed: %s", profile, e)
            return None
    return None


# ----------------------------------------------------------------------
# Teams alert
# ----------------------------------------------------------------------
_LATE_THRESHOLD_MIN = -45


def _post_teams_alert(webhook_url: str, late_rows: list[dict]) -> None:
    """POST an Adaptive Card to the Teams Power Automate webhook."""
    if not late_rows or not webhook_url:
        return

    def _col(text: str, width: str = "auto", bold: bool = False,
             color: str = "Default", wrap: bool = False) -> dict:
        return {
            "type": "Column", "width": width,
            "items": [{"type": "TextBlock", "text": text, "size": "Small",
                       "weight": "Bolder" if bold else "Default",
                       "color": color, "wrap": wrap}],
        }

    body: list[dict] = [
        {"type": "TextBlock", "text": "⚠️ Drivers Running Late",
         "weight": "Bolder", "size": "Large", "color": "Attention", "wrap": True},
        {"type": "TextBlock",
         "text": f"{len(late_rows)} load(s) are 45+ min behind schedule — as of "
                 f"{datetime.now(CT):%I:%M %p CT}",
         "size": "Small", "spacing": "None", "wrap": True},
        {"type": "TextBlock", "text": " ", "spacing": "Small"},
        {"type": "ColumnSet", "columns": [
            _col("Truck", "auto", bold=True),
            _col("Destination", "stretch", bold=True),
            _col("Appt", "auto", bold=True),
            _col("ETA", "auto", bold=True),
            _col("Late", "auto", bold=True, color="Attention"),
        ]},
    ]

    for r in sorted(late_rows, key=lambda x: x.get("delta_min") or 0):
        mins_late = abs(r["delta_min"])
        hrs, m = divmod(mins_late, 60)
        late_str = f"{hrs}h {m}m" if hrs else f"{m}m"
        dest = (f"{r['consignee_city']}, {r['consignee_state']}".strip(", ")
                or r["consignee"] or "—")
        body.append({
            "type": "ColumnSet", "separator": True,
            "columns": [
                _col(r["truck_name"], "auto", bold=True, wrap=False),
                _col(dest, "stretch", wrap=True),
                _col(_fmt_dt_ct(r["appt_dt"]), "auto", wrap=False),
                _col(_fmt_dt_ct(r.get("eta_dt")), "auto", wrap=False),
                _col(late_str, "auto", bold=True, color="Attention", wrap=False),
            ],
        })

    payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body,
            },
        }],
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
        if resp.status_code not in (200, 202):
            log.warning("Teams alert HTTP %d: %s", resp.status_code, resp.text[:300])
        else:
            log.info("Teams alert posted for %d late load(s)", len(late_rows))
    except Exception as e:
        log.warning("Teams alert failed: %s", e)


# ----------------------------------------------------------------------
# Report rendering
# ----------------------------------------------------------------------
INK = "#1a1a1a"
MUTE = "#6b6b6b"
LINE = "#e5e5e5"
RED = "#c41e2a"
TILEBG = "#fafafa"
FONT = ("font-family:-apple-system,'Helvetica Neue',Helvetica,Arial,sans-serif;"
        "font-size:13px;color:#1a1a1a;")


def _render_html(rows: list[dict], generated_at: datetime) -> str:
    if not rows:
        body = (f"<div style='padding:40px;text-align:center;color:{MUTE};font-size:14px;'>"
                f"No active X-Trux loads to display.</div>")
    else:
        # Sort: latest (worst delta first), then by appt time
        rows = sorted(
            rows,
            key=lambda r: ((r.get("delta_min") if r.get("delta_min") is not None else 9999),
                           r.get("appt_dt") or datetime.max.replace(tzinfo=timezone.utc)),
        )
        thead = (
            f"<thead><tr style='background:{TILEBG};border-bottom:2px solid {INK};'>"
            + "".join(
                f"<th style='padding:8px 10px;text-align:left;font-size:10px;"
                f"text-transform:uppercase;letter-spacing:0.8px;color:{MUTE};'>"
                f"{h}</th>"
                for h in ("Truck", "Shipper", "Shipper City", "Consignee",
                          "Consignee City", "Appt", "ETA", "Delta", "Broker"))
            + "</tr></thead>"
        )

        tbody_rows = ""
        for r in rows:
            delta_txt, delta_color = _fmt_delta(r.get("delta_min"))
            shipper_loc = f"{r['shipper_city']}, {r['shipper_state']}".strip(", ")
            consignee_loc = f"{r['consignee_city']}, {r['consignee_state']}".strip(", ")
            tbody_rows += (
                f"<tr style='border-bottom:1px solid {LINE};'>"
                f"<td style='padding:8px 10px;font-weight:700;'>{r['truck_name']}</td>"
                f"<td style='padding:8px 10px;'>{r['shipper'] or '—'}</td>"
                f"<td style='padding:8px 10px;color:{MUTE};'>{shipper_loc or '—'}</td>"
                f"<td style='padding:8px 10px;'>{r['consignee'] or '—'}</td>"
                f"<td style='padding:8px 10px;color:{MUTE};'>{consignee_loc or '—'}</td>"
                f"<td style='padding:8px 10px;white-space:nowrap;'>{_fmt_dt_ct(r['appt_dt'])}</td>"
                f"<td style='padding:8px 10px;white-space:nowrap;'>{_fmt_dt_ct(r.get('eta_dt'))}</td>"
                f"<td style='padding:8px 10px;color:{delta_color};font-weight:700;white-space:nowrap;'>{delta_txt}</td>"
                f"<td style='padding:8px 10px;color:{MUTE};'>{r['broker'] or '—'}</td>"
                f"</tr>"
            )
        body = (
            f"<table cellpadding='0' cellspacing='0' style='width:100%;border-collapse:collapse;'>"
            f"{thead}<tbody>{tbody_rows}</tbody></table>"
        )

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta http-equiv='refresh' content='180'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<style>body{{margin:0;background:#fff;{FONT}}}</style>"
        "</head><body>"
        f"<div style='padding:20px 24px;border-bottom:3px solid {RED};'>"
        f"<div style='font-weight:700;letter-spacing:1.5px;font-size:11px;"
        f"color:{RED};text-transform:uppercase;'>XFreight &middot; ETAs</div>"
        f"<div style='font-size:22px;font-weight:700;margin-top:4px;'>"
        f"Active X-Trux Loads &mdash; Live ETA</div>"
        f"<div style='color:{MUTE};font-size:12px;margin-top:6px;'>"
        f"Generated {generated_at.astimezone(CT):%a %b %d, %I:%M %p} CT &middot; "
        f"refreshes every 30 min &middot; {len(rows)} active load(s)"
        f"</div></div>"
        f"<div style='padding:20px 24px;'>{body}</div>"
        f"<div style='padding:14px 24px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};'>"
        f"Delta = ETA &minus; appointment. Red = &ge;45 min late &middot; "
        f"amber = late (under 45 min) &middot; green = within 30 min early. "
        f"ETA from Samsara GPS &rarr; Mapbox driving-traffic.</div>"
        "</body></html>"
    )


def _render_xlsx(rows: list[dict], generated_at: datetime) -> bytes:
    """Build an .xlsx in memory using openpyxl."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "ETAs"

    ws.append([f"XFreight ETAs — generated {generated_at.astimezone(CT):%a %b %d, %I:%M %p} CT"])
    ws.merge_cells("A1:I1")
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])

    headers = ["Truck", "Shipper", "Shipper City", "Consignee", "Consignee City",
               "Appt (CT)", "ETA (CT)", "Delta (min)", "Broker"]
    ws.append(headers)
    hdr_fill = PatternFill("solid", fgColor="FAFAFA")
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=3, column=col_idx)
        c.font = Font(bold=True)
        c.fill = hdr_fill
        c.alignment = Alignment(horizontal="left")

    for r in rows:
        ws.append([
            r["truck_name"],
            r["shipper"],
            f"{r['shipper_city']}, {r['shipper_state']}".strip(", "),
            r["consignee"],
            f"{r['consignee_city']}, {r['consignee_state']}".strip(", "),
            _fmt_dt_ct(r["appt_dt"]),
            _fmt_dt_ct(r.get("eta_dt")),
            r.get("delta_min", ""),
            r["broker"],
        ])

    widths = [10, 28, 22, 28, 22, 22, 22, 14, 22]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    mapbox_token = os.environ.get("MAPBOX_TOKEN")
    if not mapbox_token:
        log.error("MAPBOX_TOKEN not set — aborting.")
        return 1

    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    user_upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not all([tenant_id, client_id, client_secret, user_upn]):
        log.error("Azure / OneDrive env vars missing — aborting.")
        return 1

    # --- Pull active loads from Alvys -----------------------------------
    alvys = AlvysClient(
        client_id=os.environ["ALVYS_CLIENT_ID"],
        client_secret=os.environ["ALVYS_CLIENT_SECRET"],
    )
    trucks = alvys.fetch_trucks()
    trucks_by_id = {}
    for t in trucks:
        tid = str(t.get("Id") or "")
        if not tid:
            continue
        num = (t.get("TruckNum") or t.get("TruckNumber")
               or t.get("Number") or t.get("Name") or "")
        trucks_by_id[tid] = str(num)
    log.info("Indexed %d trucks", len(trucks_by_id))

    # Active loads: status filter + ~7 day updatedAt window
    start_date = (datetime.now(CT) - timedelta(days=7)).strftime("%Y-%m-%d")
    all_loads = alvys.fetch_loads(start_date)
    log.info("Pulled %d total loads from last 7d", len(all_loads))

    active = [
        L for L in all_loads
        if L.get("Status") in ACTIVE_STATUSES
        # Office identity comes from InvoiceAs (free string like "X-TRUX INC");
        # OfficeId would require the lookups module, which we skip for speed.
        and _entity_is_xtrux(L.get("InvoiceAs"))
    ]
    log.info("Filtered to %d active X-Trux loads", len(active))

    # Trips carry truck assignment — loads don't embed it.
    raw_trips = alvys.fetch_trips(start_date)
    trips_by_load: dict[str, dict] = {}
    for trip in raw_trips:
        ln = str(trip.get("LoadNumber") or "")
        if ln and ln not in trips_by_load:
            trips_by_load[ln] = trip
    log.info("Indexed %d trips (%d unique load numbers)", len(raw_trips), len(trips_by_load))

    load_rows: list[dict] = []
    for L in active:
        row = _extract_load_row(L, trucks_by_id, trips_by_load)
        if row:
            load_rows.append(row)
    log.info("Routable loads (have truck + undelivered stop + dest coords): %d",
             len(load_rows))

    # Diagnostic: when we can't extract any rows, dump load + trip + truck shape.
    if not load_rows and active:
        import json
        sample = active[0]
        sample_ln = str(sample.get("LoadNumber") or "")
        sample_trip = trips_by_load.get(sample_ln)
        log.warning("=== DIAGNOSTIC: no routable loads ===")
        log.warning("Load top-level keys: %s", sorted(sample.keys()))
        stops = sample.get("Stops") or []
        log.warning("Stops count: %d", len(stops))
        if stops:
            log.warning("First stop keys: %s", sorted(stops[0].keys()))
            log.warning("First stop Address: %s",
                        json.dumps(stops[0].get("Address"), default=str)[:400])
            log.warning("First stop Coordinates: %s",
                        json.dumps(stops[0].get("Coordinates"), default=str)[:400])
        log.warning("trips_by_load has load %r? %s", sample_ln, sample_trip is not None)
        if sample_trip:
            log.warning("Trip top-level keys: %s", sorted(sample_trip.keys()))
            truck_obj = sample_trip.get("Truck")
            log.warning("Trip.Truck field: %s", json.dumps(truck_obj, default=str)[:800])
        else:
            log.warning("No matching trip — active load numbers vs trip load numbers (sample):")
            active_lns = [str(L.get("LoadNumber") or "") for L in active[:5]]
            trip_lns = list(trips_by_load.keys())[:5]
            log.warning("  active: %s  trips: %s", active_lns, trip_lns)
        log.warning("Trucks_by_id sample (first 3): %s", list(trucks_by_id.items())[:3])
        log.warning("=== END DIAGNOSTIC ===")

    # --- Pull current locations from Samsara ----------------------------
    samsara = SamsaraClient(api_token=os.environ["SAMSARA_API_TOKEN"])
    locations = samsara.fetch_locations()
    locs_by_truck = _locations_by_truck_name(locations)
    log.info("Resolved current GPS for %d trucks", len(locs_by_truck))

    # --- Compute ETA per load via Mapbox --------------------------------
    now = datetime.now(timezone.utc)
    rows_with_eta: list[dict] = []
    for row in load_rows:
        gps = locs_by_truck.get(row["truck_name"])
        if not gps:
            continue  # hide trucks we can't locate
        duration_s = _mapbox_duration_seconds(
            mapbox_token, gps["lat"], gps["lng"],
            row["dest_lat"], row["dest_lng"],
        )
        if duration_s is None:
            continue
        eta_dt = now + timedelta(seconds=duration_s)
        delta_min = None
        if row["appt_dt"]:
            delta_min = int(round((row["appt_dt"] - eta_dt).total_seconds() / 60))
            # Positive delta = early; negative delta = late
        rows_with_eta.append({**row, "eta_dt": eta_dt, "delta_min": delta_min})

    log.info("Computed ETAs for %d active loads", len(rows_with_eta))

    # --- Teams alert for loads 45+ min late -----------------------------
    teams_webhook = os.environ.get("TEAMS_ETA_WEBHOOK", "").strip()
    if teams_webhook:
        late = [r for r in rows_with_eta
                if r.get("delta_min") is not None and r["delta_min"] <= _LATE_THRESHOLD_MIN]
        if late:
            _post_teams_alert(teams_webhook, late)
        else:
            log.info("No loads 45+ min late — Teams alert skipped")
    else:
        log.info("TEAMS_ETA_WEBHOOK not set — skipping alert")

    # --- Render + upload ------------------------------------------------
    generated_at = datetime.now(timezone.utc)
    html = _render_html(rows_with_eta, generated_at)
    xlsx_bytes = _render_xlsx(rows_with_eta, generated_at)

    folder = os.environ.get("ETA_ONEDRIVE_FOLDER", "ETA").strip("/")
    tok = get_token(tenant_id, client_id, client_secret)
    ensure_folder(tok, user_upn, folder)

    out_dir = Path("output/eta")
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "XFreight_ETAs.html"
    xlsx_path = out_dir / "XFreight_ETAs.xlsx"
    html_path.write_text(html, encoding="utf-8")
    xlsx_path.write_bytes(xlsx_bytes)

    upload_file(tok, user_upn, folder, html_path.name, html_path)
    upload_file(tok, user_upn, folder, xlsx_path.name, xlsx_path)
    log.info("Published %s/XFreight_ETAs.{html,xlsx} to OneDrive", folder)

    return 0


if __name__ == "__main__":
    sys.exit(main())
