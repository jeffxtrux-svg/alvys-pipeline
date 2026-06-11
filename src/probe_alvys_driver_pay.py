"""
One-shot probe: test all plausible Alvys driver-pay / settlement endpoints
and report what the API accepts plus any new pay fields on live trip records.

Usage:
    python -m src.probe_alvys_driver_pay

Reads ALVYS_CLIENT_ID / ALVYS_CLIENT_SECRET (and optionally ALVYS_START_DATE)
from the environment or .env file.  Writes a JSON report to:
    output/_debug/driver_pay_probe.json

Review the report for:
  - Any endpoint that returns HTTP 200 (new endpoint available)
  - "pay_related_fields_in_sample" — new fields in settlement records
  - "live_trip_schema.pay_related_keys" — new pay fields on trip records
  - "live_trip_schema.Driver1_keys" — new nested keys under Driver1
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("probe_alvys_driver_pay")


def main() -> None:
    client_id = os.environ.get("ALVYS_CLIENT_ID", "")
    client_secret = os.environ.get("ALVYS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        log.error("ALVYS_CLIENT_ID / ALVYS_CLIENT_SECRET not set — check your .env file")
        sys.exit(1)

    start_date = os.environ.get("ALVYS_START_DATE", "2025-01-01")

    from src.alvys_client import AlvysClient
    client = AlvysClient(client_id, client_secret)

    log.info("Running driver-pay endpoint probe (start_date=%s) …", start_date)
    results = client.probe_driver_pay_endpoints(start_date=start_date)

    out_dir = Path("output/_debug")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "driver_pay_probe.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    log.info("Report written → %s", out_path)

    # Print a quick human-readable summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    hits = []
    for label, r in results.items():
        if isinstance(r, dict) and r.get("status") == 200:
            hits.append((label, r))
    if hits:
        print(f"\n✓ {len(hits)} endpoint(s) returned HTTP 200:")
        for label, r in hits:
            print(f"  {label:35s}  {r['method']} {r['path']}")
            pay_fields = r.get("pay_related_fields_in_sample", [])
            if pay_fields:
                print(f"    pay fields: {pay_fields}")
    else:
        print("\nNo new settlement/pay endpoints returned HTTP 200.")

    trip_schema = results.get("live_trip_schema", {})
    if "pay_related_keys" in trip_schema:
        print(f"\nLive trip pay-related fields: {trip_schema['pay_related_keys']}")
    if "Driver1_keys" in trip_schema and trip_schema["Driver1_keys"]:
        print(f"Driver1 nested keys: {trip_schema['Driver1_keys']}")
    if "Carrier_keys" in trip_schema and trip_schema["Carrier_keys"]:
        print(f"Carrier nested keys: {trip_schema['Carrier_keys']}")
    if "nested_pay_shapes" in trip_schema and trip_schema["nested_pay_shapes"]:
        print(f"Nested pay object shapes: {trip_schema['nested_pay_shapes']}")

    print(f"\nFull report: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
