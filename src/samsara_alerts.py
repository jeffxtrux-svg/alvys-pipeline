"""
Samsara diagnostic alert system.

The report is grouped into Tractors/Trucks, Trailers, and Drivers.

Checks for:
  - Active engine fault codes (truck maintenance) on any tractor — the J1939
    SPN/FMI + OBD-II DTCs shown in Samsara's maintenance "Active Faults" column.
    At most 3 faults per truck are listed; extras point back to Samsara.
    (Trailers don't report engine faults, so this is a tractor-only section.)
  - DVIRs with unresolved defects (last 7 days), split into tractor vs trailer
    inspections by whether the DVIR record carries a `vehicle` or `trailer` key.
  - Drivers who have uncertified daily HOS logs AND are currently driving or on
    duty — an actionable compliance gap (someone working with logs not signed).

Sends an HTML email via Microsoft Graph API when issues are found.

Required env vars:
    SAMSARA_API_TOKEN
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
    ALERT_FROM_UPN    — M365 mailbox to send from (e.g. jeff@xfreight.net)
    ALERT_TO_EMAILS   — comma-separated recipient list (defaults to ALERT_FROM_UPN)

Optional env vars:
    SAMSARA_ALERT_TEST_MODE — when truthy (the DEFAULT while changes are in
        flight) the alert is sent ONLY to the tester and the real ALERT_TO_EMAILS
        list is suppressed; a TEST banner is shown and "[TEST]" is prepended to
        the subject. Set to 0/false/off to resume normal recipients.
    SAMSARA_ALERT_TEST_TO   — the lone recipient while in test mode
        (defaults to ALERT_FROM_UPN, i.e. Jeff's mailbox).

IMPORTANT — one-time Azure setup required:
    The app registration needs "Mail.Send" Application permission in addition to
    the Files.ReadWrite.All it already has. Add it in Azure Portal →
    App registrations → API permissions → Add permission → Microsoft Graph →
    Application permissions → Mail.Send → Grant admin consent.
"""
from __future__ import annotations

import datetime
import html
import logging
import os
import re
import sys
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from src.samsara_client import SamsaraClient
from src.samsara_cert_nudge import _is_placeholder_name, _first_name
from src.onedrive_upload import get_token

log = logging.getLogger("samsara_alerts")

GRAPH = "https://graph.microsoft.com/v1.0"


# ------------------------------------------------------------------
# Email sending
# ------------------------------------------------------------------

def send_alert_email(
    access_token: str,
    from_upn: str,
    to_emails: list[str],
    subject: str,
    body_html: str,
) -> None:
    url = f"{GRAPH}/users/{from_upn}/sendMail"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [
            {"emailAddress": {"address": addr}} for addr in to_emails
        ],
    }
    resp = requests.post(url, headers=headers, json={"message": message}, timeout=30)
    if resp.status_code == 202:
        log.info("Alert email sent to: %s", ", ".join(to_emails))
    else:
        log.error("Email send failed [%d]: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()


# ------------------------------------------------------------------
# Issue extraction
# ------------------------------------------------------------------

# Show at most this many faults per truck in the email; the rest are summarized
# as an overflow count linking back to Samsara.
MAX_FAULTS_PER_TRUCK = 3


def _clean_vehicle_name(name: str) -> str:
    """Surface the plain unit number from a Samsara vehicle name.

    Most tractors are named by unit number ("42188"), but some carry a prefix
    like "X-OOS38166", "x-41184", or "x42191". Strip a leading run of non-digit
    characters so the alert shows "38166" / "41184" / "42191". A name with no
    digits at all (a nickname, not a unit #) is returned unchanged.
    """
    s = str(name or "").strip()
    m = re.search(r"\d.*$", s)
    return m.group(0) if m else s


def _fmt_logged(iso: str | None) -> str | None:
    """Format a Samsara ISO-8601 UTC timestamp as Central wall-clock, matching
    the rest of the email (e.g. '2026-06-14 12:03 CT'). Returns None on no/bad
    input so callers can omit the clause."""
    if not iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M CT")
    except (ValueError, TypeError):
        return str(iso)


def _excluded_units() -> set[str]:
    """Unit numbers/names to drop from the truck-fault and tractor-DVIR sections
    — retired or out-of-service tractors that shouldn't appear in reports.
    Configured via SAMSARA_ALERT_EXCLUDE_UNITS (comma-separated); defaults to
    '38166' (the OOS unit that stopped reporting in 2024)."""
    raw = os.environ.get("SAMSARA_ALERT_EXCLUDE_UNITS", "38166")
    return {u.strip().upper() for u in raw.split(",") if u.strip()}


def _is_excluded_unit(name: str, excluded: set[str] | None = None) -> bool:
    """True if a vehicle name matches the exclusion set, by raw name or by the
    cleaned unit number (so 'X-OOS38166' and '38166' both match '38166')."""
    excluded = _excluded_units() if excluded is None else excluded
    if not excluded:
        return False
    raw = str(name or "").strip().upper()
    return raw in excluded or _clean_vehicle_name(name).strip().upper() in excluded


def _fault_max_age_days() -> int:
    """Hide faults whose last-logged reading is older than this many days.
    Configured via SAMSARA_ALERT_FAULT_MAX_AGE_DAYS; defaults to 7. 0 disables."""
    try:
        return int(os.environ.get("SAMSARA_ALERT_FAULT_MAX_AGE_DAYS", "7"))
    except (ValueError, TypeError):
        return 7


def _fault_too_old(iso: str | None, max_age_days: int) -> bool:
    """True if the per-vehicle fault reading time is older than max_age_days.
    Unknown/blank time → not filtered (can't prove it's stale)."""
    if not iso or max_age_days <= 0:
        return False
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return datetime.datetime.now(datetime.timezone.utc) - dt > datetime.timedelta(days=max_age_days)


def _nudge_max_age_hours() -> float:
    """Only drivers whose truck logged a fault within this many hours get nudged
    (tighter than the display window). Configured via
    SAMSARA_ALERT_NUDGE_MAX_AGE_HOURS; defaults to 12."""
    try:
        return float(os.environ.get("SAMSARA_ALERT_NUDGE_MAX_AGE_HOURS", "12"))
    except (ValueError, TypeError):
        return 12.0


def _within_hours(iso: str | None, hours: float) -> bool:
    """True if the ISO timestamp is within the last `hours`. Unknown/blank time
    → False (can't confirm it's recent, so don't nudge)."""
    if not iso or hours <= 0:
        return False
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    return datetime.datetime.now(datetime.timezone.utc) - dt <= datetime.timedelta(hours=hours)


def _format_fault(dtc: dict, logged: str | None = None) -> str:
    """Render one diagnostic trouble code the way Samsara's maintenance view does,
    with the per-vehicle "logged" time (when this fault state was last reported)
    appended after the count:

        Txld: 0 SPN: 3936 – Aftertreatment Diesel Particulate Filter System
        FMI: 18 (Low—moderate severity) Count: 1 · logged 2026-06-14 12:03 CT

    Every field is optional in the API, so each is included only when present.
    Description text is HTML-escaped since it lands in an HTML table cell.
    """
    parts: list[str] = []

    tx = dtc.get("txId")
    if tx is not None:
        parts.append(f"Txld: {html.escape(str(tx))}")

    spn = dtc.get("spnId")
    spn_desc = html.escape(str(dtc.get("spnDescription") or "Unknown fault"))
    parts.append(f"SPN: {spn} – {spn_desc}" if spn is not None else spn_desc)

    fmi = dtc.get("fmiId")
    fmi_str = f"FMI: {fmi}" if fmi is not None else ""
    fmi_desc = dtc.get("fmiDescription")
    if fmi_desc:
        fmi_desc = html.escape(str(fmi_desc))
        fmi_str = f"{fmi_str} ({fmi_desc})" if fmi_str else f"({fmi_desc})"
    if fmi_str:
        parts.append(fmi_str)

    count = dtc.get("occurrenceCount")
    if count is not None:
        parts.append(f"Count: {html.escape(str(count))}")

    line = " ".join(parts)
    if logged:
        line += f" <span style='color:#888'>&middot; logged {html.escape(logged)}</span>"
    return line


def _fault_summary(dtc: dict) -> str:
    """Plain-text one-liner for a fault, used in the driver nudge message
    (e.g. 'SPN 5113 Controller #7 (Failure)'). No HTML — this is a text message."""
    spn = dtc.get("spnId")
    desc = str(dtc.get("spnDescription") or "engine fault")
    fmi_desc = dtc.get("fmiDescription")
    s = f"SPN {spn} {desc}" if spn is not None else desc
    if fmi_desc:
        s += f" ({fmi_desc})"
    return s


def _extract_active_faults(
    fault_records: list[dict],
    driver_by_vehicle: dict[str, dict] | None = None,
    max_shown: int = MAX_FAULTS_PER_TRUCK,
) -> list[dict]:
    """Find vehicles with active engine fault codes.

    Reads faultCodes.j1939.diagnosticTroubleCodes (and obdii, for light-duty
    OBD-II vehicles) from each /fleet/vehicles/stats?types=faultCodes record.
    Lists at most `max_shown` faults per truck; any beyond that become an
    overflow count so the reader knows to open Samsara for the full list.

    `driver_by_vehicle` (vehicle id → {id, name, driving_now}) attaches the
    truck's current driver for the email column and the fault nudge.
    """
    driver_by_vehicle = driver_by_vehicle or {}
    excluded = _excluded_units()
    max_age_days = _fault_max_age_days()
    issues = []
    for record in fault_records:
        vehicle_name = record.get("name") or f"asset {record.get('id', 'unknown')}"

        # Drop excluded units (e.g. retired/OOS tractors) entirely.
        if _is_excluded_unit(vehicle_name, excluded):
            continue

        fc = record.get("faultCodes")
        # Current API returns a dict; tolerate a snapshot-list shape just in case.
        if isinstance(fc, list):
            fc = fc[0] if fc else {}
        if not isinstance(fc, dict):
            continue

        # Skip trucks whose fault reading hasn't refreshed in > max_age_days
        # (faultCodes.time is per-vehicle, so this hides stale fault sets).
        if _fault_too_old(fc.get("time"), max_age_days):
            continue

        dtcs: list[dict] = []
        for bus in ("j1939", "obdii"):
            sub = fc.get(bus)
            if isinstance(sub, dict):
                codes = sub.get("diagnosticTroubleCodes")
                if isinstance(codes, list):
                    dtcs.extend(d for d in codes if isinstance(d, dict))

        if not dtcs:
            continue

        # faultCodes.time is the per-vehicle reading time — when this fault state
        # was last logged/reported (one timestamp for all of a truck's faults).
        logged = _fmt_logged(fc.get("time"))
        shown = [_format_fault(d, logged) for d in dtcs[:max_shown]]

        driver = driver_by_vehicle.get(str(record.get("id") or "")) or {}
        summary = _fault_summary(dtcs[0])
        if len(dtcs) > 1:
            summary += f" +{len(dtcs) - 1} more"

        issues.append({
            "vehicle_name": html.escape(_clean_vehicle_name(vehicle_name)),
            "faults": shown,
            "total": len(dtcs),
            "overflow": max(0, len(dtcs) - len(shown)),
            "driver_name": driver.get("name") or "",
            "driver_id": driver.get("id") or "",
            "driving_now": bool(driver.get("driving_now")),
            "summary": summary,
            "logged_iso": fc.get("time"),
        })

    return issues


def _compose_fault_message(first: str, unit: str, summary: str, total: int) -> str:
    n = total or 1
    plural = "fault" if n == 1 else "faults"
    return (
        f"Hi {first or 'driver'}, your truck {unit} has {n} active engine {plural} "
        f"showing in Samsara: {summary}. Please let maintenance/dispatch know so it "
        f"can be checked. Thanks!"
    )


def _nudge_fault_drivers(
    client: SamsaraClient,
    active_faults: list[dict],
    *,
    test_mode: bool,
    graph_token: str | None = None,
    onedrive_upn: str | None = None,
) -> dict:
    """Message the current driver of each faulted truck about its active fault(s)
    via the Samsara Driver App, mirroring the cert-nudge pattern.

    Idempotent per Central day via a OneDrive marker
    (`Samsara/fault-nudge-sent-{date}.txt`) holding the `driverId:unit` pairs
    already nudged today, so the multi-times-daily refresh messages each
    driver+truck at most once. In TEST MODE this is a DRY RUN — it logs the
    intended messages and sends nothing to drivers.

    Returns {"recipients": [display...], "sent": [display...], "dry_run": bool}.
    """
    # Only nudge drivers whose truck logged a fault within the recent window
    # (default 12h) — tighter than the up-to-7-day display filter.
    max_age_hours = _nudge_max_age_hours()
    targets = [
        f for f in active_faults
        if f.get("driver_id") and f.get("driver_name")
        and _within_hours(f.get("logged_iso"), max_age_hours)
    ]
    result = {"recipients": [], "sent": [], "dry_run": bool(test_mode),
              "max_age_hours": max_age_hours}
    if not targets:
        return result

    # Production idempotency marker (skipped entirely in test mode / no Graph).
    already: set[str] = set()
    marker_name = None
    use_marker = (not test_mode) and bool(graph_token) and bool(onedrive_upn)
    if use_marker:
        try:
            from src.onedrive_upload import download_file
            today = datetime.datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
            marker_name = f"fault-nudge-sent-{today}.txt"
            try:
                body = download_file(graph_token, onedrive_upn, f"Samsara/{marker_name}")
                already = {ln.strip() for ln in body.decode("utf-8", "ignore").splitlines() if ln.strip()}
            except Exception:
                already = set()
        except Exception as exc:
            log.warning("Fault-nudge marker read failed (%s) — proceeding without it.", exc)
            use_marker = False

    newly: list[str] = []
    for f in targets:
        unit = re.sub(r"<[^>]+>", "", str(f["vehicle_name"]))
        did = str(f["driver_id"])
        key = f"{did}:{unit}"
        display = f"{f['driver_name']} ({unit})"
        result["recipients"].append(display)
        if key in already:
            continue
        msg = _compose_fault_message(
            _first_name(f["driver_name"]), unit, f.get("summary") or "an active fault",
            f.get("total", 1),
        )
        if test_mode:
            log.warning("FAULT-NUDGE (dry-run) -> %s: %s", display, msg)
            continue
        sent = client.send_driver_messages([did], msg)
        if sent is not None:
            result["sent"].append(display)
            newly.append(key)
        else:
            log.warning("Fault-nudge send failed for %s", display)

    if use_marker and newly:
        try:
            import tempfile
            from pathlib import Path
            from src.onedrive_upload import upload_file, ensure_folder
            ensure_folder(graph_token, onedrive_upn, "Samsara")
            content = "\n".join(sorted(already | set(newly))) + "\n"
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
                tf.write(content)
                tmp = Path(tf.name)
            upload_file(graph_token, onedrive_upn, folder_path="Samsara",
                        filename=marker_name, file_path=tmp)
        except Exception as exc:
            log.warning("Fault-nudge marker write failed: %s", exc)

    return result


def _dvir_vehicle_name(dvir: dict) -> str:
    """Samsara's /fleet/dvirs/history uses different shapes depending on
    DVIR type. Try the documented paths in order; fall back to the asset id."""
    for path in (
        ("asset", "name"),
        ("vehicle", "name"),
        ("trailer", "name"),
    ):
        node = dvir
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if node:
            return str(node)
    for flat in ("assetName", "vehicleName", "trailerName"):
        v = dvir.get(flat)
        if v:
            return str(v)
    for path in (("asset", "id"), ("vehicle", "id"), ("trailer", "id")):
        node = dvir
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if node:
            return f"asset {node}"
    return "unknown vehicle"


def _dvir_asset_kind(dvir: dict) -> str:
    """Classify a DVIR as 'tractor' or 'trailer'.

    /fleet/dvirs/history attaches the inspected asset under a `trailer` key for
    trailer inspections and a `vehicle` key for tractor inspections, so the
    presence of either key is the discriminator. An `asset.assetType` of
    'trailer' is honored too. Unknown shapes default to tractor (the powered
    asset), which is the safer bucket for a maintenance/fault context.
    """
    if isinstance(dvir.get("trailer"), dict):
        return "trailer"
    if isinstance(dvir.get("vehicle"), dict):
        return "tractor"
    asset = dvir.get("asset")
    if isinstance(asset, dict) and "trailer" in str(asset.get("assetType") or "").lower():
        return "trailer"
    return "tractor"


def _dvir_driver_name(dvir: dict) -> str:
    # Production trailer DVIRs put the driver in
    # authorSignature.signatoryUser.name — check that first.
    for path in (
        ("authorSignature", "signatoryUser", "name"),
        ("driver", "name"),
        ("submittedBy", "name"),
        ("createdBy", "name"),
        ("inspector", "name"),
        ("user", "name"),
    ):
        node = dvir
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if node:
            return str(node)
    for flat in ("driverName", "submittedByName", "createdByName"):
        v = dvir.get(flat)
        if v:
            return str(v)
    drv_id = (dvir.get("driver") or {}).get("id") if isinstance(dvir.get("driver"), dict) else None
    if drv_id:
        return f"driver {drv_id}"
    # Trailer DVIRs sometimes carry no driver — em-dash is cleaner than "unknown".
    return "&mdash;"


def _dvir_time(dvir: dict) -> str:
    # Try every ISO-string time field Samsara has shipped under any DVIR shape.
    for k in (
        "createdAtTime", "inspectionTime", "completedAtTime", "submittedAtTime",
        "lastInspectedAtTime", "endTime", "startTime", "time",
        "createdAt", "submittedAt", "completedAt", "inspectedAt",
    ):
        v = dvir.get(k)
        if v:
            return str(v)
    # Millisecond fallbacks.
    for ms_key in ("createdAtMs", "inspectionTimeMs", "completedAtMs",
                   "submittedAtMs", "lastInspectedAtMs"):
        ms = dvir.get(ms_key)
        if ms:
            try:
                return datetime.datetime.utcfromtimestamp(int(ms) / 1000).strftime(
                    "%Y-%m-%d %H:%M UTC"
                )
            except (TypeError, ValueError):
                continue
    return "&mdash;"


def _extract_dvir_defects(dvirs: list[dict]) -> list[dict]:
    """Find DVIRs with unresolved defects."""
    defects = []
    excluded = _excluded_units()
    # One-shot debug: dump the first DVIR's top-level keys + full record so we
    # can see the actual response shape when a field comes back unexpectedly blank.
    if dvirs and isinstance(dvirs[0], dict):
        import json as _json
        log.info("DVIR sample keys: %s", sorted(dvirs[0].keys()))
        log.info("DVIR sample record: %s", _json.dumps(dvirs[0], default=str)[:1500])
        # Also dump the first DVIR that has an unresolved defect, since it may
        # be a different shape than dvirs[0].
        for d in dvirs:
            if not isinstance(d, dict):
                continue
            has_unresolved = any(
                not x.get("isResolved", x.get("resolved", True))
                for k in ("vehicleDefects", "trailerDefects", "defects")
                for x in (d.get(k) or [])
                if isinstance(x, dict)
            )
            if has_unresolved:
                log.info("DVIR sample (with unresolved defects): %s",
                         _json.dumps(d, default=str)[:1500])
                break
    for dvir in dvirs:
        # /fleet/dvirs/history nests defects under vehicleDefects/trailerDefects
        # with an isResolved flag (older shape used a flat "defects" list + resolved).
        dvir_defects = []
        for key in ("vehicleDefects", "trailerDefects", "defects"):
            v = dvir.get(key)
            if isinstance(v, list):
                dvir_defects.extend(v)
        unresolved = [
            d for d in dvir_defects
            if isinstance(d, dict) and not d.get("isResolved", d.get("resolved", True))
        ]
        if not unresolved:
            continue

        vname = _dvir_vehicle_name(dvir)
        if _is_excluded_unit(vname, excluded):
            continue

        defects.append({
            "vehicle": vname,
            "driver":  _dvir_driver_name(dvir),
            "created": _dvir_time(dvir),
            "kind":    _dvir_asset_kind(dvir),
            "defects": [
                d.get("comment") or d.get("defectType", "unspecified defect")
                for d in unresolved
            ],
        })
    return defects


# ------------------------------------------------------------------
# Driver log-certification check (uncertified + currently active)
# ------------------------------------------------------------------

# Duty statuses that count as "actively driving or on duty". Samsara's
# currentDutyStatus.hosStatusType is camelCase; we compare case-insensitively.
# personalConveyance (off-duty driving) and sleeperBed are intentionally excluded.
_ACTIVE_DUTY_STATUSES = {"driving", "onduty"}
_DUTY_STATUS_LABELS = {"driving": "Driving", "onduty": "On Duty"}


def _duty_status(clock_rec: dict) -> str | None:
    cds = clock_rec.get("currentDutyStatus")
    if isinstance(cds, dict) and cds.get("hosStatusType"):
        return str(cds["hosStatusType"])
    return clock_rec.get("hosStatusType")


def _extract_active_uncertified_drivers(
    daily_logs: list[dict],
    clocks: list[dict],
    today_str: str | None = None,
) -> list[dict]:
    """Drivers with uncertified daily HOS logs who are currently driving/on duty.

    Mirrors samsara_cert_nudge's uncertified-day logic — `logMetaData.isCertified`
    is false, the day is strictly before today (today's log is still open), and
    placeholder/stub driver names are dropped — then intersects with the live
    duty status from /fleet/hos/clocks, keeping only drivers presently in a
    `driving` or `onDuty` status.
    """
    if today_str is None:
        today_str = datetime.datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")

    # 1) Map currently-active drivers: id -> (name, pretty status).
    active: dict[str, tuple[str, str]] = {}
    for rec in clocks:
        if not isinstance(rec, dict):
            continue
        drv = rec.get("driver") or {}
        did = str(drv.get("id") or "").strip()
        if not did:
            continue
        status = (_duty_status(rec) or "").strip()
        if status.lower() in _ACTIVE_DUTY_STATUSES:
            active[did] = (drv.get("name") or "", _DUTY_STATUS_LABELS[status.lower()])

    # 2) Gather uncertified days per driver from the daily logs.
    by_driver: dict[str, dict] = {}
    for rec in daily_logs:
        if not isinstance(rec, dict):
            continue
        if (rec.get("logMetaData") or {}).get("isCertified"):
            continue
        drv = rec.get("driver") or {}
        did = str(drv.get("id") or "").strip()
        if not did:
            continue
        name = drv.get("name") or ""
        if _is_placeholder_name(name):
            continue
        day = (rec.get("startTime") or "")[:10]
        if not day or day >= today_str:
            continue
        by_driver.setdefault(did, {"name": name, "days": set()})["days"].add(day)

    # 3) Keep only uncertified drivers who are currently active.
    out = []
    for did, info in by_driver.items():
        if did not in active:
            continue
        name, status = active[did]
        days = sorted(info["days"])
        out.append({
            "driver": html.escape(str(name or info["name"] or f"driver {did}")),
            "status": status,
            "days": days,
            "count": len(days),
        })
    out.sort(key=lambda d: -d["count"])
    return out


def _extract_disqualified_drivers(graph_token: str, onedrive_upn: str) -> list[dict]:
    """Drivers who are disqualified to drive — either:
      - flagged by SambaSafety's Invalid License Report (DISQUALIFIED / SUSPENDED
        / REVOKED), or
      - carrying an expired DOT physical (Alvys Drivers sheet `MedicalExpiresAt`
        in the past).

    Reads the same OneDrive workbooks the daily brief uses
    (SambaSafety/SambaSafety_Master.xlsx and Alvys Pipeline.xlsx) and reuses the
    scorecard's compute_sambasafety / compute_alvys_drivers, so the
    disqualified/expired determination stays identical to page 2 of the brief.

    Entirely fail-soft: a missing file, missing API scope, or import error logs a
    warning and contributes no rows — the rest of the alert still sends. Returns
    one row per driver: {"driver": <display name>, "reasons": [str, ...]}.
    """
    try:
        import io
        import pandas as pd
        from src.onedrive_upload import download_file
        from src.scorecard_email import compute_sambasafety, compute_alvys_drivers
    except Exception as exc:
        log.warning("Disqualified-driver check unavailable (import failed): %s", exc)
        return []

    by_name: dict[str, dict] = {}

    def _add(name: str, reason: str) -> None:
        key = " ".join(str(name or "").strip().upper().split())
        if not key:
            return
        slot = by_name.setdefault(
            key, {"driver": html.escape(str(name).strip()), "reasons": []}
        )
        if reason not in slot["reasons"]:
            slot["reasons"].append(reason)

    # --- SambaSafety: disqualified / suspended / revoked licenses --------------
    samba_path = os.environ.get(
        "SCORECARD_SAMBASAFETY_PATH", "SambaSafety/SambaSafety_Master.xlsx"
    )
    try:
        samba_sheets = pd.read_excel(
            io.BytesIO(download_file(graph_token, onedrive_upn, samba_path)),
            sheet_name=None,
        )
        samba = compute_sambasafety(samba_sheets)
        flagged = [d for d in (samba or {}).get("drivers", []) if d.get("invalid")]
        for d in flagged:
            status = str(d.get("status") or "DISQUALIFIED").strip().upper()
            _add(d.get("name", ""), f"SambaSafety license: {html.escape(status)}")
        log.info("SambaSafety disqualification check: %d driver(s) flagged", len(flagged))
    except Exception as exc:
        log.warning("SambaSafety disqualification check skipped (%s): %s", samba_path, exc)

    # --- Alvys: expired DOT physical (medical card) ---------------------------
    pipe_path = os.environ.get("SCORECARD_ALVYS_PIPELINE_PATH", "Alvys Pipeline.xlsx")
    try:
        pipe_sheets = pd.read_excel(
            io.BytesIO(download_file(graph_token, onedrive_upn, pipe_path)),
            sheet_name=None,
        )
        alv = compute_alvys_drivers(pipe_sheets)
        n_exp = 0
        for d in (alv or {}).get("drivers", []):
            md = d.get("medical_days")
            if md is not None and md < 0:
                n_exp += 1
                exp = d.get("medical_exp")
                exp_str = exp.strftime("%Y-%m-%d") if hasattr(exp, "strftime") else str(exp)
                _add(d.get("name", ""), f"DOT physical expired {exp_str} ({abs(int(md))}d ago)")
        log.info("DOT-physical expiration check: %d driver(s) expired", n_exp)
    except Exception as exc:
        log.warning("DOT physical expiration check skipped (%s): %s", pipe_path, exc)

    return sorted(by_name.values(), key=lambda r: r["driver"].lower())


def _section_banner(title: str) -> str:
    return (
        f"<h2 style='font-size:17px;margin:22px 0 6px;padding-bottom:4px;"
        f"border-bottom:2px solid #333'>{title}</h2>"
    )


def _render_faults_table(lines: list[str], faults: list[dict]) -> None:
    lines.append("<h3 style='margin:10px 0 4px'>Active Faults (engine / maintenance)</h3>")
    lines.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>")
    lines.append("<tr><th align='left'>Vehicle</th><th align='left'>Current Driver</th>"
                 "<th align='left'>Active Faults</th></tr>")
    for issue in faults:
        fault_html = "<br>".join(issue["faults"])
        if issue["overflow"]:
            fault_html += (
                f"<br><em style='color:#cc0000'>+{issue['overflow']} more active "
                f"fault(s) — view all {issue['total']} on "
                "<a href='https://cloud.samsara.com'>Samsara</a></em>"
            )
        driver = issue.get("driver_name") or ""
        driver_cell = html.escape(driver) if driver else "&mdash;"
        lines.append(
            f"<tr><td valign='top'>{issue['vehicle_name']}</td>"
            f"<td valign='top'>{driver_cell}</td>"
            f"<td valign='top'>{fault_html}</td></tr>"
        )
    lines.append("</table>")


def _render_dvir_table(lines: list[str], defects: list[dict]) -> None:
    lines.append("<h3 style='margin:10px 0 4px'>Unresolved DVIR Defects</h3>")
    lines.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>")
    lines.append("<tr><th align='left'>Vehicle</th><th align='left'>Driver</th>"
                 "<th align='left'>Inspection Time</th><th align='left'>Defects</th></tr>")
    for d in defects:
        defect_str = "; ".join(d["defects"])
        lines.append(
            f"<tr><td valign='top'>{d['vehicle']}</td><td valign='top'>{d['driver']}</td>"
            f"<td valign='top'>{d['created']}</td><td valign='top'>{defect_str}</td></tr>"
        )
    lines.append("</table>")


def _render_drivers_table(lines: list[str], drivers: list[dict]) -> None:
    lines.append(
        "<p style='font-size:12px;color:#555;margin:4px 0'>"
        "Drivers below have uncertified daily HOS logs and are currently driving "
        "or on duty — please remind them to certify in the Samsara Driver App.</p>"
    )
    lines.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>")
    lines.append("<tr><th align='left'>Driver</th><th align='left'>Current Status</th>"
                 "<th align='left'>Uncertified Days</th></tr>")
    for d in drivers:
        days_str = ", ".join(d["days"]) if d["days"] else "&mdash;"
        label = f"{d['count']} day{'s' if d['count'] != 1 else ''}"
        lines.append(
            f"<tr><td valign='top'>{d['driver']}</td>"
            f"<td valign='top'>{html.escape(str(d['status']))}</td>"
            f"<td valign='top'>{label} ({days_str})</td></tr>"
        )
    lines.append("</table>")


def _render_disqualified_table(lines: list[str], drivers: list[dict]) -> None:
    lines.append("<h3 style='margin:10px 0 4px;color:#cc0000'>Disqualified Drivers</h3>")
    lines.append(
        "<p style='font-size:12px;color:#555;margin:4px 0'>"
        "Disqualified by SambaSafety (Invalid License Report) or carrying an "
        "expired DOT physical — these drivers should not be dispatched.</p>"
    )
    lines.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>")
    lines.append("<tr><th align='left'>Driver</th><th align='left'>Reason</th></tr>")
    for d in drivers:
        reason = "; ".join(d["reasons"])
        lines.append(
            f"<tr><td valign='top'><strong style='color:#cc0000'>{d['driver']}</strong></td>"
            f"<td valign='top'>{reason}</td></tr>"
        )
    lines.append("</table>")


def _build_email_body(
    active_faults: list[dict],
    dvir_defects: list[dict],
    active_uncertified: list[dict] | None = None,
    disqualified: list[dict] | None = None,
    fault_nudge: dict | None = None,
    test_mode: bool = False,
    test_to: str | None = None,
) -> str:
    active_uncertified = active_uncertified or []
    disqualified = disqualified or []
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "<h2 style='color:#cc0000'>XFreight Fleet Alert</h2>",
        f"<p><strong>Generated:</strong> {ts} CT</p>",
    ]

    if test_mode:
        lines.append(
            "<p style='background:#fff3cd;border:1px solid #ffc107;padding:8px 10px;"
            "color:#856404;font-weight:bold;border-radius:4px'>"
            "TEST MODE — fleet-alert changes are in progress, so this email is going "
            f"only to {html.escape(test_to or 'the tester')}. The normal recipient "
            "list is suppressed until test mode is turned off."
            "</p>"
        )

    lines.append("<hr>")

    # Split DVIR defects by asset class; faults are engine codes (tractors only).
    tractor_dvirs = [d for d in dvir_defects if d.get("kind") != "trailer"]
    trailer_dvirs = [d for d in dvir_defects if d.get("kind") == "trailer"]

    # Order per Jeff: Drivers first, then Tractors/Trucks, then Trailers.
    if disqualified or active_uncertified:
        lines.append(_section_banner("Drivers"))
        if disqualified:
            _render_disqualified_table(lines, disqualified)
        if active_uncertified:
            lines.append("<h3 style='margin:10px 0 4px'>Missing Log Certifications (On Duty / Driving)</h3>")
            _render_drivers_table(lines, active_uncertified)

    if active_faults or tractor_dvirs:
        lines.append(_section_banner("Tractors / Trucks"))
        if active_faults:
            _render_faults_table(lines, active_faults)
            if fault_nudge and fault_nudge.get("recipients"):
                _h = fault_nudge.get("max_age_hours", 12)
                _hs = str(int(_h)) if float(_h) == int(_h) else str(_h)
                if fault_nudge.get("dry_run"):
                    who = ", ".join(html.escape(r) for r in fault_nudge["recipients"])
                    lines.append(
                        "<p style='font-size:12px;color:#888;margin:4px 0'><em>"
                        f"Driver fault-nudges (faults logged in last {_hs}h; test mode "
                        f"&mdash; dry run, nothing sent to drivers): would notify {who}.</em></p>"
                    )
                elif fault_nudge.get("sent"):
                    who = ", ".join(html.escape(r) for r in fault_nudge["sent"])
                    lines.append(
                        "<p style='font-size:12px;color:#888;margin:4px 0'><em>"
                        f"Samsara Driver-App fault-nudge (faults logged in last {_hs}h) "
                        f"sent to: {who}.</em></p>"
                    )
                else:
                    lines.append(
                        "<p style='font-size:12px;color:#888;margin:4px 0'><em>"
                        "Current drivers were already nudged about these faults today.</em></p>"
                    )
        if tractor_dvirs:
            _render_dvir_table(lines, tractor_dvirs)

    if trailer_dvirs:
        lines.append(_section_banner("Trailers"))
        _render_dvir_table(lines, trailer_dvirs)

    lines.append(
        "<p style='color:#888;font-size:12px'>"
        "This alert was generated automatically by the XFreight fleet data pipeline."
        "</p>"
    )
    return "\n".join(lines)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    api_token = os.environ.get("SAMSARA_API_TOKEN")
    if not api_token:
        sys.exit("ERROR: SAMSARA_API_TOKEN not set")

    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    from_upn = os.environ.get("ALERT_FROM_UPN") or "jeff@xfreight.net"
    to_raw = os.environ.get("ALERT_TO_EMAILS") or from_upn
    to_emails = [e.strip() for e in to_raw.split(",") if e.strip()]

    # --- Test mode ------------------------------------------------------------
    # While fleet-alert changes are in progress, force every send to a single
    # tester and suppress the real ALERT_TO_EMAILS list. Default is ON; flip it
    # off by setting SAMSARA_ALERT_TEST_MODE=0 (env locally, or as a secret/var
    # in .github/workflows/samsara_refresh.yml) once the changes are validated.
    test_mode = os.environ.get("SAMSARA_ALERT_TEST_MODE", "1").strip().lower() not in (
        "0", "false", "no", "off", ""
    )
    test_to = os.environ.get("SAMSARA_ALERT_TEST_TO") or from_upn
    if test_mode:
        log.warning(
            "TEST MODE ON — overriding recipients to %s only (real list %s suppressed). "
            "Set SAMSARA_ALERT_TEST_MODE=0 to resume normal recipients.",
            test_to, to_emails,
        )
        to_emails = [test_to]

    client = SamsaraClient(api_token)

    log.info("Checking for active engine fault codes (truck maintenance)…")
    fault_records = client.fetch_fault_codes()
    vehicle_ids = [str(r.get("id")) for r in fault_records if r.get("id")]
    driver_by_vehicle = client.fetch_current_drivers(vehicle_ids)
    active_faults = _extract_active_faults(fault_records, driver_by_vehicle)

    log.info("Checking DVIRs for unresolved defects (last 7 days)…")
    now = datetime.datetime.utcnow()
    dvirs = client.fetch_dvirs(now - datetime.timedelta(days=7), now)
    dvir_defects = _extract_dvir_defects(dvirs)

    log.info("Checking driver log certifications vs. current duty status…")
    daily_logs = client.fetch_hos_daily_logs(now - datetime.timedelta(days=7), now)
    clocks = client.fetch_hos_clocks()
    active_uncertified = _extract_active_uncertified_drivers(daily_logs, clocks)

    # Graph token is needed both to read SambaSafety/Alvys (disqualified drivers)
    # and to send the email; fetch it once. Gate on Azure creds being present.
    onedrive_upn = os.environ.get("ONEDRIVE_USER_UPN") or from_upn
    graph_token = None
    disqualified: list[dict] = []
    if all([tenant_id, client_id, client_secret]):
        try:
            graph_token = get_token(tenant_id, client_id, client_secret)
        except Exception as exc:
            log.warning("Graph token fetch failed (%s) — cannot read SambaSafety/Alvys or send.", exc)
        if graph_token:
            log.info("Checking for disqualified drivers (SambaSafety DQ + expired DOT physical)…")
            disqualified = _extract_disqualified_drivers(graph_token, onedrive_upn)
    else:
        log.warning("Azure credentials not set — skipping disqualified-driver check and email send.")

    # Nudge the current driver of each faulted truck via the Samsara Driver App.
    # Dry-run (logs only) while in test mode; idempotent per Central day in prod.
    fault_nudge = _nudge_fault_drivers(
        client, active_faults, test_mode=test_mode,
        graph_token=graph_token, onedrive_upn=onedrive_upn,
    )
    if fault_nudge.get("recipients"):
        log.info("Fault nudges: %d target(s), %d sent (dry_run=%s)",
                 len(fault_nudge["recipients"]), len(fault_nudge.get("sent", [])),
                 fault_nudge.get("dry_run"))

    if not active_faults and not dvir_defects and not active_uncertified and not disqualified:
        log.info("No active faults, unresolved defects, uncertified active drivers, "
                 "or disqualified drivers — no alert needed.")
        return 0

    n_tractor_dvirs = sum(1 for d in dvir_defects if d.get("kind") != "trailer")
    n_trailer_dvirs = len(dvir_defects) - n_tractor_dvirs
    log.info(
        "Issues found: %d disqualified driver(s), %d uncertified active driver(s), "
        "%d vehicle(s) with active faults, %d tractor + %d trailer DVIR defect(s)",
        len(disqualified), len(active_uncertified),
        len(active_faults), n_tractor_dvirs, n_trailer_dvirs,
    )

    if graph_token is None:
        log.warning("No Graph token — logging issues but cannot send email.")
        for d in disqualified:
            log.warning("DISQUALIFIED: %s → %s", d["driver"], "; ".join(d["reasons"]))
        for d in active_uncertified:
            log.warning("UNCERTIFIED (%s): %s → %d day(s) %s",
                        d["status"], d["driver"], d["count"], ", ".join(d["days"]))
        for issue in active_faults:
            log.warning(
                "FAULTS: %s → %s%s",
                issue["vehicle_name"], "; ".join(issue["faults"]),
                f" (+{issue['overflow']} more)" if issue["overflow"] else "",
            )
        for d in dvir_defects:
            log.warning("DVIR defect [%s]: %s | %s | %s",
                        d.get("kind", "tractor"), d["vehicle"], d["created"], d["defects"])
        return 0

    total = len(disqualified) + len(active_uncertified) + len(active_faults) + len(dvir_defects)
    subject = f"[XFreight Fleet Alert] {total} issue(s) require attention"
    if test_mode:
        subject = "[TEST] " + subject
    body = _build_email_body(
        active_faults, dvir_defects, active_uncertified, disqualified,
        fault_nudge=fault_nudge, test_mode=test_mode, test_to=test_to,
    )

    send_alert_email(graph_token, from_upn, to_emails, subject, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
