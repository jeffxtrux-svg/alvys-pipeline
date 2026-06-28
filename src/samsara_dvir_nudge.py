"""
Samsara DVIR compliance nudge.

After each Samsara data refresh, checks the last DVIR_NUDGE_DAYS (default: 2)
calendar days for drivers who had HOS log entries but fewer DVIRs than required.
FMCSA 396.11 requires a pre-trip AND post-trip inspection per vehicle type per
working day: 2 tractor + 2 trailer = 4 total per driver per working day.

Sends a short Samsara Driver App message to each non-compliant driver.
Each driver×date pair is nudged at most once — idempotency via an OneDrive
JSON marker at Samsara/dvir-nudge-sent.json so the 8x/day refresh never
spams a driver who already got the message.

Required env vars:
    SAMSARA_API_TOKEN
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
Optional:
    SAMSARA_OUTPUT_DIR   (default: output/samsara)
    DVIR_NUDGE_DRY_RUN=1 — log without sending
    DVIR_NUDGE_DAYS=2    — how many calendar days back to check
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

from src.samsara_client import SamsaraClient
from src.onedrive_upload import get_token, download_file, upload_file, ensure_folder

log = logging.getLogger("samsara_dvir_nudge")

MARKER_FOLDER = "Samsara"
MARKER_NAME   = "dvir-nudge-sent.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_chi() -> datetime.date:
    return datetime.datetime.now(ZoneInfo("America/Chicago")).date()


def _find_col(df: pd.DataFrame, needles: list[str]) -> str | None:
    norm = {str(c).lower().replace(" ", "").replace(".", ""): c for c in df.columns}
    for needle in needles:
        k = needle.lower().replace(" ", "").replace(".", "")
        if k in norm:
            return norm[k]
    return None


def _to_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None).dt.date


def _load_sheets(output_dir: str) -> dict[str, pd.DataFrame]:
    path = Path(output_dir) / "Samsara_Master.xlsx"
    if not path.exists():
        log.warning("Samsara_Master.xlsx not found at %s", path)
        return {}
    xl = pd.ExcelFile(path)
    sheets = {s: xl.parse(s) for s in xl.sheet_names}
    log.info("Loaded %d sheets from %s", len(sheets), path)
    return sheets


def _compute_misses(sheets: dict, days_back: int) -> list[dict]:
    """Return [{driver_name, date, miss_t, miss_tr}] for drivers with
    fewer DVIRs than required in the last days_back calendar dates."""
    hos = sheets.get("HOS_DailyLogs")
    dvirs = sheets.get("DVIRs")
    if hos is None or hos.empty:
        log.info("HOS_DailyLogs sheet empty — no working-days data.")
        return []

    today  = _today_chi()
    cutoff = today - datetime.timedelta(days=days_back)

    # Build set of (driver_name, date) pairs from HOS logs
    hn = _find_col(hos, ["driver name", "driver.name"])
    hd = _find_col(hos, ["logstartdate", "log start date", "date", "logmetadata.logdate"])
    if not hn or not hd:
        log.warning("HOS_DailyLogs: driver-name or date column not found — skipping.")
        return []

    h = hos[[hn, hd]].copy()
    h["_name"] = h[hn].astype(str).str.strip()
    h["_date"] = _to_date(h[hd])
    h = h[h["_date"].notna() & h["_name"].ne("") & h["_name"].ne("nan")
          & (h["_date"] > cutoff) & (h["_date"] <= today)]
    worked_pairs: set[tuple[str, object]] = set(zip(h["_name"], h["_date"]))
    log.info("Found %d driver×date working pairs in last %d days.", len(worked_pairs), days_back)

    if not worked_pairs:
        return []

    # Count DVIRs per (driver, date) split by tractor/trailer
    trac_done: dict[tuple, int] = {}
    trlr_done: dict[tuple, int] = {}
    if dvirs is not None and not dvirs.empty:
        dn  = _find_col(dvirs, ["driver.name", "driver name",
                                  "authorsignature.signatoryuser.name",
                                  "submittedby.name", "createdby.name"])
        dt  = _find_col(dvirs, ["starttime", "start time",
                                  "createdattime", "submittedattime"])
        dv  = _find_col(dvirs, ["vehicle.name", "vehicle name"])
        dtr = _find_col(dvirs, ["trailer.name", "trailer name", "asset.name"])
        if dn and dt:
            d = dvirs[[dn, dt] + ([dv] if dv else []) + ([dtr] if dtr else [])].copy()
            d["_name"] = d[dn].astype(str).str.strip()
            d["_date"] = _to_date(d[dt])
            d = d[d["_date"].notna() & (d["_date"] > cutoff) & (d["_date"] <= today)]
            for _, row in d.iterrows():
                key = (row["_name"], row["_date"])
                has_v  = dv  and pd.notna(row[dv])  and str(row[dv]).strip()  not in ("", "nan")
                has_tr = dtr and pd.notna(row[dtr]) and str(row[dtr]).strip() not in ("", "nan")
                if has_v:
                    trac_done[key] = trac_done.get(key, 0) + 1
                if has_tr:
                    trlr_done[key] = trlr_done.get(key, 0) + 1
                if not has_v and not has_tr:
                    trac_done[key] = trac_done.get(key, 0) + 1

    misses = []
    for name, date in sorted(worked_pairs):
        key   = (name, date)
        td    = trac_done.get(key, 0)
        trd   = trlr_done.get(key, 0)
        miss_t  = max(0, 2 - td)
        miss_tr = max(0, 2 - trd)
        if miss_t + miss_tr > 0:
            misses.append({
                "driver_name": name,
                "date":        str(date),
                "trac_done":   td,
                "trlr_done":   trd,
                "miss_t":      miss_t,
                "miss_tr":     miss_tr,
            })
    log.info("%d driver×date pair(s) with missing DVIRs.", len(misses))
    return misses


def _build_id_map(client: SamsaraClient, sheets: dict) -> dict[str, str]:
    """Build lowercase-name → Samsara driver ID map."""
    drv_sheet = sheets.get("Drivers")
    if drv_sheet is not None and not drv_sheet.empty:
        id_col = _find_col(drv_sheet, ["id", "driverid"])
        nm_col = _find_col(drv_sheet, ["name"])
        if id_col and nm_col:
            result: dict[str, str] = {}
            for _, row in drv_sheet.iterrows():
                did = str(row[id_col]).strip()
                nm  = str(row[nm_col]).strip()
                if did and nm and did.lower() not in ("nan", "") and nm.lower() not in ("nan", ""):
                    result[nm.lower()] = did
            if result:
                log.info("Driver ID map from local sheet: %d entries.", len(result))
                return result
    log.info("Fetching drivers from Samsara API for ID map…")
    drivers = client.fetch_drivers()
    return {
        str(d.get("name") or "").strip().lower(): str(d.get("id") or "").strip()
        for d in drivers
        if d.get("name") and d.get("id")
    }


def _lookup_driver_id(name: str, id_map: dict[str, str]) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    if key in id_map:
        return id_map[key]
    # Title-case fallback (Samsara names can be ALL-CAPS in one sheet, title in another)
    if key.title() in id_map or name.title().lower() in id_map:
        return id_map.get(name.title().lower())
    # First-name partial match as last resort
    first = key.split()[0] if key.split() else ""
    if first:
        return next((v for k, v in id_map.items() if k.startswith(first)), None)
    return None


def _load_marker(tok: str, upn: str) -> dict[str, bool]:
    try:
        raw = download_file(tok, upn, f"{MARKER_FOLDER}/{MARKER_NAME}")
        return json.loads(raw.decode("utf-8"))
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return {}
        raise
    except Exception as e:
        log.warning("Could not load DVIR nudge marker: %s", e)
        return {}


def _save_marker(tok: str, upn: str, data: dict) -> None:
    ensure_folder(tok, upn, MARKER_FOLDER)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(data, tf, indent=2)
        tmp = Path(tf.name)
    upload_file(tok, upn, folder_path=MARKER_FOLDER, filename=MARKER_NAME, file_path=tmp)
    tmp.unlink(missing_ok=True)


def _first_name(full: str) -> str:
    parts = (full or "").strip().split()
    return parts[0].title() if parts else "driver"


def _compose_message(name: str, date: str, miss_t: int, miss_tr: int) -> str:
    first  = _first_name(name)
    parts  = []
    if miss_t:
        parts.append(f"{miss_t} tractor inspection{'s' if miss_t > 1 else ''}")
    if miss_tr:
        parts.append(f"{miss_tr} trailer inspection{'s' if miss_tr > 1 else ''}")
    missing_str = " and ".join(parts)
    return (
        f"Hi {first} — you are missing {missing_str} for {date}. "
        f"FMCSA 396.11 requires a pre-trip and post-trip DVIR every working day. "
        f"Please complete the inspection(s) in the Samsara Driver App as soon as possible. "
        f"Contact dispatch with any questions."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    api_token = os.environ.get("SAMSARA_API_TOKEN")
    if not api_token:
        log.error("SAMSARA_API_TOKEN not set — aborting.")
        return 1
    upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not upn:
        log.error("ONEDRIVE_USER_UPN not set — aborting.")
        return 1

    output_dir = os.environ.get("SAMSARA_OUTPUT_DIR", "output/samsara")
    days_back  = int(os.environ.get("DVIR_NUDGE_DAYS", "2"))
    dry        = os.environ.get("DVIR_NUDGE_DRY_RUN", "").strip() == "1"

    if dry:
        log.info("DVIR_NUDGE_DRY_RUN=1 — will log without sending.")

    sheets = _load_sheets(output_dir)
    if not sheets:
        log.info("No Samsara sheets available — skipping.")
        return 0

    misses = _compute_misses(sheets, days_back)
    if not misses:
        log.info("All drivers DVIR-compliant for the last %d day(s).", days_back)
        return 0

    graph_tok = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )
    marker = _load_marker(graph_tok, upn)
    client = SamsaraClient(api_token)
    id_map = _build_id_map(client, sheets)

    sent = skipped_dup = skipped_no_id = 0
    marker_dirty = False

    for m in misses:
        name = m["driver_name"]
        date = m["date"]
        key  = f"{name}::{date}"

        if marker.get(key):
            log.info("  Already nudged %s on %s — skipping.", name, date)
            skipped_dup += 1
            continue

        did = _lookup_driver_id(name, id_map)
        if not did:
            log.warning("  No Samsara driver ID for %r — cannot message.", name)
            skipped_no_id += 1
            continue

        msg = _compose_message(name, date, m["miss_t"], m["miss_tr"])
        log.info(
            "  → %s (id=%s)  date=%s  miss_t=%d  miss_tr=%d%s",
            name, did, date, m["miss_t"], m["miss_tr"],
            "  [DRY RUN]" if dry else "",
        )
        log.info("    %r", msg)

        if dry:
            sent += 1
            continue

        result = client.send_driver_messages([did], msg)
        if result is not None:
            sent += 1
            marker[key] = True
            marker_dirty = True
        else:
            log.warning("  Send failed for %s — will retry next refresh.", name)

    if marker_dirty:
        try:
            _save_marker(graph_tok, upn, marker)
            log.info("Marker saved (%d total entries).", len(marker))
        except Exception as e:
            log.warning("Could not save nudge marker: %s", e)

    log.info(
        "DVIR nudge done: %d sent, %d already-sent skipped, %d no-id skipped (dry=%s)",
        sent, skipped_dup, skipped_no_id, dry,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
