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
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.samsara_client import SamsaraClient


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

    now = datetime.datetime.utcnow()
    start_long = now - datetime.timedelta(days=days_back)
    start_hos = now - datetime.timedelta(days=30)

    log.info("Samsara → Excel pipeline starting")
    log.info("Trip/safety/DVIR window : %s → now (%d days)", start_long.date(), days_back)
    log.info("HOS window              : %s → now (30 days)", start_hos.date())
    log.info("Output dir              : %s", output_dir.resolve())

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
    raw_trips = client.fetch_trips(start_long, now)

    log.info("=" * 60)
    log.info("Step 6/9: Safety Events (%d days)", days_back)
    log.info("=" * 60)
    raw_safety = client.fetch_safety_events(start_long, now)

    log.info("=" * 60)
    log.info("Step 7/9: HOS Logs (30 days)")
    log.info("=" * 60)
    raw_hos = client.fetch_hos_logs(start_hos, now)

    log.info("=" * 60)
    log.info("Step 8/9: DVIRs (%d days)", days_back)
    log.info("=" * 60)
    raw_dvirs = client.fetch_dvirs(start_long, now)

    log.info("=" * 60)
    log.info("Step 9/9: IFTA (last 3 months)")
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
    sheets: dict[str, pd.DataFrame] = {
        "Vehicles":     flatten(raw_vehicles,  "Vehicles"),
        "Drivers":      flatten(raw_drivers,   "Drivers"),
        "VehicleStats": flatten(raw_stats,     "VehicleStats"),
        "Locations":    flatten(raw_locations, "Locations"),
        "Trips":        flatten(raw_trips,     "Trips"),
        "SafetyEvents": flatten(raw_safety,    "SafetyEvents"),
        "HOS_Logs":     flatten(raw_hos,       "HOS_Logs"),
        "DVIRs":        flatten(raw_dvirs,     "DVIRs"),
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
