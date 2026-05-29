"""Regression tests for the X-Trux rate-per-mile goal (compute_rpm_goal).

Locks in the cost-out contract:
  - cost / mile = driver-pay/mile (X-Trux asset, recent window) + office
    overhead/mile (combined QB Total Expenses / fiscal-YTD X-Trux miles)
  - goal / mile = cost / target operating ratio (OR 1.0 = break-even)
  - X-Linx brokerage loads and cancelled loads are excluded from the per-mile reads
  - office overhead pools the configured companies only (X-Trux + X-Linx, not Truk-Way)

Run directly (only needs pandas):  python tests/test_rpm_goal.py
Or via pytest:                     pytest tests/test_rpm_goal.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import compute_rpm_goal  # noqa: E402

# Recent date inside both the short trailing pay window and the fiscal-YTD window.
_RECENT = (pd.Timestamp.now().normalize() - pd.Timedelta(days=3))


def _sheets():
    rows = [
        # X-Trux asset, settled: pay 2000 over 1000 mi, revenue 2600.
        dict(Office="X-Trux, Inc", **{"Customer Revenue": 2600, "Driver Rate": 2000,
             "Total Dispatch Mileage": 1000, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # X-Trux asset, settled: pay 1620 over 900 mi, revenue 2300.
        dict(Office="XFreight", **{"Customer Revenue": 2300, "Driver Rate": 1620,
             "Total Dispatch Mileage": 900, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # X-Linx brokerage — must NOT count toward X-Trux pay/miles.
        dict(Office="X-Linx, Inc.", **{"Customer Revenue": 800, "Driver Rate": 500,
             "Total Dispatch Mileage": 300, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # Cancelled X-Trux — excluded.
        dict(Office="X-Trux, Inc", **{"Customer Revenue": 9999, "Driver Rate": 9999,
             "Total Dispatch Mileage": 9999, "Scheduled Pickup": _RECENT, "Load Status": "Cancelled"}),
    ]
    return {"Loads": pd.DataFrame(rows)}


# Combined office overhead pool: X-Trux + X-Linx Total Expenses = 1710 (Truk-Way ignored).
# A negative opex sign (QB sometimes exports expenses negative) must be abs()'d.
def _qb_pnl():
    return {
        "X-Trux, Inc.": {"opex": 1000.0},          # punctuation differs from the configured name
        "X-Linx Inc": {"opex": -710.0},            # negative → abs → 710
        "Truk-Way Leasing": {"opex": 50000.0},     # not in the overhead pool
    }


_PAY = 2000 + 1620           # 3620
_MILES = 1000 + 900          # 1900
_PAY_PM = _PAY / _MILES      # ~1.9053
_OVERHEAD = 1000 + 710       # 1710
_OVERHEAD_PM = _OVERHEAD / _MILES
_COST_PM = _PAY_PM + _OVERHEAD_PM


def test_driver_pay_per_mile_excludes_xlinx_and_cancelled():
    g = compute_rpm_goal(_sheets(), _qb_pnl())
    assert g is not None
    assert abs(g["pay_per_mile"] - _PAY_PM) < 1e-9
    assert abs(g["pay_miles"] - _MILES) < 1e-9
    assert abs(g["actual_rpm"] - (4900 / _MILES)) < 1e-9


def test_overhead_pools_configured_companies_only_and_abs():
    g = compute_rpm_goal(_sheets(), _qb_pnl())
    assert abs(g["overhead_total"] - _OVERHEAD) < 1e-9          # 1710, Truk-Way excluded
    assert abs(g["overhead_per_mile"] - _OVERHEAD_PM) < 1e-9
    assert sorted(g["overhead_companies"]) == ["X-Linx Inc", "X-Trux, Inc."]


def test_cost_per_mile_and_default_bakes_8pct_profit():
    g = compute_rpm_goal(_sheets(), _qb_pnl())                 # default OR = 0.92 (8% net)
    assert abs(g["cost_per_mile"] - _COST_PM) < 1e-9
    assert abs(g["goal_rpm"] - _COST_PM / 0.92) < 1e-9         # cost + 8% net margin
    assert abs(g["profit_per_mile"] - (_COST_PM / 0.92 - _COST_PM)) < 1e-9
    assert abs(g["target_margin"] - 0.08) < 1e-9


def test_breakeven_when_or_is_one():
    g = compute_rpm_goal(_sheets(), _qb_pnl(), target_or=1.0)
    assert abs(g["goal_rpm"] - _COST_PM) < 1e-9                 # break-even: goal == cost
    assert abs(g["profit_per_mile"]) < 1e-9
    assert g["target_margin"] == 0.0


def test_profit_layered_via_operating_ratio():
    g = compute_rpm_goal(_sheets(), _qb_pnl(), target_or=0.85)  # 15% net margin
    assert abs(g["goal_rpm"] - _COST_PM / 0.85) < 1e-9
    assert abs(g["profit_per_mile"] - (_COST_PM / 0.85 - _COST_PM)) < 1e-9
    assert abs(g["target_margin"] - 0.15) < 1e-9


def test_no_quickbooks_yields_partial_cost_out():
    g = compute_rpm_goal(_sheets(), qb_pnl=None)
    assert abs(g["pay_per_mile"] - _PAY_PM) < 1e-9             # driver leg still computed
    assert g["overhead_per_mile"] is None                      # no QB → no overhead
    assert g["cost_per_mile"] is None and g["goal_rpm"] is None
    # worksheet sanity-check leg is still available offline
    assert abs(g["worksheet_cost_per_mile"] - (_PAY_PM + g["worksheet_overhead"])) < 1e-9


def test_pay_leg_uses_settled_loads_only():
    # A fresh X-Trux load whose driver pay hasn't settled yet (Driver Rate 0) has
    # real miles but must NOT drag the pay-per-mile down — it's excluded from the
    # pay read, yet its miles still count toward the YTD overhead denominator.
    rows = [
        dict(Office="X-Trux, Inc", **{"Customer Revenue": 2600, "Driver Rate": 2000,
             "Total Dispatch Mileage": 1000, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        dict(Office="XFreight", **{"Customer Revenue": 2300, "Driver Rate": 1620,
             "Total Dispatch Mileage": 900, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # unsettled: just picked up, driver pay not entered yet
        dict(Office="X-Trux, Inc", **{"Customer Revenue": 1500, "Driver Rate": 0,
             "Total Dispatch Mileage": 700, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
    ]
    g = compute_rpm_goal({"Loads": pd.DataFrame(rows)}, _qb_pnl())
    assert abs(g["pay_per_mile"] - _PAY_PM) < 1e-9             # 3620/1900, unsettled excluded
    assert abs(g["pay_miles"] - _MILES) < 1e-9
    assert abs(g["ytd_miles"] - (_MILES + 700)) < 1e-9        # unsettled miles still operated
    assert abs(g["overhead_per_mile"] - (_OVERHEAD / (_MILES + 700))) < 1e-9


def test_returns_none_without_xtrux_loads():
    only_xlinx = {"Loads": pd.DataFrame([
        dict(Office="X-Linx, Inc.", **{"Customer Revenue": 800, "Driver Rate": 500,
             "Total Dispatch Mileage": 300, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"})])}
    assert compute_rpm_goal(only_xlinx, _qb_pnl()) is None


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
