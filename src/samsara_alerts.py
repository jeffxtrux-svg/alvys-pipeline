"""
Samsara diagnostic alert system.

Checks for:
  - Active OBD fault / DTC codes on any vehicle
  - DVIRs with unresolved defects (last 7 days)

Sends an HTML email via Microsoft Graph API when issues are found.

Required env vars:
    SAMSARA_API_TOKEN
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
    ALERT_FROM_UPN    — M365 mailbox to send from (e.g. jeff@xfreight.net)
    ALERT_TO_EMAILS   — comma-separated recipient list (defaults to ALERT_FROM_UPN)

IMPORTANT — one-time Azure setup required:
    The app registration needs "Mail.Send" Application permission in addition to
    the Files.ReadWrite.All it already has. Add it in Azure Portal →
    App registrations → API permissions → Add permission → Microsoft Graph →
    Application permissions → Mail.Send → Grant admin consent.
"""
from __future__ import annotations

import datetime
import logging
import os
import sys

import requests
from dotenv import load_dotenv

from src.samsara_client import SamsaraClient
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

def _extract_dtc_issues(fault_records: list[dict]) -> list[dict]:
    """Find vehicles with at least one active DTC code."""
    issues = []
    for record in fault_records:
        vehicle_name = record.get("name") or record.get("id", "unknown")

        # The stats endpoint returns a list of stat snapshots per vehicle.
        # Each snapshot has a `value` containing the DTC payload.
        codes: list[str] = []
        dtc_entry = record.get("nativeObdDtcCodes")

        if isinstance(dtc_entry, list):
            for snap in dtc_entry:
                val = snap.get("value", {})
                if isinstance(val, dict):
                    codes.extend(val.get("dtcIds", []))
                elif isinstance(val, list):
                    codes.extend(str(c) for c in val)
        elif isinstance(dtc_entry, dict):
            val = dtc_entry.get("value", {})
            if isinstance(val, dict):
                codes.extend(val.get("dtcIds", []))
            elif isinstance(val, list):
                codes.extend(str(c) for c in val)

        if codes:
            issues.append({
                "vehicle_name": vehicle_name,
                "dtc_codes": [str(c) for c in codes],
            })

    return issues


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


def _dvir_driver_name(dvir: dict) -> str:
    # Most thorough: walk every possible nesting.
    for path in (
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

        defects.append({
            "vehicle": _dvir_vehicle_name(dvir),
            "driver":  _dvir_driver_name(dvir),
            "created": _dvir_time(dvir),
            "defects": [
                d.get("comment") or d.get("defectType", "unspecified defect")
                for d in unresolved
            ],
        })
    return defects


def _build_email_body(dtc_issues: list[dict], dvir_defects: list[dict]) -> str:
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "<h2 style='color:#cc0000'>XFreight Fleet Alert</h2>",
        f"<p><strong>Generated:</strong> {ts} CT</p>",
        "<hr>",
    ]

    if dtc_issues:
        lines.append("<h3>Active Fault Codes / Warning Lights</h3>")
        lines.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>")
        lines.append("<tr><th>Vehicle</th><th>DTC Codes</th></tr>")
        for issue in dtc_issues:
            codes = ", ".join(issue["dtc_codes"])
            lines.append(f"<tr><td>{issue['vehicle_name']}</td><td>{codes}</td></tr>")
        lines.append("</table>")

    if dvir_defects:
        lines.append("<h3>Unresolved DVIR Defects</h3>")
        lines.append("<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>")
        lines.append("<tr><th>Vehicle</th><th>Driver</th><th>Inspection Time</th><th>Defects</th></tr>")
        for d in dvir_defects:
            defect_str = "; ".join(d["defects"])
            lines.append(
                f"<tr><td>{d['vehicle']}</td><td>{d['driver']}</td>"
                f"<td>{d['created']}</td><td>{defect_str}</td></tr>"
            )
        lines.append("</table>")
        # If every row came back unknown, surface that explicitly so the reader
        # knows the data is incomplete rather than assuming three anonymous trucks.
        unknown_rows = sum(
            1 for d in dvir_defects
            if d["vehicle"] == "unknown vehicle" and d["driver"] == "unknown driver"
        )
        if unknown_rows == len(dvir_defects):
            lines.append(
                "<p style='color:#cc0000;font-size:12px'>"
                "All rows above are missing vehicle and driver identifiers — "
                "Samsara's DVIR response did not include them. Check "
                "<code>output/samsara/Samsara_Master.xlsx</code> DVIR sheet for full detail."
                "</p>"
            )

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

    client = SamsaraClient(api_token)

    log.info("Checking for active DTC fault codes…")
    fault_records = client.fetch_fault_codes()
    dtc_issues = _extract_dtc_issues(fault_records)

    log.info("Checking DVIRs for unresolved defects (last 7 days)…")
    now = datetime.datetime.utcnow()
    dvirs = client.fetch_dvirs(now - datetime.timedelta(days=7), now)
    dvir_defects = _extract_dvir_defects(dvirs)

    if not dtc_issues and not dvir_defects:
        log.info("No active faults or unresolved defects — no alert needed.")
        return 0

    log.info(
        "Issues found: %d vehicle(s) with fault codes, %d DVIR defect(s)",
        len(dtc_issues), len(dvir_defects),
    )

    if not all([tenant_id, client_id, client_secret]):
        log.warning("Azure credentials not set — logging issues but cannot send email.")
        for issue in dtc_issues:
            log.warning("DTC: %s → %s", issue["vehicle_name"], issue["dtc_codes"])
        for d in dvir_defects:
            log.warning("DVIR defect: %s | %s | %s", d["vehicle"], d["created"], d["defects"])
        return 0

    access_token = get_token(tenant_id, client_id, client_secret)

    total = len(dtc_issues) + len(dvir_defects)
    subject = f"[XFreight Fleet Alert] {total} issue(s) require attention"
    body = _build_email_body(dtc_issues, dvir_defects)

    send_alert_email(access_token, from_upn, to_emails, subject, body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
