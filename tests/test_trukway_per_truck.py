"""Regression tests for the Truk-Way per-truck P&L tab (build_trukway_per_truck).

Locks in the contract for the "Truk-Way Trucks" Google Sheet tab:
  - only loads on the Truk-Way fleet (Load Fleet ~ "truk-way") are counted
  - one row per truck; Settlement Revenue = Driver Rate + Detention + Lumper + Other
  - Fuel Cost is matched per truck on the Alvys fuel-card truck number
  - Rev - Fuel = Settlement Revenue - Fuel Cost; per-mile rates use total miles
  - cancelled loads and rows without a truck are excluded
  - a TOTAL row sums the columns and recomputes the per-mile rates from totals
  - fail-soft: empty / column-less / no-match inputs yield an empty frame

Run directly (only needs pandas):  python tests/test_trukway_per_truck.py
Or via pytest:                     pytest tests/test_trukway_per_truck.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sheets_main import build_trukway_per_truck, trukway_total_expenses  # noqa: E402


def _loads() -> pd.DataFrame:
    """Two Truk-Way trucks (T101 x2 loads, T102 x1), plus noise rows that must
    be excluded: a non-Truk-Way fleet, a cancelled load, and a truck-less load."""
    rows = [
        # T101 — load A
        dict(**{"Load Fleet": "Truk-Way Leasing LLC", "Truck": "T101", "Driver 1": "Joe",
                "Load Status": "Delivered", "Driver Rate": 1000, "Carrier Detention": 50,
                "Carrier Lumper": 0, "Carrier Other Accessorials": 0, "Carrier Advances": 100,
                "Loaded Miles": 800, "Empty Miles": 100, "Customer Revenue": 1500}),
        # T101 — load B
        dict(**{"Load Fleet": "truk-way leasing llc", "Truck": "T101", "Driver 1": "Joe",
                "Load Status": "Completed", "Driver Rate": 600, "Carrier Detention": 0,
                "Carrier Lumper": 25, "Carrier Other Accessorials": 25, "Carrier Advances": 0,
                "Loaded Miles": 400, "Empty Miles": 100, "Customer Revenue": 900}),
        # T102 — single load
        dict(**{"Load Fleet": "Truk-Way Leasing LLC", "Truck": "T102", "Driver 1": "Sam",
                "Load Status": "Delivered", "Driver Rate": 500, "Carrier Detention": 0,
                "Carrier Lumper": 0, "Carrier Other Accessorials": 0, "Carrier Advances": 0,
                "Loaded Miles": 300, "Empty Miles": 0, "Customer Revenue": 700}),
        # excluded: different fleet
        dict(**{"Load Fleet": "X-Trux Inc", "Truck": "T999", "Driver 1": "Al",
                "Load Status": "Delivered", "Driver Rate": 9999, "Carrier Detention": 0,
                "Carrier Lumper": 0, "Carrier Other Accessorials": 0, "Carrier Advances": 0,
                "Loaded Miles": 1, "Empty Miles": 0, "Customer Revenue": 1}),
        # excluded: cancelled Truk-Way load
        dict(**{"Load Fleet": "Truk-Way Leasing LLC", "Truck": "T101", "Driver 1": "Joe",
                "Load Status": "Cancelled", "Driver Rate": 7777, "Carrier Detention": 0,
                "Carrier Lumper": 0, "Carrier Other Accessorials": 0, "Carrier Advances": 0,
                "Loaded Miles": 1, "Empty Miles": 0, "Customer Revenue": 1}),
        # excluded: Truk-Way load with no truck assigned
        dict(**{"Load Fleet": "Truk-Way Leasing LLC", "Truck": "", "Driver 1": "",
                "Load Status": "Delivered", "Driver Rate": 5555, "Carrier Detention": 0,
                "Carrier Lumper": 0, "Carrier Other Accessorials": 0, "Carrier Advances": 0,
                "Loaded Miles": 1, "Empty Miles": 0, "Customer Revenue": 1}),
    ]
    return pd.DataFrame(rows)


def _fuel() -> pd.DataFrame:
    # T101 fuels twice (lowercase to test case-insensitive match); T102 has none.
    return pd.DataFrame([
        dict(Truck="t101", **{"Total Due": 300, "Net Total": 290}),
        dict(Truck="T101", **{"Total Due": 200, "Net Total": 195}),
        dict(Truck="T999", **{"Total Due": 999, "Net Total": 999}),  # not Truk-Way
    ])


def _truck_row(df: pd.DataFrame, truck: str) -> dict:
    return df[df["Truck"] == truck].iloc[0].to_dict()


def test_per_truck_revenue_fuel_and_contribution():
    out = build_trukway_per_truck(_loads(), _fuel())

    # Trucks T101 + T102 + TOTAL = 3 rows; no excluded trucks leaked in.
    assert set(out["Truck"]) == {"T101", "T102", "TOTAL"}

    t101 = _truck_row(out, "T101")
    assert t101["Loads"] == 2
    # Settlement = (1000+50+0+0) + (600+0+25+25) = 1050 + 650 = 1700
    assert abs(t101["Settlement Revenue"] - 1700) < 1e-9
    assert abs(t101["Accessorials"] - 100) < 1e-9          # 50 + 25 + 25
    assert abs(t101["Linehaul Pay"] - 1600) < 1e-9         # 1000 + 600
    assert abs(t101["Fuel Cost"] - 500) < 1e-9             # 300 + 200, case-insensitive
    assert abs(t101["Rev - Fuel"] - 1200) < 1e-9           # 1700 - 500
    assert t101["Total Miles"] == 1400                     # 900 + 500
    assert abs(t101["Rev / Mile"] - round(1700 / 1400, 3)) < 1e-9
    assert t101["Driver"] == "Joe"

    t102 = _truck_row(out, "T102")
    assert t102["Loads"] == 1
    assert abs(t102["Settlement Revenue"] - 500) < 1e-9
    assert abs(t102["Fuel Cost"] - 0) < 1e-9               # no fuel matched
    assert abs(t102["Rev - Fuel"] - 500) < 1e-9


def test_total_row_sums_and_recomputes_rates():
    out = build_trukway_per_truck(_loads(), _fuel())
    total = _truck_row(out, "TOTAL")
    assert total["Loads"] == 3                              # 2 + 1
    assert abs(total["Settlement Revenue"] - 2200) < 1e-9   # 1700 + 500
    assert abs(total["Fuel Cost"] - 500) < 1e-9
    assert abs(total["Rev - Fuel"] - 1700) < 1e-9
    assert total["Total Miles"] == 1700                     # 1400 + 300
    # Rate recomputed from totals, not averaged across truck rows.
    assert abs(total["Rev / Mile"] - round(2200 / 1700, 3)) < 1e-9


def test_excludes_cancelled_and_other_fleets():
    out = build_trukway_per_truck(_loads(), _fuel())
    # The 7777 cancelled load and 9999 X-Trux load must not inflate any total.
    total = _truck_row(out, "TOTAL")
    assert total["Settlement Revenue"] < 7000
    assert "T999" not in set(out["Truck"])


def test_failsoft_inputs():
    assert build_trukway_per_truck(pd.DataFrame(), pd.DataFrame()).empty
    # missing the 'Load Fleet' column
    assert build_trukway_per_truck(pd.DataFrame([{"Truck": "T1"}]), pd.DataFrame()).empty
    # no Truk-Way rows
    no_match = pd.DataFrame([{"Load Fleet": "X-Trux Inc", "Truck": "T1", "Load Status": "Delivered"}])
    assert build_trukway_per_truck(no_match, pd.DataFrame()).empty


def test_handles_missing_fuel_frame():
    out = build_trukway_per_truck(_loads(), pd.DataFrame())
    assert not out.empty
    assert (out["Fuel Cost"] == 0).all()


def test_net_profit_allocates_qb_expenses_by_miles():
    # Fleet miles = 1400 (T101) + 300 (T102) = 1700. QB Total Expenses = 1700.
    out = build_trukway_per_truck(_loads(), _fuel(), qb_total_expenses=1700.0)
    assert "Net Profit" in out.columns and "Allocated QB Cost" in out.columns

    t101 = _truck_row(out, "T101")
    t102 = _truck_row(out, "T102")
    # Allocation is by mile share: 1400/1700 and 300/1700 of $1700 → $1400 / $300.
    assert abs(t101["Allocated QB Cost"] - 1400) < 1e-6
    assert abs(t102["Allocated QB Cost"] - 300) < 1e-6
    # Net Profit = Settlement Revenue − Allocated QB Cost (fuel NOT subtracted again).
    assert abs(t101["Net Profit"] - (1700 - 1400)) < 1e-6
    assert abs(t102["Net Profit"] - (500 - 300)) < 1e-6

    total = _truck_row(out, "TOTAL")
    # Allocated cost sums back to the QB total; net = total settlement − QB total.
    assert abs(total["Allocated QB Cost"] - 1700) < 1e-6
    assert abs(total["Net Profit"] - (2200 - 1700)) < 1e-6
    assert abs(total["Net / Mile"] - round(500 / 1700, 3)) < 1e-6


def test_net_columns_absent_without_qb_expenses():
    out = build_trukway_per_truck(_loads(), _fuel())  # no qb_total_expenses
    assert "Net Profit" not in out.columns
    assert "Allocated QB Cost" not in out.columns


def test_trukway_total_expenses_parsing():
    qb = pd.DataFrame([
        {"Company": "Truk-Way Leasing", "RowLabel": "Fuel", "RowType": "Data", "Col1": "500"},
        {"Company": "Truk-Way Leasing", "RowLabel": "TOTAL Expenses", "RowType": "Summary", "Col1": "1700.00"},
        {"Company": "X-Trux Inc", "RowLabel": "TOTAL Expenses", "RowType": "Summary", "Col1": "9999"},
    ])
    assert abs(trukway_total_expenses(qb) - 1700.0) < 1e-6
    # Other-company total must not leak in.
    assert trukway_total_expenses(qb) != 9999.0
    # Fail-soft on empty / None.
    assert trukway_total_expenses(None) is None
    assert trukway_total_expenses(pd.DataFrame()) is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
