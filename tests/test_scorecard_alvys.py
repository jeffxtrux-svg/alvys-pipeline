"""Regression tests for the scorecard's Alvys KPIs.

These lock in the contract that matches the Power BI XFreight Report:
  - X-Trux cost = SUM(Loads[Driver Rate])  (settled loads only, Driver Rate > 0)
  - X-Linx cost = SUM(Loads[Driver Rate] + Loads[Carrier Rate])
                  (brokered: carrier payout lands in Carrier Rate, Driver Rate = 0)
  - margin = Customer Revenue - cost
  - margin_pct = Margin / Revenue  (same formula for both entities, matches Power BI)
  - entities are grouped by the Office slicer, not the Invoice As billing column
  - "Loads" counts every non-cancelled load in the window, not just revenue ones

Run directly (only needs pandas):  python tests/test_scorecard_alvys.py
Or via pytest:                     pytest tests/test_scorecard_alvys.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import compute_alvys_entities, _alvys_health, compute_alvys_drivers  # noqa: E402

APR_START = pd.Timestamp(2026, 4, 1)
APR_END = pd.Timestamp(2026, 5, 1)


def _loads():
    """Three April loads exercising the tricky cases."""
    rows = [
        # asset load, fully settled
        dict(Office="XFreight", **{"Invoice As": "XFreight"}, **{"Customer Revenue": 1000,
             "Driver Rate": 300, "Carrier Rate": 0, "Total Dispatch Mileage": 100,
             "Empty Dispatch Mileage": 10, "Scheduled Pickup": pd.Timestamp(2026, 4, 10),
             "Load Status": "Delivered"}),
        # brokered load: Office is X-Linx, invoiced as XFreight. Carrier payout
        # is in Carrier Rate (Driver Rate = 0 — no owner-op on brokered loads).
        dict(Office="X-Linx, Inc.", **{"Invoice As": "XFreight"}, **{"Customer Revenue": 500,
             "Driver Rate": 0, "Carrier Rate": 400, "Total Dispatch Mileage": 80,
             "Empty Dispatch Mileage": 0, "Scheduled Pickup": pd.Timestamp(2026, 4, 12),
             "Load Status": "Delivered"}),
        # zero-revenue but settled (driver paid) — e.g. a positioning / deadhead
        # move with no customer fare. Must still be counted in "Loads" and its cost
        # must roll into the entity's cost/margin.
        dict(Office="X-Trux, Inc", **{"Invoice As": "X-Trux, Inc"}, **{"Customer Revenue": 0,
             "Driver Rate": 200, "Carrier Rate": 0, "Total Dispatch Mileage": 50,
             "Empty Dispatch Mileage": 5, "Scheduled Pickup": pd.Timestamp(2026, 4, 15),
             "Load Status": "Delivered"}),
    ]
    return {"Loads": pd.DataFrame(rows)}


def test_margin_is_revenue_minus_driver_rate():
    e = compute_alvys_entities(_loads(), start=APR_START, end=APR_END)
    xt = e["X-Trux"]
    assert round(xt["cost"]) == 500                  # SUM(Loads[Driver Rate]) for L1 (300) + L3 (200)
    assert round(xt["margin"]) == 500                # 1000 - 500
    assert abs(xt["margin_pct"] - 0.50) < 1e-9       # 500 / 1000  (= Power BI's Margin %)


def test_margin_pct_matches_power_bi_formula():
    """Margin % = Margin / Revenue = (Revenue - Driver Rate) / Revenue,
    same formula for both entities, matching the Power BI XFreight
    Report. Uses distinct numbers so a 50/50 case can't false-pass
    either direction."""
    distinct = {"Loads": pd.DataFrame([
        dict(Office="XFreight", **{"Invoice As": "XFreight"}, **{
            "Customer Revenue": 1000, "Driver Rate": 300, "Carrier Rate": 0,
            "Total Dispatch Mileage": 100, "Empty Dispatch Mileage": 10,
            "Scheduled Pickup": pd.Timestamp(2026, 4, 10), "Load Status": "Delivered"}),
        dict(Office="X-Linx, Inc.", **{"Invoice As": "X-Linx"}, **{
            "Customer Revenue": 1000, "Driver Rate": 825, "Carrier Rate": 0,
            "Total Dispatch Mileage": 80, "Empty Dispatch Mileage": 0,
            "Scheduled Pickup": pd.Timestamp(2026, 4, 12), "Load Status": "Delivered"}),
    ])}
    d = compute_alvys_entities(distinct, start=APR_START, end=APR_END)
    # X-Trux: (1000 - 300) / 1000 = 0.70
    assert abs(d["X-Trux"]["margin_pct"] - 0.70) < 1e-9
    # X-Linx: (1000 - 825) / 1000 = 0.175 — exactly on the brokerage goal
    assert abs(d["X-Linx"]["margin_pct"] - 0.175) < 1e-9


def test_grouping_by_office_not_invoice_as():
    # L2 is invoiced as XFreight but its Office is X-Linx — it must land in X-Linx.
    e = compute_alvys_entities(_loads(), start=APR_START, end=APR_END)
    assert round(e["X-Linx"]["revenue"]) == 500
    assert round(e["X-Trux"]["revenue"]) == 1000     # L2 not folded into X-Trux


def test_carrier_rate_adds_to_xlinx_cost():
    # X-Linx brokered loads have Driver Rate = 0 and Carrier Rate = 400 (the
    # carrier payout). Cost must be Driver Rate + Carrier Rate = 400.
    e = compute_alvys_entities(_loads(), start=APR_START, end=APR_END)
    assert round(e["X-Linx"]["cost"]) == 400         # DR 0 + CR 400
    assert round(e["X-Linx"]["margin"]) == 100       # 500 - 400


def test_counts_all_loads_including_zero_revenue():
    e = compute_alvys_entities(_loads(), start=APR_START, end=APR_END)
    assert e["X-Trux"]["loads"] == 2                 # L1 + zero-revenue L3
    assert e["X-Linx"]["loads"] == 1


def test_unsettled_loads_excluded_from_pnl():
    """Booked-but-not-yet-dispatched loads (Load Status = "Open") must NOT
    contribute to revenue/cost/margin (which would inflate revenue mid-month
    relative to the Power BI report, which excludes Open loads). They surface
    separately via `unsettled`. This is a STATUS rule — note the Open load below
    carries revenue but is still excluded, and a DR=0 non-Open load (e.g.
    "Covered") would still count."""
    sheets = _loads()
    booked_unsettled = pd.DataFrame([dict(
        Office="X-Trux, Inc", **{"Invoice As": "X-Trux, Inc"},
        **{"Customer Revenue": 2665, "Driver Rate": 0, "Carrier Rate": 0,
           "Total Dispatch Mileage": 0, "Empty Dispatch Mileage": 0,
           "Scheduled Pickup": pd.Timestamp(2026, 4, 28), "Load Status": "Open"})])
    sheets["Loads"] = pd.concat([sheets["Loads"], booked_unsettled], ignore_index=True)
    e = compute_alvys_entities(sheets, start=APR_START, end=APR_END)
    xt = e["X-Trux"]
    # Same totals as without the Open load — it's excluded from P&L.
    assert round(xt["revenue"]) == 1000 and round(xt["cost"]) == 500
    assert round(xt["margin"]) == 500
    assert xt["loads"] == 2 and xt["unsettled"] == 1


def test_covered_dr_zero_load_counts():
    """A DR=0 load that is NOT "Open" (e.g. "Covered" — carrier assigned, driver
    rate not yet entered) MUST count toward revenue, matching Power BI. This is
    exactly the case the old "Driver Rate > 0" heuristic got wrong (it dropped
    Covered loads along with Open ones)."""
    sheets = _loads()
    covered = pd.DataFrame([dict(
        Office="X-Trux, Inc", **{"Invoice As": "X-Trux, Inc"},
        **{"Customer Revenue": 1420, "Driver Rate": 0, "Carrier Rate": 0,
           "Total Dispatch Mileage": 0, "Empty Dispatch Mileage": 0,
           "Scheduled Pickup": pd.Timestamp(2026, 4, 20), "Load Status": "Covered"})])
    sheets["Loads"] = pd.concat([sheets["Loads"], covered], ignore_index=True)
    e = compute_alvys_entities(sheets, start=APR_START, end=APR_END)
    xt = e["X-Trux"]
    # Covered revenue is included (1000 + 1420); cost unchanged (DR=0); not unsettled.
    assert round(xt["revenue"]) == 2420 and round(xt["cost"]) == 500
    assert xt["loads"] == 3 and xt["unsettled"] == 0


def test_health_flags_missing_driver_rate():
    sheets = _loads()
    sheets["Loads"] = sheets["Loads"].drop(columns=["Driver Rate"])
    warns = _alvys_health(sheets)
    assert any("Driver Rate" in w for w in warns)


def test_health_flags_empty_driver_rate_column():
    sheets = _loads()
    sheets["Loads"]["Driver Rate"] = 0
    warns = _alvys_health(sheets)
    assert any("Driver Rate" in w for w in warns)


def test_health_clean_when_columns_present():
    assert _alvys_health(_loads()) == []


def test_compute_alvys_drivers_filters_terminated_and_buckets_windows():
    """Drivers sheet → active drivers only, with CDL + DOT medical bucketing."""
    NOW = pd.Timestamp(2026, 6, 2)
    sheets = {"Drivers": pd.DataFrame([
        # Critical: medical expires in 6 days (inside the 14-day window)
        {"Id": "1", "Name": "Bob Trucker", "Type": "Owner Operator", "Status": "Active",
         "LicenseExpiresAt": pd.Timestamp("2027-01-15"),
         "MedicalExpiresAt": pd.Timestamp("2026-06-08"),
         "TerminatedAt": None},
        # 30-day pipeline but not critical
        {"Id": "2", "Name": "Carol Driver", "Type": "Company Driver", "Status": "Active",
         "LicenseExpiresAt": pd.Timestamp("2026-06-20"),   # 18 days
         "MedicalExpiresAt": pd.Timestamp("2026-06-25"),   # 23 days
         "TerminatedAt": None},
        # Terminated — must be excluded
        {"Id": "3", "Name": "Ex Employee", "Type": "Company Driver", "Status": "Inactive",
         "LicenseExpiresAt": pd.Timestamp("2026-06-03"),
         "MedicalExpiresAt": pd.Timestamp("2026-06-03"),
         "TerminatedAt": pd.Timestamp("2025-12-31")},
        # Way outside any window
        {"Id": "4", "Name": "Future Driver", "Type": "Owner Operator", "Status": "Active",
         "LicenseExpiresAt": pd.Timestamp("2028-01-01"),
         "MedicalExpiresAt": pd.Timestamp("2028-01-01"),
         "TerminatedAt": None},
    ])}
    out = compute_alvys_drivers(sheets, now=NOW)
    assert out["monitored"] == 3   # Ex Employee excluded
    assert [d["name"] for d in out["medical_critical_14"]] == ["Bob Trucker"]
    assert {d["name"] for d in out["medical_issues_30"]} == {"Bob Trucker", "Carol Driver"}
    assert [d["name"] for d in out["license_issues_30"]] == ["Carol Driver"]
    assert out["license_critical_14"] == []   # 18 days is outside the <14d window


def test_compute_alvys_drivers_returns_none_when_sheet_missing():
    assert compute_alvys_drivers(None) is None
    assert compute_alvys_drivers({}) is None
    assert compute_alvys_drivers({"Drivers": pd.DataFrame()}) is None


def test_compute_alvys_drivers_handles_tz_aware_expirations():
    """Alvys' /drivers endpoint returns ISO timestamps WITH timezone
    (e.g. '2026-06-08T00:00:00+00:00'). `pd.Timestamp.now()` is tz-naive,
    so any subtraction without stripping tz first raises TypeError.
    This test pins down that the function tolerates either shape."""
    NOW = pd.Timestamp(2026, 6, 2)   # tz-naive
    tz_str = "2026-06-08T00:00:00+00:00"
    sheets = {"Drivers": pd.DataFrame([
        {"Id": "1", "Name": "Tz Driver", "Type": "Owner Operator", "Status": "Active",
         "LicenseExpiresAt": tz_str, "MedicalExpiresAt": tz_str,
         "TerminatedAt": None},
    ])}
    out = compute_alvys_drivers(sheets, now=NOW)
    assert out["monitored"] == 1
    # 6 days from Jun 2 → Jun 8
    assert out["medical_critical_14"][0]["medical_days"] == 6
    assert out["license_critical_14"][0]["license_days"] == 6


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
