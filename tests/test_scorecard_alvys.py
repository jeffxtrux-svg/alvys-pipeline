"""Regression tests for the scorecard's Alvys KPIs.

These lock in the contract that matches the Power BI XFreight Report:
  - cost / "Driver Rate" = SUM(Loads[Driver Rate])  (Carrier Rate is NOT added)
  - margin = Customer Revenue - Driver Rate
  - margin_pct = Margin / Revenue = (Revenue - Driver Rate) / Revenue
                                     (same formula for both entities,
                                      matches Power BI)
  - entities are grouped by the Office slicer, not the Invoice As billing column
  - "Loads" counts every non-cancelled load in the window, not just revenue ones

Run directly (only needs pandas):  python tests/test_scorecard_alvys.py
Or via pytest:                     pytest tests/test_scorecard_alvys.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import compute_alvys_entities, _alvys_health  # noqa: E402

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
        # brokered load: Office is X-Linx but it is invoiced under XFreight, and it
        # carries a Carrier Rate that must be ignored (payout lives in Driver Rate).
        dict(Office="X-Linx, Inc.", **{"Invoice As": "XFreight"}, **{"Customer Revenue": 500,
             "Driver Rate": 400, "Carrier Rate": 999, "Total Dispatch Mileage": 80,
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


def test_carrier_rate_is_not_added():
    # L2 has Carrier Rate 999; cost must be the Driver Rate (400), not 400+999.
    e = compute_alvys_entities(_loads(), start=APR_START, end=APR_END)
    assert round(e["X-Linx"]["cost"]) == 400
    assert round(e["X-Linx"]["margin"]) == 100       # 500 - 400


def test_counts_all_loads_including_zero_revenue():
    e = compute_alvys_entities(_loads(), start=APR_START, end=APR_END)
    assert e["X-Trux"]["loads"] == 2                 # L1 + zero-revenue L3
    assert e["X-Linx"]["loads"] == 1


def test_unsettled_loads_excluded_from_pnl():
    """Booked-but-not-yet-dispatched loads (revenue > 0, Driver Rate = 0) must NOT
    contribute to revenue/cost/margin (which would inflate margin % mid-month
    relative to the Power BI report). They surface separately via `unsettled`."""
    sheets = _loads()
    booked_unsettled = pd.DataFrame([dict(
        Office="X-Trux, Inc", **{"Invoice As": "X-Trux, Inc"},
        **{"Customer Revenue": 2665, "Driver Rate": 0, "Carrier Rate": 0,
           "Total Dispatch Mileage": 0, "Empty Dispatch Mileage": 0,
           "Scheduled Pickup": pd.Timestamp(2026, 4, 28), "Load Status": "Delivered"})])
    sheets["Loads"] = pd.concat([sheets["Loads"], booked_unsettled], ignore_index=True)
    e = compute_alvys_entities(sheets, start=APR_START, end=APR_END)
    xt = e["X-Trux"]
    # Same totals as without the unsettled load — it's excluded.
    assert round(xt["revenue"]) == 1000 and round(xt["cost"]) == 500
    assert round(xt["margin"]) == 500
    assert xt["loads"] == 2 and xt["unsettled"] == 1


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
