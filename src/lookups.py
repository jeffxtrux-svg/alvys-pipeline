"""
Reference-data lookup tables.

Populated once at script startup via build_lookups(). Column-mapping
callables import this module and read the dicts directly.

  drivers              : Driver.Id   → "First Last"
  trucks               : Truck.Id    → TruckNumber
  trailers             : Trailer.Id  → TrailerNumber
  users                : User.Id     → "First Last"
  offices              : OfficeId    → "X-Trux, Inc"-style name
  subsidiaries         : SubsidiaryId → "X-TRUX INC"-style name
  carriers             : Carrier.Id  → carrier name
  factoring_by_carrier : Carrier.Id  → factoring company name
  truck_fuel_cards     : Truck.Id    → {CardNumber, DeductFromName, DeductFuel}

  loads_by_num         : LoadNumber  → load record
  trips_by_num         : LoadNumber  → trip record (primary leg)
  trips_count_by_load  : LoadNumber  → int (count of trips on this load)
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# ID → friendly name dictionaries
drivers:              dict[str, str]  = {}
trucks:               dict[str, str]  = {}
trailers:             dict[str, str]  = {}
users:                dict[str, str]  = {}
offices:              dict[str, str]  = {}
subsidiaries:         dict[str, str]  = {}
carriers:             dict[str, str]  = {}
factoring_by_carrier: dict[str, str]  = {}
truck_fuel_cards:     dict[str, dict] = {}   # TruckId → {CardNumber, DeductFromName, DeductFuel}

# Raw driver records — kept so the pipeline can write a Drivers sheet to
# Alvys_Master.xlsx (CDL + medical-card expiration for the scorecard's
# driver-compliance page). Populated by build_lookups().
raw_drivers: list[dict] = []

# Raw truck + trailer records — kept so the pipeline can write Equipment
# sheets to Alvys_Master.xlsx (inspection due dates for the scorecard's
# equipment-compliance page). Populated by build_lookups().
raw_trucks:   list[dict] = []
raw_trailers: list[dict] = []

# NEW: Customer + invoice lookups (Round 4)
customers_by_id:           dict[str, dict] = {}   # CustomerId → full customer record
customer_invoice_by_load:  dict[str, dict] = {}   # LoadNumber → customer invoice record
carrier_invoice_by_load:   dict[str, dict] = {}   # LoadNumber → carrier invoice record

# Cross-sheet join indexes
loads_by_num:         dict[str, dict] = {}
trips_by_num:         dict[str, dict] = {}
trips_count_by_load:  dict[str, int]  = {}


# ----------------------------------------------------------------------
# Name extractors — try several common key spellings
# ----------------------------------------------------------------------
def _try_keys(d: dict, keys: list[str]) -> Any:
    for k in keys:
        if k in d and d[k]:
            return d[k]
        # case-insensitive
        for actual_k, v in d.items():
            if isinstance(actual_k, str) and actual_k.lower() == k.lower() and v:
                return v
    return None


def _name_from_driver(d: dict) -> str | None:
    v = _try_keys(d, ["FullName", "Name", "DisplayName"])
    if v:
        return v
    first = _try_keys(d, ["FirstName", "First"])
    last  = _try_keys(d, ["LastName", "Last"])
    if first or last:
        return f"{first or ''} {last or ''}".strip()
    return None


def _name_from_user(u: dict) -> str | None:
    v = _try_keys(u, ["FullName", "DisplayName", "Name"])
    if v:
        return v
    first = _try_keys(u, ["FirstName"])
    last  = _try_keys(u, ["LastName"])
    if first or last:
        return f"{first or ''} {last or ''}".strip()
    return _try_keys(u, ["Email"])


def _number_from_truck(t: dict) -> str | None:
    v = _try_keys(t, ["TruckNum", "TruckNumber", "Number", "Name"])
    return str(v) if v is not None else None


def _number_from_trailer(t: dict) -> str | None:
    v = _try_keys(t, ["TrailerNum", "TrailerNumber", "Number", "Name"])
    return str(v) if v is not None else None


def _name_from_office(o: dict) -> str | None:
    return _try_keys(o, ["Name", "DisplayName", "OfficeName", "CompanyName"])


def _name_from_subsidiary(s: dict) -> str | None:
    return _try_keys(s, ["Name", "DisplayName", "SubsidiaryName"])


def _name_from_carrier(c: dict) -> str | None:
    return _try_keys(c, ["Name", "DisplayName", "CarrierName", "CompanyName"])


def _factoring_from_carrier(c: dict) -> str | None:
    """Extract the factoring company name from a carrier record.
    
    Field structure observed in the wild: FactoringCompany is itself a dict
    of {Id, Name}, not a string. Need to dig into .Name.
    """
    direct = _try_keys(c, ["FactoringCompany", "FactoringCompanyName"])
    if direct:
        if isinstance(direct, dict):
            return _try_keys(direct, ["Name", "DisplayName", "CompanyName"])
        return direct
    nested = _try_keys(c, ["Factoring"])
    if isinstance(nested, dict):
        return _try_keys(nested, ["Name", "DisplayName", "CompanyName"])
    return None


# ----------------------------------------------------------------------
# Build lookups
# ----------------------------------------------------------------------
def build_lookups(client) -> None:
    """
    Pull reference data and populate the dicts. Each endpoint wrapped in
    try/except so one failure doesn't kill the whole run.
    """
    log.info("=" * 60)
    log.info("Building lookup tables")
    log.info("=" * 60)

    import json
    debug_dir = os.environ.get("DEBUG_DIR", "output/_debug")
    os.makedirs(debug_dir, exist_ok=True)

    # ---- Core lookups (existing) ----
    core = [
        ("drivers",  client.fetch_drivers,  drivers,  "Id", _name_from_driver),
        ("trucks",   client.fetch_trucks,   trucks,   "Id", _number_from_truck),
        ("trailers", client.fetch_trailers, trailers, "Id", _number_from_trailer),
        ("users",    client.fetch_users,    users,    "Id", _name_from_user),
    ]
    global raw_drivers, raw_trucks, raw_trailers
    _local_raw_trucks: list[dict] = []
    for label, fetch_fn, target, key_field, name_fn in core:
        try:
            records = fetch_fn()
            if records:
                sample_path = os.path.join(debug_dir, f"sample_{label}.json")
                with open(sample_path, "w") as f:
                    json.dump(records[0], f, indent=2, default=str)
                first_keys = list(records[0].keys()) if isinstance(records[0], dict) else []
                log.info("  %-9s: keys in first record = %s",
                         label, first_keys[:15])

            for r in records:
                rid = _try_keys(r, [key_field])
                if rid:
                    target[rid] = name_fn(r)

            # Save trucks for fuel-card extraction and the Equipment sheet.
            if label == "trucks":
                _local_raw_trucks = list(records or [])
                raw_trucks = _local_raw_trucks
            # Save trailers for the Equipment sheet.
            if label == "trailers":
                raw_trailers = list(records or [])
            # Save drivers for the Drivers sheet (CDL + medical-card tracking)
            if label == "drivers":
                raw_drivers = list(records or [])

            sample_pairs = list(target.items())[:3]
            log.info("  %-9s: %d records  | first keys: %s",
                     label, len(target),
                     [f"{k} → {v}" for k, v in sample_pairs])
        except Exception as e:
            log.warning("  %-9s: FAILED (%s) — those columns will stay blank", label, e)

    # ---- Truck fuel cards (extracted from trucks, no extra API call) ----
    log.info("Building truck_fuel_cards lookup from %d trucks", len(_local_raw_trucks))
    for truck in _local_raw_trucks:
        if not isinstance(truck, dict):
            continue
        truck_id = _try_keys(truck, ["Id"])
        fuel_cards = _try_keys(truck, ["FuelCards"])
        if not truck_id or not isinstance(fuel_cards, list) or not fuel_cards:
            continue
        # Use the first card as the canonical
        card = fuel_cards[0]
        if not isinstance(card, dict):
            continue
        truck_fuel_cards[truck_id] = {
            "CardNumber": _try_keys(card, ["CardNumber"]),
            "DeductFromName": _try_keys(card, ["DeductFromName"]),
            "DeductFuel": _try_keys(card, ["DeductFuel"]),
            "Provider": _try_keys(card, ["Provider"]),
        }
    log.info("  truck_fuel_cards: %d trucks with cards", len(truck_fuel_cards))

    # ---- Optional reference data (may 404 — that's OK) ----
    # Offices
    try:
        recs = client.fetch_offices()
        if recs:
            sample_path = os.path.join(debug_dir, "sample_offices.json")
            with open(sample_path, "w") as f:
                json.dump(recs[0], f, indent=2, default=str)
            log.info("  offices: keys in first record = %s",
                     list(recs[0].keys())[:15] if isinstance(recs[0], dict) else [])
            for r in recs:
                rid = _try_keys(r, ["Id"])
                if rid:
                    offices[rid] = _name_from_office(r)
        log.info("  offices  : %d records", len(offices))
    except Exception as e:
        log.warning("  offices  : FAILED (%s)", e)

    # Subsidiaries
    try:
        recs = client.fetch_subsidiaries()
        if recs:
            sample_path = os.path.join(debug_dir, "sample_subsidiaries.json")
            with open(sample_path, "w") as f:
                json.dump(recs[0], f, indent=2, default=str)
            log.info("  subs: keys in first record = %s",
                     list(recs[0].keys())[:15] if isinstance(recs[0], dict) else [])
            for r in recs:
                rid = _try_keys(r, ["Id"])
                if rid:
                    subsidiaries[rid] = _name_from_subsidiary(r)
        log.info("  subsidiaries: %d records", len(subsidiaries))
    except Exception as e:
        log.warning("  subsidiaries: FAILED (%s)", e)

    # Carriers
    try:
        recs = client.fetch_carriers()
        if recs:
            sample_path = os.path.join(debug_dir, "sample_carriers.json")
            with open(sample_path, "w") as f:
                json.dump(recs[0], f, indent=2, default=str)
            log.info("  carriers: keys in first record = %s",
                     list(recs[0].keys())[:15] if isinstance(recs[0], dict) else [])
            for r in recs:
                rid = _try_keys(r, ["Id"])
                if rid:
                    carriers[rid] = _name_from_carrier(r)
                    factoring = _factoring_from_carrier(r)
                    if factoring:
                        factoring_by_carrier[rid] = factoring
        log.info("  carriers : %d records (%d with factoring)",
                 len(carriers), len(factoring_by_carrier))
    except Exception as e:
        log.warning("  carriers : FAILED (%s)", e)

    # Customers — for AM/SM/CSR + invoicing method
    try:
        recs = client.fetch_customers()
        if recs:
            sample_path = os.path.join(debug_dir, "sample_customers.json")
            with open(sample_path, "w") as f:
                json.dump(recs[0], f, indent=2, default=str)
            log.info("  customers: keys in first record = %s",
                     list(recs[0].keys())[:20] if isinstance(recs[0], dict) else [])
            for r in recs:
                rid = _try_keys(r, ["Id"])
                if rid:
                    customers_by_id[rid] = r  # keep full record for multi-field lookups
        log.info("  customers: %d records", len(customers_by_id))
    except Exception as e:
        log.warning("  customers: FAILED (%s)", e)

    # ---- Apply user-provided overrides from ALVYS_OFFICE_MAPPINGS env var ----
    # Format: JSON dict, e.g. {"8087bd04-...": "X-Trux, Inc", ...}
    env_offices = os.environ.get("ALVYS_OFFICE_MAPPINGS")
    if env_offices:
        try:
            user_map = json.loads(env_offices)
            offices.update(user_map)
            log.info("  applied %d office overrides from ALVYS_OFFICE_MAPPINGS", len(user_map))
        except Exception as e:
            log.warning("  ALVYS_OFFICE_MAPPINGS not valid JSON: %s", e)


def build_join_index(raw_loads: list[dict], raw_trips: list[dict]) -> None:
    """Build LoadNumber-keyed indexes for the trip↔load join."""
    for load in raw_loads:
        ln = load.get("LoadNumber")
        if ln:
            loads_by_num[ln] = load

    # Count trips per load + pick the trip with most data as the primary
    for trip in raw_trips:
        ln = trip.get("LoadNumber")
        if not ln:
            continue
        trips_count_by_load[ln] = trips_count_by_load.get(ln, 0) + 1
        existing = trips_by_num.get(ln)
        if existing is None or len(str(trip)) > len(str(existing)):
            trips_by_num[ln] = trip

    log.info("Join index: %d loads, %d trips_by_load (avg trips/load: %.2f)",
             len(loads_by_num), len(trips_by_num),
             (sum(trips_count_by_load.values()) / max(1, len(trips_count_by_load))))


def build_invoice_index(raw_invoices: list[dict]) -> None:
    """
    Bucket invoices by LoadNumber into customer_invoice_by_load and
    carrier_invoice_by_load lookups.

    Heuristic: An invoice is a "Carrier" invoice if it has a CarrierInvoiceNumber
    or CarrierId or InvoiceType=='Carrier'. Otherwise it's a customer invoice.
    """
    if not raw_invoices:
        log.info("No invoices to index")
        return

    # Dump first record for debugging
    import os, json as _json
    debug_dir = os.environ.get("DEBUG_DIR", "output/_debug")
    os.makedirs(debug_dir, exist_ok=True)
    with open(os.path.join(debug_dir, "sample_invoice.json"), "w") as f:
        _json.dump(raw_invoices[0], f, indent=2, default=str)
    log.info("Invoice keys in first record: %s",
             list(raw_invoices[0].keys())[:20] if isinstance(raw_invoices[0], dict) else [])

    customer_count = 0
    carrier_count = 0
    for inv in raw_invoices:
        if not isinstance(inv, dict):
            continue
        # Try several common load-key fields
        load_num = _try_keys(inv, ["LoadNumber", "Load.LoadNumber", "LoadId"])
        if not load_num:
            # might be nested under Load
            load_obj = _try_keys(inv, ["Load"])
            if isinstance(load_obj, dict):
                load_num = _try_keys(load_obj, ["LoadNumber", "Number", "Id"])
        if not load_num:
            continue
        load_num = str(load_num)

        # Determine invoice type
        inv_type = _try_keys(inv, ["InvoiceType", "Type"])
        has_carrier_number = bool(_try_keys(inv, [
            "CarrierInvoiceNumber", "CarrierInvoiceNum"
        ]))
        has_carrier_id = bool(_try_keys(inv, ["CarrierId", "Carrier.Id"]))
        is_carrier = (
            (inv_type and "carrier" in str(inv_type).lower())
            or has_carrier_number
            or has_carrier_id
        )

        if is_carrier:
            # Keep the most populated record if duplicates
            existing = carrier_invoice_by_load.get(load_num)
            if existing is None or len(str(inv)) > len(str(existing)):
                carrier_invoice_by_load[load_num] = inv
                carrier_count += 1
        else:
            existing = customer_invoice_by_load.get(load_num)
            if existing is None or len(str(inv)) > len(str(existing)):
                customer_invoice_by_load[load_num] = inv
                customer_count += 1

    log.info("Invoice index: %d customer invoices, %d carrier invoices",
             len(customer_invoice_by_load), len(carrier_invoice_by_load))


# ----------------------------------------------------------------------
# Helpers for column_mappings callables
# ----------------------------------------------------------------------
def _get_nested(obj: Any, path: str) -> Any:
    if obj is None or not path:
        return None
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        if part == "first" and isinstance(current, list):
            current = current[0] if current else None
            continue
        if part == "last" and isinstance(current, list):
            current = current[-1] if current else None
            continue
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                key_lower = part.lower()
                found = None
                for k, v in current.items():
                    if isinstance(k, str) and k.lower() == key_lower:
                        found = v
                        break
                current = found
        else:
            return None
    return current


def trip_for_load(load_record: dict) -> dict | None:
    return trips_by_num.get(load_record.get("LoadNumber"))


def load_for_trip(trip_record: dict) -> dict | None:
    return loads_by_num.get(trip_record.get("LoadNumber"))


def trips_count(load_record: dict) -> int:
    return trips_count_by_load.get(load_record.get("LoadNumber"), 0)


# ---- Customer + invoice accessors ----
def customer_for_load(load_record: dict) -> dict | None:
    """Return the customer record joined to this load via CustomerId."""
    cid = load_record.get("CustomerId")
    return customers_by_id.get(cid) if cid else None


def customer_invoice_for_load(load_record: dict) -> dict | None:
    return customer_invoice_by_load.get(load_record.get("LoadNumber"))


def carrier_invoice_for_load(load_record: dict) -> dict | None:
    return carrier_invoice_by_load.get(load_record.get("LoadNumber"))


# ---- Rates processing ----
def _rate_for_type(rates: list, rate_type: str) -> float | None:
    if not isinstance(rates, list):
        return None
    for r in rates:
        if isinstance(r, dict) and r.get("RateType") == rate_type:
            return r.get("Rate")
    return None


def driver1_rate(rate_type: str):
    def fn(trip_record: dict) -> Any:
        rates = _get_nested(trip_record, "Driver1.Rates")
        return _rate_for_type(rates, rate_type)
    return fn


def driver1_rate_via_trip(rate_type: str):
    def fn(load_record: dict) -> Any:
        trip = trip_for_load(load_record)
        if not trip:
            return None
        rates = _get_nested(trip, "Driver1.Rates")
        return _rate_for_type(rates, rate_type)
    return fn
