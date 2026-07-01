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

from src.scorecard_email import (  # noqa: E402
    compute_rpm_goal, compute_rpm_goal_trend, _rpm_goal_health,
)

# Recent date inside both the short trailing pay window and the fiscal-YTD window.
def _recent_in_current_month() -> pd.Timestamp:
    """A date that is (a) within the last 10 days (so the rpm-goal pay
    window picks it up) AND (b) guaranteed to be in the current month
    (so compute_rpm_goal_trend's strict month-bucket lands it in the
    current-month slot). Subtracting a flat 3 days breaks on Jun 2-3 etc.
    when the run straddles a month boundary."""
    today = pd.Timestamp.now().normalize()
    # If we're in days 1-3 of the month, use today; otherwise use today-3
    # so we exercise the "near-today but not today" path. Either way,
    # both compute_rpm_goal (10d pay window) and compute_rpm_goal_trend
    # (current-month bucket) see the same loads.
    return today if today.day <= 3 else today - pd.Timedelta(days=3)


_RECENT = _recent_in_current_month()


def _sheets():
    rows = [
        # X-Trux Inc, settled: pay 2000 over 1000 mi, revenue 2600. → included.
        dict(Office="X-Trux, Inc", **{"Customer Revenue": 2600, "Driver Rate": 2000,
             "Total Dispatch Mileage": 1000, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # XFreight (X-Trux group but name lacks "TRUX") → excluded from pay/miles/revenue
        # by the xtrux_only filter in both compute_rpm_goal and compute_rpm_goal_trend.
        dict(Office="XFreight", **{"Customer Revenue": 2300, "Driver Rate": 1620,
             "Total Dispatch Mileage": 900, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # X-Linx brokerage — excluded by _entity_group filter.
        dict(Office="X-Linx, Inc.", **{"Customer Revenue": 800, "Driver Rate": 500,
             "Total Dispatch Mileage": 300, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # Cancelled X-Trux — excluded by Load Status filter.
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


# Only X-Trux Inc loads count; XFreight is in the X-Trux entity group but is
# excluded by the xtrux_only filter (.str.contains("TRUX")) in both
# compute_rpm_goal and compute_rpm_goal_trend.
_PAY = 2000                  # X-Trux Inc only
_MILES = 1000                # X-Trux Inc only
_PAY_PM = _PAY / _MILES      # 2.0
_OVERHEAD = 1000 + 710       # 1710
_OVERHEAD_PM = _OVERHEAD / _MILES   # 1.71
_COST_PM = _PAY_PM + _OVERHEAD_PM  # 3.71


def test_driver_pay_per_mile_excludes_xlinx_and_cancelled():
    g = compute_rpm_goal(_sheets(), _qb_pnl())
    assert g is not None
    assert abs(g["pay_per_mile"] - _PAY_PM) < 1e-9
    assert abs(g["pay_miles"] - _MILES) < 1e-9
    assert abs(g["actual_rpm"] - (2600 / _MILES)) < 1e-9  # X-Trux Inc revenue only


def test_overhead_pools_configured_companies_only_and_abs():
    g = compute_rpm_goal(_sheets(), _qb_pnl())
    assert abs(g["overhead_total"] - _OVERHEAD) < 1e-9          # 1710, Truk-Way excluded
    assert abs(g["overhead_per_mile"] - _OVERHEAD_PM) < 1e-9
    assert sorted(g["overhead_companies"]) == ["X-Linx Inc", "X-Trux, Inc."]


def test_cost_per_mile_and_default_bakes_5pct_profit():
    g = compute_rpm_goal(_sheets(), _qb_pnl())                 # default OR = 0.95 (5% net)
    assert abs(g["cost_per_mile"] - _COST_PM) < 1e-9
    assert abs(g["goal_rpm"] - _COST_PM / 0.95) < 1e-9         # cost + 5% net margin
    assert abs(g["profit_per_mile"] - (_COST_PM / 0.95 - _COST_PM)) < 1e-9
    assert abs(g["target_margin"] - 0.05) < 1e-9


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
    # A fresh X-Trux Inc load whose driver pay hasn't settled yet (Driver Rate 0) has
    # real miles but must NOT drag the pay-per-mile down — it's excluded from the
    # pay read, yet its miles still count toward the YTD overhead denominator.
    # XFreight row is present but excluded by the xtrux_only filter.
    rows = [
        dict(Office="X-Trux, Inc", **{"Customer Revenue": 2600, "Driver Rate": 2000,
             "Total Dispatch Mileage": 1000, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        dict(Office="XFreight", **{"Customer Revenue": 2300, "Driver Rate": 1620,
             "Total Dispatch Mileage": 900, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
        # unsettled X-Trux Inc: pay not entered yet, miles still operated
        dict(Office="X-Trux, Inc", **{"Customer Revenue": 1500, "Driver Rate": 0,
             "Total Dispatch Mileage": 700, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}),
    ]
    g = compute_rpm_goal({"Loads": pd.DataFrame(rows)}, _qb_pnl())
    assert abs(g["pay_per_mile"] - _PAY_PM) < 1e-9             # 2000/1000, unsettled excluded
    assert abs(g["pay_miles"] - _MILES) < 1e-9                 # 1000 mi (settled X-Trux Inc)
    assert abs(g["ytd_miles"] - (_MILES + 700)) < 1e-9        # 1700: settled+unsettled X-Trux Inc
    assert abs(g["overhead_per_mile"] - (_OVERHEAD / (_MILES + 700))) < 1e-9


def test_pay_per_mile_excludes_brokered_loads():
    """Blended driver pay/mi reflects actual X-Trux drivers only. A load brokered
    out to a carrier (tiny placeholder Driver Rate, high Corrected Margin %) has
    big miles but ~no driver pay; including it drags the blend below the contract
    floor. It's excluded from the pay window (rate AND miles), but its truck miles
    still count toward the YTD overhead denominator."""
    rows = [dict(Office="X-Trux, Inc", **{"Customer Revenue": 2600, "Driver Rate": 2000,
                 "Total Dispatch Mileage": 1000, "Scheduled Pickup": _RECENT,
                 "Load Status": "Delivered"}) for _ in range(5)]
    # Brokered: 98% Corrected Margin (4000 rev, 80 driver rate), 1300 mi.
    rows.append(dict(Office="X-Trux, Inc", **{"Customer Revenue": 4000, "Driver Rate": 80,
                "Total Dispatch Mileage": 1300, "Scheduled Pickup": _RECENT,
                "Load Status": "Delivered"}))
    g = compute_rpm_goal({"Loads": pd.DataFrame(rows)}, _qb_pnl())
    assert abs(g["pay_per_mile_raw"] - 2.0) < 1e-9       # 10000/5000, brokered excluded
    assert g["pay_per_mile_floored"] is False            # 2.0 > 1.76 floor, no flooring
    assert abs(g["pay_miles"] - 5000) < 1e-9             # brokered 1300 mi out of the pay leg
    assert g["pay_loads"] == 5
    assert abs(g["ytd_miles"] - 6300) < 1e-9             # but brokered miles count toward YTD


def test_returns_none_without_xtrux_loads():
    only_xlinx = {"Loads": pd.DataFrame([
        dict(Office="X-Linx, Inc.", **{"Customer Revenue": 800, "Driver Rate": 500,
             "Total Dispatch Mileage": 300, "Scheduled Pickup": _RECENT, "Load Status": "Delivered"})])}
    assert compute_rpm_goal(only_xlinx, _qb_pnl()) is None


def test_goal_trend_this_month_matches_point_goal():
    sheets, qb = _sheets(), _qb_pnl()
    g = compute_rpm_goal(sheets, qb)
    t = compute_rpm_goal_trend(sheets, g)
    assert len(t["labels"]) == 6
    assert t["labels"][-1].endswith("*")                       # current month flagged MTD
    # All test loads sit in the current month, so this month's trend cost/goal/actual
    # equal the point-in-time figures from compute_rpm_goal.
    assert abs(t["cost"][-1] - g["cost_per_mile"]) < 1e-9
    assert abs(t["goal"][-1] - g["goal_rpm"]) < 1e-9
    assert abs(t["actual"][-1] - 2600 / _MILES) < 1e-9         # X-Trux Inc revenue/mi (2600/1000)


def test_goal_trend_cost_empty_without_quickbooks():
    sheets = _sheets()
    g = compute_rpm_goal(sheets, qb_pnl=None)                   # no overhead leg
    t = compute_rpm_goal_trend(sheets, g)
    assert t["cost"] == [] and t["goal"] == []                 # cost/goal pending
    assert len(t["actual"]) == 6                               # actual rev/mi still available


def _rich_sheets(rate=1.80, n=6, mi_each=1000):
    """Enough settled X-Trux loads to clear the min-sample threshold in a 10d window."""
    rows = [dict(Office="X-Trux, Inc", **{"Customer Revenue": mi_each * 2.4,
                 "Driver Rate": mi_each * rate, "Total Dispatch Mileage": mi_each,
                 "Scheduled Pickup": _RECENT, "Load Status": "Delivered"}) for _ in range(n)]
    return {"Loads": pd.DataFrame(rows)}


def test_pay_window_widens_when_sample_is_thin():
    # _sheets() has only 1 settled X-Trux Inc load / 1000 mi — below the 5-load / 5000-mi floor,
    # so the window widens to the largest fallback and flags it.
    g = compute_rpm_goal(_sheets(), _qb_pnl())
    assert g["pay_window_fallback"] is True
    assert g["pay_window_used"] == 90                          # widened past 10
    assert abs(g["pay_per_mile"] - _PAY_PM) < 1e-9            # same settled loads, just a wider net
    assert "widened the pay window" in " ".join(_rpm_goal_health(g))


def test_no_fallback_with_a_rich_sample():
    g = compute_rpm_goal(_rich_sheets(), _qb_pnl())
    assert g["pay_window_fallback"] is False
    assert g["pay_window_used"] == g["pay_window_days"]        # no fallback: used == configured
    assert g["pay_loads"] == 6
    assert _rpm_goal_health(g) == []                           # clean: no banner warnings


def test_overhead_allocation_and_xtrux_only():
    g = compute_rpm_goal(_sheets(), _qb_pnl())                 # default alloc 1.0
    assert abs(g["overhead_total"] - _OVERHEAD) < 1e-9
    assert abs(g["overhead_per_mile_xtrux_only"] - (1000 / _MILES)) < 1e-9   # X-Trux opex only
    # allocation factor scales the combined pool
    os.environ["RPM_GOAL_OVERHEAD_ALLOC"] = "0.5"
    try:
        g2 = compute_rpm_goal(_sheets(), _qb_pnl())
        assert abs(g2["overhead_total"] - _OVERHEAD * 0.5) < 1e-9
        assert abs(g2["overhead_alloc"] - 0.5) < 1e-9
    finally:
        del os.environ["RPM_GOAL_OVERHEAD_ALLOC"]


def test_implausible_cost_is_flagged():
    huge = {"X-Trux Inc": {"opex": 30000.0}, "X-Linx Inc": {"opex": 30000.0}}  # ~$31/mi overhead
    g = compute_rpm_goal(_sheets(), huge)
    assert g["cost_plausible"] is False
    assert any("outside the expected" in m for m in _rpm_goal_health(g))


if __name__ == "__main__":
    # These tests verify the live cost-out math; the operational
    # RPM_GOAL_OVERHEAD_PIN constant overrides the live overhead with a
    # hand-set value (0.98 currently) and would break every cost-of-mile
    # assertion below. Unset it for the duration of the run so the tests
    # exercise what they're actually documenting.
    os.environ["RPM_GOAL_OVERHEAD_PIN"] = "0"
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
