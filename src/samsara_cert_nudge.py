"""
Samsara driver-cert nudge.

For each driver with uncertified daily logs in the last 7 days, send a
short message to their Samsara Driver App inbox asking them to certify.

Endpoint: POST /v1/fleet/messages — see samsara_client.send_driver_messages.
Token needs the **Write Messages** scope (Driver Workflow → Write Messages).

Idempotency: OneDrive marker `Samsara/cert-nudge-sent-{YYYY-MM-DD}.txt`.
A given day fires at most one nudge per driver — re-runs the same day
short-circuit on the marker. The marker is keyed to America/Chicago so a
day flip aligns with the daily cadence.

Required env vars:
    SAMSARA_API_TOKEN
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
Optional:
    CERT_NUDGE_DRY_RUN=1  — log what would be sent, skip the POST
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from src.samsara_client import SamsaraClient
from src.onedrive_upload import get_token, download_file, upload_file, ensure_folder

log = logging.getLogger("samsara_cert_nudge")

MARKER_FOLDER = "Samsara"


def _today_chi() -> str:
    return datetime.datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")


def _marker_path() -> str:
    return f"{MARKER_FOLDER}/cert-nudge-sent-{_today_chi()}.txt"


def _marker_exists(tok: str, upn: str) -> bool:
    """True if today's nudge marker is already in OneDrive."""
    try:
        download_file(tok, upn, _marker_path())
        return True
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return False
        raise


def _write_marker(tok: str, upn: str, body: str) -> None:
    """Write today's marker by uploading a small text file. The
    onedrive_upload helper takes a Path, so we land the content in a
    tempfile first."""
    import tempfile
    from pathlib import Path
    ensure_folder(tok, upn, MARKER_FOLDER)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write(body + "\n")
        tmp = Path(tf.name)
    name = _marker_path().split("/", 1)[1]
    upload_file(tok, upn, folder_path=MARKER_FOLDER,
                filename=name, file_path=tmp)


def _first_name(full: str) -> str:
    return (full or "").strip().split()[0] if full else ""


def _compose_message(first: str, days: int, earliest: str, latest: str) -> str:
    span = earliest if earliest == latest else f"{earliest} – {latest}"
    word = "log" if days == 1 else "logs"
    return (
        f"Hi {first or 'driver'}, you have {days} uncertified daily {word} "
        f"in Samsara ({span}). Please open the Samsara Driver App → My Day "
        f"and certify each pending day to stay compliant. Thanks!"
    )


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    token = os.environ.get("SAMSARA_API_TOKEN")
    if not token:
        log.error("SAMSARA_API_TOKEN not set — aborting.")
        return 1
    upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not upn:
        log.error("ONEDRIVE_USER_UPN not set — aborting.")
        return 1

    graph_tok = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )

    if _marker_exists(graph_tok, upn):
        log.info("Marker present for %s — already nudged today. Skipping.",
                 _today_chi())
        return 0

    client = SamsaraClient(token)
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=7)

    log.info("Fetching HOS daily logs %s → %s…", start.date(), now.date())
    raw = client.fetch_hos_daily_logs(start, now)
    if not raw:
        log.info("No daily logs returned — nothing to nudge.")
        _write_marker(graph_tok, upn, "no-daily-logs")
        return 0

    # Group uncertified logs by driver id. Driver name lifted from the
    # nested driver dict on each daily-log record.
    by_driver: dict[str, dict] = {}
    for rec in raw:
        if not isinstance(rec, dict):
            continue
        meta = rec.get("logMetaData") or {}
        if meta.get("isCertified"):
            continue
        drv = rec.get("driver") or {}
        did = str(drv.get("id") or "").strip()
        if not did:
            continue
        # startTime is the day boundary in the driver's timezone.
        day = (rec.get("startTime") or "")[:10]
        slot = by_driver.setdefault(did, {
            "name": drv.get("name") or "",
            "days": [],
        })
        if day:
            slot["days"].append(day)

    if not by_driver:
        log.info("All daily logs certified — nothing to nudge.")
        _write_marker(graph_tok, upn, "all-certified")
        return 0

    dry = os.environ.get("CERT_NUDGE_DRY_RUN", "").strip() == "1"
    log.info("%s%d driver(s) with uncertified logs",
             "DRY RUN — " if dry else "", len(by_driver))

    sent = 0
    skipped = 0
    for did, info in sorted(by_driver.items(), key=lambda kv: -len(kv[1]["days"])):
        days_sorted = sorted(set(info["days"]))
        if not days_sorted:
            continue
        first = _first_name(info["name"])
        msg = _compose_message(first, len(days_sorted),
                               days_sorted[0], days_sorted[-1])
        log.info("  → %s (id=%s): %d day(s) %s..%s — %r",
                 info["name"] or "(unknown)", did, len(days_sorted),
                 days_sorted[0], days_sorted[-1], msg)
        if dry:
            skipped += 1
            continue
        result = client.send_driver_messages([did], msg)
        if result is not None:
            sent += 1
        else:
            skipped += 1

    log.info("Cert nudge complete: %d sent, %d skipped (dry=%s)",
             sent, skipped, dry)
    _write_marker(graph_tok, upn,
                  f"sent={sent} skipped={skipped} dry={int(dry)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
