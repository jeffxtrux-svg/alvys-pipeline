"""
Samsara row-count regression check.

Compares each sheet's row count in today's Samsara_Master.xlsx against
yesterday's run, stored as a small JSON snapshot in OneDrive
(`Samsara/_row_counts.json`). When a sheet that had data on the prior
run lands empty today — typically because an API endpoint regressed,
the token lost a scope, or a date-window param drifted past the API's
allowed range — email the standing alert list so the silent placeholder
doesn't go unnoticed in the brief.

This is exactly the failure mode that hid the HOS daily-logs endDate
bug for several runs: the API rejected the request, write_samsara_xlsx
laid down a placeholder `(no data retrieved)` sheet, and the brief
just looked clean-but-wrong.

Runs as a step in samsara_refresh.yml after samsara_onedrive_upload.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from src.onedrive_upload import (
    download_file,
    ensure_folder,
    get_token,
    upload_file,
)
from src.scorecard_email import send_email

log = logging.getLogger("samsara_regression_check")

SNAPSHOT_FOLDER = "Samsara"
SNAPSHOT_NAME = "_row_counts.json"
SNAPSHOT_PATH = f"{SNAPSHOT_FOLDER}/{SNAPSHOT_NAME}"

# Sheets where 0 rows is the expected steady state. CoachingSessions /
# TrainingAssignments wrap /coaching/sessions + /training/assignments,
# both of which 404 for our tenant scope — known long-standing gap,
# not a regression. IFTA_* sheets churn month-over-month; the current
# month often has 0 rows mid-month while Samsara processes data.
_ALWAYS_EMPTY = {"CoachingSessions", "TrainingAssignments"}


def _row_counts_for(path: Path) -> dict[str, int]:
    """Map sheet name → row count for a workbook. Placeholder sheets
    written as `(no data retrieved)` 0×1 by write_samsara_xlsx count
    as 0 here, same as a truly empty sheet."""
    counts: dict[str, int] = {}
    sheets = pd.read_excel(path, sheet_name=None)
    for name, df in sheets.items():
        counts[name] = int(len(df))
    return counts


def _download_prev(tok: str, upn: str) -> dict | None:
    """Returns the parsed snapshot dict, or None if no snapshot yet."""
    try:
        body = download_file(tok, upn, SNAPSHOT_PATH)
        return json.loads(body.decode("utf-8"))
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            log.info("No prior snapshot at %s — first run.", SNAPSHOT_PATH)
            return None
        raise


def _upload_snapshot(tok: str, upn: str, snapshot: dict) -> None:
    ensure_folder(tok, upn, SNAPSHOT_FOLDER)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(snapshot, tf, indent=2, sort_keys=True)
        tmp = Path(tf.name)
    upload_file(tok, upn, folder_path=SNAPSHOT_FOLDER,
                filename=SNAPSHOT_NAME, file_path=tmp)


def _is_ifta_current_month(sheet_name: str) -> bool:
    """IFTA_YYYY_MM sheet for the current calendar month — Samsara's
    IFTA report often returns empty mid-month while data processes.
    Suppress alerts for that specific case."""
    if not sheet_name.startswith("IFTA_"):
        return False
    today = datetime.date.today()
    return sheet_name == f"IFTA_{today.year}_{today.month:02d}"


def _send_alert(tok: str, upn: str,
                regressions: list[tuple[str, int, int]],
                prev_snapshot: dict | None) -> None:
    to_emails = [e.strip() for e in
                 os.environ.get("ALERT_TO_EMAILS", "jeff@xfreight.net").split(",")
                 if e.strip()]
    from_upn = os.environ.get("ALERT_FROM_UPN", upn)
    prev_as_of = (prev_snapshot or {}).get("as_of", "unknown")
    rows = "".join(
        f"<tr><td>{s}</td>"
        f"<td style='text-align:right'>{p}</td>"
        f"<td style='text-align:right;color:#c00'>{c}</td></tr>"
        for s, p, c in regressions
    )
    html = (
        f"<p>The Samsara pull just wrote an empty (or placeholder) sheet "
        f"for one or more tables that had data on the previous run. This "
        f"usually means an API endpoint regressed, the token lost a scope, "
        f"or a date-window param drifted past the API's allowed range.</p>"
        f"<p><b>Prior snapshot:</b> {prev_as_of}</p>"
        f"<table border='1' cellpadding='6' cellspacing='0' "
        f"style='border-collapse:collapse'>"
        f"<tr><th>Sheet</th><th>Prior rows</th><th>Now</th></tr>"
        f"{rows}"
        f"</table>"
        f"<p>Investigate the <code>samsara_refresh</code> workflow logs "
        f"for the affected fetch step — look for an HTTP 400/401/403/404 "
        f"on the matching endpoint.</p>"
    )
    subj = (f"⚠️ XFreight Samsara — {len(regressions)} "
            f"sheet(s) empty after refresh")
    send_email(tok, from_upn, to_emails, subj, html)
    log.info("Regression alert emailed to %s", to_emails)


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    out_dir = Path(os.environ.get("SAMSARA_OUTPUT_DIR", "output/samsara"))
    xlsx = out_dir / "Samsara_Master.xlsx"
    if not xlsx.exists():
        log.warning("No %s — skipping regression check.", xlsx)
        return 0

    current = _row_counts_for(xlsx)
    log.info("Current row counts (%d sheets): %s", len(current), current)

    upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not upn:
        log.warning("ONEDRIVE_USER_UPN not set — skipping snapshot persistence.")
        return 0

    tok = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )

    prev_snapshot = _download_prev(tok, upn)
    prev = (prev_snapshot or {}).get("counts", {})

    regressions: list[tuple[str, int, int]] = []
    for sheet, cur_count in current.items():
        if sheet in _ALWAYS_EMPTY or _is_ifta_current_month(sheet):
            continue
        prev_count = int(prev.get(sheet, 0))
        if prev_count > 0 and cur_count == 0:
            regressions.append((sheet, prev_count, cur_count))

    if regressions:
        log.warning("REGRESSION DETECTED on %d sheet(s):", len(regressions))
        for s, p, c in regressions:
            log.warning("  %s: %d → %d rows", s, p, c)
        try:
            _send_alert(tok, upn, regressions, prev_snapshot)
        except Exception as e:
            log.warning("Alert email failed: %s — snapshot will still update.", e)
    else:
        log.info("No regressions vs. prior snapshot.")

    # Always overwrite the snapshot — keeps the next run's comparison
    # honest about today's state. If today regressed and tomorrow
    # recovers, tomorrow won't re-alert (correct: alerts fire on fresh
    # drops, not on stable-empty or recovery transitions).
    _upload_snapshot(tok, upn, {
        "as_of": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "counts": current,
    })
    log.info("Snapshot updated at %s", SNAPSHOT_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
