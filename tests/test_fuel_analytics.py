"""Unit tests for src/fuel_analytics.py — fuel cost computed directly from
raw Alvys fuel transactions + trip mileage (no Excel staging).

Run directly:  python tests/test_fuel_analytics.py
Or via pytest: pytest tests/test_fuel_analytics.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.fuel_analytics import (  # noqa: E402
    compute_fuel, compute_fuel_trend, render_fuel_section_html,
    fetch_and_compute_fuel, _norm_driver_name,
)

_NOW = datetime(2026, 6, 29, 18, 0, tzinfo=timezone.utc)   # "today" for all tests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _fuel_rec(driver, truck, day, amount, gallons, total_amount=None, category="Purchase"):
    return {
        "DriverName": driver,
        "TruckNumber": truck,
        "TransactionDate": f"2026-06-{day:02d}T12:00:00Z",
        "FuelTotal": {"Amount": amount},
        "Total": {"Amount": total_amount if total_amount is not None else amount},
        "Quantity": {"Value": gallons},
        "Category": category,
    }


def _trip_rec(driver, truck, day, miles):
    return {
        "Driver1": {"FullName": driver},
        "Truck": {"TruckNum": truck},
        "TotalMileage": {"Distance": {"Value": miles}},
        "UpdatedAt": f"2026-06-{day:02d}T12:00:00Z",
    }


# ---------------------------------------------------------------------------
# compute_fuel — basic math
# ---------------------------------------------------------------------------
def test_returns_none_with_no_fuel_records():
    assert compute_fuel(None, None) is None
    assert compute_fuel([], []) is None


def test_basic_spend_gallons_avg_price():
    fuel = [
        _fuel_rec("Michael Hall", "42187", 10, 500.0, 100.0),
        _fuel_rec("Michael Hall", "42187", 20, 300.0, 60.0),
    ]
    trips = [_trip_rec("Michael Hall", "42187", 15, 1000.0)]
    f = compute_fuel(fuel, trips, now=_NOW)
    assert f["spend_mtd"] == 800.0
    assert f["gallons_mtd"] == 160.0
    assert round(f["avg_price_per_gallon"], 3) == round(800.0 / 160.0, 3)


def test_fuel_cost_per_mile_uses_trip_mileage():
    fuel = [_fuel_rec("Gary Abla", "44202", 10, 400.0, 80.0)]
    trips = [_trip_rec("Gary Abla", "44202", 12, 1000.0)]
    f = compute_fuel(fuel, trips, now=_NOW)
    assert f["fleet_miles_mtd"] == 1000.0
    assert round(f["fuel_cost_per_mile"], 4) == round(400.0 / 1000.0, 4)


def test_no_trip_mileage_leaves_cost_per_mile_none_with_warning():
    fuel = [_fuel_rec("Gary Abla", "44202", 10, 400.0, 80.0)]
    f = compute_fuel(fuel, trip_records=[], now=_NOW)
    assert f["fuel_cost_per_mile"] is None
    assert f["fleet_miles_mtd"] is None
    assert any("mileage" in w.lower() for w in f["warnings"])


# ---------------------------------------------------------------------------
# Month windowing — only this month's records count
# ---------------------------------------------------------------------------
def test_prior_month_fuel_excluded():
    fuel = [
        _fuel_rec("X", "1", 10, 500.0, 100.0),               # this month (June)
    ]
    fuel[0]["TransactionDate"] = "2026-05-28T12:00:00Z"       # actually May
    f = compute_fuel(fuel, [], now=_NOW)
    assert f["spend_mtd"] == 0.0
    assert f["gallons_mtd"] == 0.0


def test_prior_month_trip_mileage_excluded():
    fuel = [_fuel_rec("X", "1", 10, 100.0, 20.0)]
    trips = [_trip_rec("X", "1", 1, 5000.0)]
    trips[0]["UpdatedAt"] = "2026-05-15T12:00:00Z"             # May, not June
    f = compute_fuel(fuel, trips, now=_NOW)
    assert f["fleet_miles_mtd"] is None


def test_missing_transaction_date_skipped_and_warned():
    fuel = [
        {"DriverName": "X", "TruckNumber": "1", "TransactionDate": None,
         "FuelTotal": {"Amount": 999}, "Total": {"Amount": 999}, "Quantity": {"Value": 999}},
        _fuel_rec("Y", "2", 10, 100.0, 20.0),
    ]
    f = compute_fuel(fuel, [], now=_NOW)
    assert f["spend_mtd"] == 100.0   # the bad record's $999 never counted
    assert any("TransactionDate" in w for w in f["warnings"])


# ---------------------------------------------------------------------------
# Amount source: Total.Amount preferred, FuelTotal.Amount fallback
# ---------------------------------------------------------------------------
def test_prefers_total_amount_over_fuel_total():
    fuel = [_fuel_rec("X", "1", 10, amount=100.0, gallons=20.0, total_amount=105.50)]
    f = compute_fuel(fuel, [], now=_NOW)
    assert f["spend_mtd"] == 105.50


def test_falls_back_to_fuel_total_when_total_missing():
    rec = _fuel_rec("X", "1", 10, amount=100.0, gallons=20.0)
    del rec["Total"]
    f = compute_fuel([rec], [], now=_NOW)
    assert f["spend_mtd"] == 100.0


# ---------------------------------------------------------------------------
# National diesel comparison
# ---------------------------------------------------------------------------
def test_price_vs_national_computed_when_provided():
    fuel = [_fuel_rec("X", "1", 10, 500.0, 100.0)]   # $5.00/gal
    f = compute_fuel(fuel, [], now=_NOW, national_diesel_price=4.832)
    assert round(f["price_vs_national"], 3) == round(5.00 - 4.832, 3)


def test_price_vs_national_none_when_not_provided():
    fuel = [_fuel_rec("X", "1", 10, 500.0, 100.0)]
    f = compute_fuel(fuel, [], now=_NOW)
    assert f["price_vs_national"] is None


# ---------------------------------------------------------------------------
# Per-driver rollup + name matching across fuel-vs-trip formatting variance
# ---------------------------------------------------------------------------
def test_driver_name_matches_despite_case_difference():
    fuel = [_fuel_rec("MICHAEL HALL", "42187", 10, 400.0, 80.0)]
    trips = [_trip_rec("Michael Hall", "42187", 12, 800.0)]
    f = compute_fuel(fuel, trips, now=_NOW)
    row = f["by_driver"][0]
    assert row["driver"] == "MICHAEL HALL"
    assert row["miles"] == 800.0
    assert round(row["cost_per_mile"], 4) == round(400.0 / 800.0, 4)


def test_falls_back_to_truck_miles_when_driver_name_unmatched():
    # Fuel transaction has no driver on file, but the truck's trip does.
    fuel = [_fuel_rec(None, "42187", 10, 400.0, 80.0)]
    trips = [_trip_rec("Michael Hall", "42187", 12, 800.0)]
    f = compute_fuel(fuel, trips, now=_NOW)
    row = f["by_driver"][0]
    assert row["miles"] == 800.0


def test_two_drivers_rolled_up_separately():
    fuel = [
        _fuel_rec("Driver A", "1", 10, 100.0, 20.0),
        _fuel_rec("Driver B", "2", 10, 200.0, 40.0),
    ]
    trips = [
        _trip_rec("Driver A", "1", 12, 500.0),
        _trip_rec("Driver B", "2", 12, 500.0),
    ]
    f = compute_fuel(fuel, trips, now=_NOW)
    names = {r["driver"] for r in f["by_driver"]}
    assert names == {"Driver A", "Driver B"}


# ---------------------------------------------------------------------------
# High-cost-driver flagging
# ---------------------------------------------------------------------------
def test_high_cost_driver_flagged_above_threshold():
    fuel = [_fuel_rec("Expensive Driver", "1", 10, 600.0, 100.0)]
    trips = [_trip_rec("Expensive Driver", "1", 12, 1000.0)]   # $0.60/mi > 0.55 default
    f = compute_fuel(fuel, trips, now=_NOW)
    assert len(f["high_cost_drivers"]) == 1
    assert f["high_cost_drivers"][0]["driver"] == "Expensive Driver"


def test_driver_below_threshold_not_flagged():
    fuel = [_fuel_rec("Cheap Driver", "1", 10, 400.0, 100.0)]
    trips = [_trip_rec("Cheap Driver", "1", 12, 1000.0)]        # $0.40/mi
    f = compute_fuel(fuel, trips, now=_NOW)
    assert f["high_cost_drivers"] == []


def test_custom_threshold_respected():
    fuel = [_fuel_rec("Driver", "1", 10, 400.0, 100.0)]
    trips = [_trip_rec("Driver", "1", 12, 1000.0)]               # $0.40/mi
    f = compute_fuel(fuel, trips, now=_NOW, high_cost_threshold=0.35)
    assert len(f["high_cost_drivers"]) == 1


# ---------------------------------------------------------------------------
# compute_fuel_trend
# ---------------------------------------------------------------------------
def test_trend_returns_requested_month_count_with_mtd_asterisk():
    fuel = [_fuel_rec("X", "1", 10, 500.0, 100.0)]
    t = compute_fuel_trend(fuel, [], now=_NOW, months=6)
    assert len(t["labels"]) == 6
    assert t["labels"][-1].endswith("*")
    assert t["labels"][-1].startswith("Jun")


def test_trend_buckets_spend_by_month():
    fuel = [
        _fuel_rec("X", "1", 10, 500.0, 100.0),                       # June
        {**_fuel_rec("X", "1", 10, 300.0, 60.0), "TransactionDate": "2026-05-15T12:00:00Z"},  # May
    ]
    t = compute_fuel_trend(fuel, [], now=_NOW, months=6)
    assert t["spend"][-1] == 500.0    # current month (Jun)
    assert t["spend"][-2] == 300.0    # prior month (May)


def test_trend_outside_window_excluded():
    old = _fuel_rec("X", "1", 10, 999.0, 200.0)
    old["TransactionDate"] = "2025-01-15T12:00:00Z"   # well outside a 3mo window
    t = compute_fuel_trend([old], [], now=_NOW, months=3)
    assert sum(t["spend"]) == 0.0


# ---------------------------------------------------------------------------
# render_fuel_section_html — smoke tests
# ---------------------------------------------------------------------------
def test_render_empty_shows_no_transactions_message():
    html = render_fuel_section_html(None)
    assert "No fuel transactions" in html


def test_render_shows_core_tiles():
    fuel = [_fuel_rec("X", "1", 10, 500.0, 100.0)]
    f = compute_fuel(fuel, [_trip_rec("X", "1", 12, 1000.0)], now=_NOW)
    html = render_fuel_section_html(f)
    assert "Fuel Spend MTD" in html and "$500.00" in html
    assert "Gallons MTD" in html and "100 gal" in html
    assert "Fuel Cost / Mile" in html


def test_render_shows_high_cost_driver_row():
    fuel = [_fuel_rec("Hot Driver", "1", 10, 600.0, 100.0)]
    f = compute_fuel(fuel, [_trip_rec("Hot Driver", "1", 12, 1000.0)], now=_NOW)
    html = render_fuel_section_html(f)
    assert "Hot Driver" in html
    assert "High Fuel Cost Drivers" in html


def test_render_no_high_cost_drivers_message():
    fuel = [_fuel_rec("Cheap Driver", "1", 10, 200.0, 100.0)]
    f = compute_fuel(fuel, [_trip_rec("Cheap Driver", "1", 12, 1000.0)], now=_NOW)
    html = render_fuel_section_html(f)
    assert "No drivers above" in html


def test_render_shows_warnings():
    fuel = [_fuel_rec("X", "1", 10, 200.0, 50.0)]
    f = compute_fuel(fuel, [], now=_NOW)   # no trips -> warning
    html = render_fuel_section_html(f)
    assert "mileage" in html.lower()


# ---------------------------------------------------------------------------
# fetch_and_compute_fuel — live-fetch wrapper, mocked client
# ---------------------------------------------------------------------------
class _FakeAlvysClient:
    def __init__(self, fuel, trips):
        self._fuel = fuel
        self._trips = trips
        self.fuel_calls = []
        self.trip_calls = []

    def fetch_fuel(self, start_date):
        self.fuel_calls.append(start_date)
        return self._fuel

    def fetch_trips(self, start_date):
        self.trip_calls.append(start_date)
        return self._trips


def test_fetch_and_compute_fuel_calls_client_and_computes():
    fuel = [_fuel_rec("X", "1", 10, 500.0, 100.0)]
    trips = [_trip_rec("X", "1", 12, 1000.0)]
    client = _FakeAlvysClient(fuel, trips)
    result = fetch_and_compute_fuel(client, "2026-06-01", now=_NOW)
    assert client.fuel_calls == ["2026-06-01"]
    assert client.trip_calls == ["2026-06-01"]
    assert result["spend_mtd"] == 500.0


# ---------------------------------------------------------------------------
# _norm_driver_name
# ---------------------------------------------------------------------------
def test_norm_driver_name_handles_case_and_whitespace():
    assert _norm_driver_name("  Michael   HALL ") == "michael hall"
    assert _norm_driver_name(None) == ""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
