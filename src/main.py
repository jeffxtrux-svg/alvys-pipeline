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

    # --- Debug: inventory Driver1.Rates AND Driver1.RatesV2 structures ---
    # The legacy Rates is a list of {RateType, Rate}. The new RatesV2 is a
    # structured object with named rate sub-objects (per Alvys support).
    # We log both so the column_mappings extractor can target the right
    # field names.
    from collections import Counter
    rate_type_counts: Counter = Counter()
    sample_rates_by_type: dict = {}
    ratesv2_key_counts: Counter = Counter()
    ratesv2_samples: dict = {}
    trips_with_v2 = 0
    trips_with_legacy = 0
    for trip in raw_trips:
        d1 = trip.get("Driver1") if isinstance(trip.get("Driver1"), dict) else None
        if not d1:
            continue
        legacy = d1.get("Rates")
        if isinstance(legacy, list) and legacy:
            trips_with_legacy += 1
            for r in legacy:
                if not isinstance(r, dict):
                    continue
                rt = r.get("RateType")
                if rt is not None:
                    rate_type_counts[rt] += 1
                    if rt not in sample_rates_by_type:
                        sample_rates_by_type[rt] = r
        v2 = d1.get("RatesV2")
        if isinstance(v2, dict) and v2:
            trips_with_v2 += 1
            for k, v in v2.items():
                ratesv2_key_counts[k] += 1
                if k not in ratesv2_samples:
                    ratesv2_samples[k] = v
    log.info("=" * 60)
    log.info("Driver1 rates inventory across %d trips:", len(raw_trips))
    log.info("  %d trips have legacy Rates, %d have RatesV2",
             trips_with_legacy, trips_with_v2)
    log.info("=" * 60)
    log.info("Legacy Rates (Driver1.Rates) RateType breakdown:")
    for rt, count in rate_type_counts.most_common():
        sample = sample_rates_by_type.get(rt, {})
        log.info("  %5d trips: RateType=%r  sample=%s",
                 count, rt, json.dumps(sample, default=str)[:200])
    log.info("RatesV2 (Driver1.RatesV2) keys:")
    for k, count in ratesv2_key_counts.most_common():
        sample = ratesv2_samples.get(k, {})
        log.info("  %5d trips have key=%r  sample=%s",
                 count, k, json.dumps(sample, default=str)[:300])
    rate_inventory_path = debug_dir / "driver1_rate_types.json"
    with open(rate_inventory_path, "w") as f:
        json.dump({
            "trips_with_legacy": trips_with_legacy,
            "trips_with_ratesv2": trips_with_v2,
            "legacy_rate_type_counts": dict(rate_type_counts),
            "legacy_rate_type_samples": {k: v for k, v in sample_rates_by_type.items()},
            "ratesv2_key_counts": dict(ratesv2_key_counts),
            "ratesv2_key_samples": {k: v for k, v in ratesv2_samples.items()},
        }, f, indent=2, default=str)
    log.info("Wrote rate inventory → %s", rate_inventory_path)

    # --- Debug: inventory trip.Carrier field structure ---
    # Brokered (X-LINX) trips have a Carrier object whose Rate.Amount we
    # use for "Carrier Rate". X-TRUX trips don't. Log key counts + a sample
    # so we can verify the field path is right.
    carrier_key_counts: Counter = Counter()
    carrier_sample = None
    trips_with_carrier = 0
    for trip in raw_trips:
        c = trip.get("Carrier") if isinstance(trip.get("Carrier"), dict) else None
        if not c:
            continue
        trips_with_carrier += 1
        for k in c.keys():
            carrier_key_counts[k] += 1
        if carrier_sample is None:
            carrier_sample = c
    log.info("=" * 60)
    log.info("trip.Carrier inventory: %d of %d trips have a Carrier object",
             trips_with_carrier, len(raw_trips))
    log.info("=" * 60)
    for k, count in carrier_key_counts.most_common():
        log.info("  %5d trips have Carrier.%s", count, k)
    if carrier_sample is not None:
        carrier_path = debug_dir / "sample_trip_carrier.json"
        with open(carrier_path, "w") as f:
            json.dump(carrier_sample, f, indent=2, default=str)
        log.info("Wrote first Carrier sample → %s", carrier_path)

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
