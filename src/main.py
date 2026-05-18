"""
Entry point for the Alvys → Excel pipeline.
Run locally:
    python -m src.main
Reads credentials from .env (local) or environment variables (GitHub Actions).
Writes output to output/Alvys_Master.xlsx.
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from dotenv import load_dotenv
from src.alvys_client import AlvysClient
from src.column_mappings import LOADS_COLUMNS, TRIPS_COLUMNS, FUEL_COLUMNS
from src.output_writer import write_master_xlsx
from src.transformers import transform_records, report_blank_columns

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

def get_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.exit(f"ERROR: required env var {key} not set. Check your .env file.")
    return val

def main() -> int:
    setup_logging()
    load_dotenv()
    log = logging.getLogger("main")

    client_id = get_required("ALVYS_CLIENT_ID")
    client_secret = get_required("ALVYS_CLIENT_SECRET")

    start_date = os.environ.get(
        "ALVYS_START_DATE",
        (date.today() - timedelta(days=425)).strftime("%Y-%m-%d")
    )

    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    debug_dir = output_dir / "_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    log.info("Alvys → Excel pipeline starting")
    log.info("Date range: %s → today", start_date)
    log.info("Output dir: %s", output_dir.resolve())

    client = AlvysClient(client_id, client_secret)

    # --- Build lookup tables (Phase 1.5 enrichment) ---
    from src import lookups
    lookups.build_lookups(client)

    # --- Pull ---
    log.info("=" * 60)
    log.info("Step 1/3: Loads")
    log.info("=" * 60)
    raw_loads = client.fetch_loads(start_date)

    log.info("=" * 60)
    log.info("Step 2/3: Trips")
    log.info("=" * 60)
    raw_trips = client.fetch_trips(start_date)

    log.info("=" * 60)
    log.info("Step 3/3: Fuel")
    log.info("=" * 60)
    raw_fuel = client.fetch_fuel(start_date)

    # --- Build trip↔load join index ---
    lookups.build_join_index(raw_loads, raw_trips)

    # --- Fetch invoices ---
    log.info("=" * 60)
    log.info("Step 4/4: Invoices (for Carrier Invoice Number/Due Date, Customer Due Date)")
    log.info("=" * 60)
    try:
        raw_invoices = client.fetch_invoices(start_date)
        log.info("Total invoices fetched: %d", len(raw_invoices))
        lookups.build_invoice_index(raw_invoices)
    except Exception as e:
        log.warning("Invoice fetch failed: %s — invoice columns will stay blank", e)

    # --- Debug: dump first record from each endpoint ---
    import json
    for name, records in [("loads", raw_loads), ("trips", raw_trips), ("fuel", raw_fuel)]:
        if records:
            sample_path = debug_dir / f"sample_{name}.json"
            with open(sample_path, "w") as f:
                json.dump(records[0], f, indent=2, default=str)
            log.info("Wrote sample %s record → %s", name, sample_path)

    # --- Transform ---
    log.info("=" * 60)
    log.info("Transforming records")
    log.info("=" * 60)
    log.info("Loads:")
    loads_df = transform_records(raw_loads, LOADS_COLUMNS)
    report_blank_columns(loads_df, "Loads")
    log.info("Trips:")
    trips_df = transform_records(raw_trips, TRIPS_COLUMNS)
    report_blank_columns(trips_df, "Trips")
    log.info("Fuel:")
    fuel_df = transform_records(raw_fuel, FUEL_COLUMNS)
    report_blank_columns(fuel_df, "Fuel")

    # --- Write ---
    output_path = output_dir / "Alvys_Master.xlsx"
    write_master_xlsx(loads_df, trips_df, fuel_df, output_path)

    log.info("=" * 60)
    log.info("SUCCESS — output written to %s", output_path.resolve())
    log.info("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
