"""
Entry point for the Samsara → Excel pipeline.

Run locally:
    python -m src.samsara_main

Reads SAMSARA_API_TOKEN from .env (local) or environment (GitHub Actions).
Writes output/samsara/Samsara_Master.xlsx with one sheet per data type.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.samsara_client import SamsaraClient

# openpyxl rejects ASCII control chars (except tab/LF/CR) embedded in strings
_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _sanitize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Strip illegal Excel characters from all string cells."""
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].apply(
            lambda v: _ILLEGAL_CHARS.sub("", v) if isinstance(v, str) else v
        )
    return df


# --- Samsara value normalizers ------------------------------------------------
# Samsara returns timestamps as either epoch-ms (e.g. createdAtMs) or ISO-8601
# strings. Downstream (the scorecard window filters) needs a parseable form.
def _ts_to_str(value) -> str | None:
    """Epoch-ms (int/numeric str) or ISO-8601 string → 'YYYY-MM-DD HH:MM:SS' UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            return datetime.datetime.utcfromtimestamp(int(value) / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        except (ValueError, OverflowError, OSError):
            return None
    try:
        return datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def build_dvir_defects(raw_dvirs: list[dict]) -> pd.DataFrame:
    """One row per DVIR defect (unit, driver, defect, resolved flag, time).

    json_normalize leaves the nested ``defects[]`` array as an unusable list
    cell, so we explode it here — same field shape that samsara_alerts.py reads.
    Keeps both resolved and unresolved so the scorecard can filter on ``Resolved``.
    """
    rows: list[dict] = []
    for dvir in raw_dvirs or []:
        defects = dvir.get("defects")
        if not isinstance(defects, list) or not defects:
            continue
        vehicle = dvir.get("vehicle") or {}
        driver = dvir.get("driver") or {}
        unit = vehicle.get("name") or vehicle.get("id")
        driver_name = driver.get("name") or driver.get("id")
        reported = _ts_to_str(dvir.get("createdAtMs") or dvir.get("createdAt"))
        dvir_type = dvir.get("inspectionType") or dvir.get("dvirType")
        for d in defects:
            if not isinstance(d, dict):
                continue
            rows.append({
                "Reported": reported,
                "Unit": unit,
                "Driver": driver_name,
                "Defect": d.get("comment") or d.get("defectType") or "unspecified defect",
                "Defect Type": d.get("defectType"),
                "Resolved": bool(d.get("resolved", False)),
                "Mechanic Notes": d.get("mechanicNotes") or d.get("resolvedComment"),
                "DVIR Type": dvir_type,
            })
    return pd.DataFrame(rows)


# Coarse severity buckets keyed off behavior names (adjust as needed).
_HIGH_SEVERITY = (
    "forward collision", "collision warning", "crash", "harsh brake",
    "following distance", "no seat belt", "ran red", "lane departure",
    "distracted", "drowsy", "mobile usage", "rolling stop",
)
_MED_SEVERITY = ("speeding", "harsh accel", "harsh turn", "harsh corner")


def _safety_event_type(rec: dict) -> str | None:
    """Decode the behaviorLabels array into a clean comma-joined event type."""
    labels = rec.get("behaviorLabels")
    if labels is None:
        labels = rec.get("behaviors")
    names: list[str] = []
    if isinstance(labels, list):
        for b in labels:
            if isinstance(b, dict):
                name = b.get("name") or b.get("label") or b.get("type")
            elif isinstance(b, str):
                name = b
            else:
                name = None
            if name:
                names.append(str(name))
    elif isinstance(labels, str):
        names.append(labels)
    if names:
        return ", ".join(dict.fromkeys(names))  # dedupe, preserve order
    return rec.get("name") or rec.get("eventType")


def _severity_for(event_type: str | None) -> str | None:
    if not event_type:
        return None
    t = event_type.lower()
    if any(k in t for k in _HIGH_SEVERITY):
        return "High"
    if any(k in t for k in _MED_SEVERITY):
        return "Medium"
    return "Low"


def _hos_violation_type(rec: dict) -> str | None:
    return (
        rec.get("violationType")
        or rec.get("type")
        or rec.get("hosViolationType")
        or rec.get("name")
        or (rec.get("violation") or {}).get("type")
    )


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.exit(f"ERROR: required env var {key!r} not set. Check your .env file.")
    return val


def flatten(records: list[dict], label: str = "") -> pd.DataFrame:
    """Flatten nested JSON records into a DataFrame via json_normalize."""
    log = logging.getLogger("samsara_main")
    if not records:
        if label:
            log.info("  %s: no records", label)
        return pd.DataFrame()
    try:
        df = pd.json_normalize(records, max_level=4)
        if label:
            log.info("  %s: %d rows × %d cols", label, len(df), len(df.columns))
        return df
    except Exception as e:
        log.warning("json_normalize failed for %s (%s) — falling back to basic DataFrame", label, e)
        return pd.DataFrame(records)


def write_samsara_xlsx(sheets: dict[str, pd.DataFrame], output_path: Path) -> None:
    log = logging.getLogger("samsara_main")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Writing %s", output_path)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            if df.empty:
                log.warning("  %s: no data — writing placeholder sheet", sheet_name)
                df = pd.DataFrame({"(no data retrieved)": []})
            df = _sanitize_df(df)
            # Excel sheet names max 31 chars
            safe_name = sheet_name[:31]
            df.to_excel(writer, sheet_name=safe_name, index=False)
            log.info("  %s: %d rows × %d cols", safe_name, len(df), len(df.columns))

    log.info("Done: %s", output_path.resolve())


def main() -> int:
    setup_logging()
    load_dotenv()
    log = logging.getLogger("samsara_main")

    api_token = get_required("SAMSARA_API_TOKEN")
    output_dir = Path(os.environ.get("SAMSARA_OUTPUT_DIR", "output/samsara"))
    days_back = int(os.environ.get("SAMSARA_DAYS_BACK", "90"))
    # Safety/DVIR/HOS-violation history must cover the scorecard's "previous
    # 6 months" window, so default to ~190 days (independent of trips, which
    # are per-vehicle and costlier to pull far back).
    safety_days_back = int(os.environ.get("SAMSARA_SAFETY_DAYS_BACK", "190"))

    now = datetime.datetime.utcnow()
    start_long = now - datetime.timedelta(days=days_back)
    start_safety = now - datetime.timedelta(days=safety_days_back)
    start_hos = now - datetime.timedelta(days=30)

    log.info("Samsara → Excel pipeline starting")
    log.info("Trips window               : %s → now (%d days)", start_long.date(), days_back)
    log.info("Safety/DVIR/HOS-viol window: %s → now (%d days)", start_safety.date(), safety_days_back)
    log.info("HOS-logs window            : %s → now (30 days)", start_hos.date())
    log.info("Output dir                 : %s", output_dir.resolve())

    client = SamsaraClient(api_token)

    log.info("=" * 60)
    log.info("Step 1/9: Vehicles")
    log.info("=" * 60)
    raw_vehicles = client.fetch_vehicles()

    log.info("=" * 60)
    log.info("Step 2/9: Drivers")
    log.info("=" * 60)
    raw_drivers = client.fetch_drivers()

    log.info("=" * 60)
    log.info("Step 3/9: Vehicle Stats (odometer, fuel, engine state)")
    log.info("=" * 60)
    raw_stats = client.fetch_vehicle_stats()

    log.info("=" * 60)
    log.info("Step 4/9: Current Locations")
    log.info("=" * 60)
    raw_locations = client.fetch_locations()

    log.info("=" * 60)
    log.info("Step 5/9: Trips (%d days)", days_back)
    log.info("=" * 60)
    vehicle_ids = [v["id"] for v in raw_vehicles if "id" in v]
    raw_trips = client.fetch_trips(start_long, now, vehicle_ids)

    log.info("=" * 60)
    log.info("Step 6/10: Safety Events (%d days)", safety_days_back)
    log.info("=" * 60)
    raw_safety = client.fetch_safety_events(start_safety, now)

    log.info("=" * 60)
    log.info("Step 7/10: HOS Logs (30 days)")
    log.info("=" * 60)
    raw_hos = client.fetch_hos_logs(start_hos, now)

    log.info("=" * 60)
    log.info("Step 8/10: HOS Violations (%d days)", safety_days_back)
    log.info("=" * 60)
    raw_hos_viol = client.fetch_hos_violations(start_safety, now)

    log.info("=" * 60)
    log.info("Step 9/10: DVIRs (%d days)", safety_days_back)
    log.info("=" * 60)
    raw_dvirs = client.fetch_dvirs(start_safety, now)

    log.info("=" * 60)
    log.info("Step 10/10: IFTA (last 3 months)")
    log.info("=" * 60)
    ifta_sheets: dict[str, pd.DataFrame] = {}
    for months_ago in range(3):
        target = (now.replace(day=1) - datetime.timedelta(days=months_ago * 28)).replace(day=1)
        raw_ifta = client.fetch_ifta(target.year, target.month)
        if raw_ifta:
            df_ifta = flatten(raw_ifta, f"IFTA {target.year}-{target.month:02d}")
            df_ifta.insert(0, "Period", f"{target.year}-{target.month:02d}")
            key = f"IFTA_{target.year}_{target.month:02d}"
            ifta_sheets[key] = df_ifta

    log.info("=" * 60)
    log.info("Flattening to DataFrames")
    log.info("=" * 60)

    # Safety events: add clean Event Type / Severity / Driver / Unit columns,
    # since behaviorLabels[] does not flatten into a usable column.
    df_safety = flatten(raw_safety, "SafetyEvents")
    if not df_safety.empty and len(df_safety) == len(raw_safety):
        event_types = [_safety_event_type(r) for r in raw_safety]
        df_safety["Event Type"] = event_types
        df_safety["Severity"] = [_severity_for(t) for t in event_types]
        df_safety["Driver Name"] = [(r.get("driver") or {}).get("name") for r in raw_safety]
        df_safety["Unit"] = [(r.get("vehicle") or {}).get("name") for r in raw_safety]

    # HOS violations: add clean Driver / Violation Type columns.
    df_hosv = flatten(raw_hos_viol, "HOS_Violations")
    if not df_hosv.empty and len(df_hosv) == len(raw_hos_viol):
        df_hosv["Driver Name"] = [(r.get("driver") or {}).get("name") for r in raw_hos_viol]
        df_hosv["Violation Type"] = [_hos_violation_type(r) for r in raw_hos_viol]

    df_dvir_defects = build_dvir_defects(raw_dvirs)
    log.info("  DVIR_Defects: %d rows (exploded from %d DVIRs)",
             len(df_dvir_defects), len(raw_dvirs))

    sheets: dict[str, pd.DataFrame] = {
        "Vehicles":       flatten(raw_vehicles,  "Vehicles"),
        "Drivers":        flatten(raw_drivers,   "Drivers"),
        "VehicleStats":   flatten(raw_stats,     "VehicleStats"),
        "Locations":      flatten(raw_locations, "Locations"),
        "Trips":          flatten(raw_trips,     "Trips"),
        "SafetyEvents":   df_safety,
        "HOS_Logs":       flatten(raw_hos,       "HOS_Logs"),
        "HOS_Violations": df_hosv,
        "DVIRs":          flatten(raw_dvirs,     "DVIRs"),
        "DVIR_Defects":   df_dvir_defects,
        **ifta_sheets,
    }

    output_path = output_dir / "Samsara_Master.xlsx"
    write_samsara_xlsx(sheets, output_path)

    log.info("=" * 60)
    log.info("SUCCESS — output: %s", output_path.resolve())
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
