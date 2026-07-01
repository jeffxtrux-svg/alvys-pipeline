"""Regression tests for compute_margin_projection.

Pins the current contract (working-day run-rate model):
    daily_run_rate    = trailing_revenue_over_{days}_working_days / {days}
    projected_revenue = daily_run_rate * working_days_in_month
    projected_margin  = projected_revenue * trailing_margin_pct,
                        floored at the already-settled MTD margin

  - trailing window = last {days} WORKING days (Mon-Fri excl. major US
    holidays) of settled (load cost > 0), non-cancelled loads. Default 80.
  - 'settled MTD margin' = revenue - cost of this month's settled loads; it is
    the floor (the projection never reads below what's already earned).
  - X-Trux cost = Driver Rate; X-Linx cost = Driver Rate + Carrier Rate.
  - Unsettled loads (cost = 0) are excluded from BOTH the trailing rate and the
    settled-MTD floor.
  - Combined trailing rate is revenue-weighted (SUM margin / SUM revenue), NOT a
    simple average of the per-entity rates.
  - Cancelled loads excluded; empty inputs return {} (no crash).
  - Output keys: per entity + 'combined' → settled_mtd_margin,
    trailing_margin_pct, projected_revenue, projected_margin.
    Top level → working_days_in_month, trailing_days.

Run:  pytest tests/test_margin_projection.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import (compute_margin_projection,  # noqa: E402
                                 _working_days_in_month, _working_days_elapsed)

DAYS = 80  # default trailing working-day window


def _now():
    return pd.Timestamp.now()


def _row(office, pickup, rev, cost, status="Delivered"):
    return {"Office": office, "Scheduled Pickup": pickup,
            "Customer Revenue": rev, "Driver Rate": cost, "Load Status": status}


def _sheets(rows):
    return {"Loads": pd.DataFrame(rows)}


def _prior_month_end(now):
    """Last day of the previous month — firmly outside MTD but inside the
    trailing ~80-working-day (~112 calendar day) window."""
    return pd.Timestamp(now.year, now.month, 1) - pd.Timedelta(days=1)


def test_empty_inputs_return_empty_dict():
    assert compute_margin_projection(None) == {}
    assert compute_margin_projection({}) == {}
    assert compute_margin_projection({"Loads": pd.DataFrame()}) == {}


def test_basic_projection_math():
    # Run-rate model (current contract — MTD revenue pace once the month has
    # enough working days behind it):
    #   if working_days_elapsed >= 5 and settled MTD revenue > 0:
    #       daily_run_rate = settled_mtd_revenue / working_days_elapsed
    #   else (early month):
    #       daily_run_rate = trailing_revenue / DAYS (80 working days)
    #   projected_revenue = daily_run_rate * working_days_in_month
    #   projected_margin  = projected_revenue * MTD margin %,
    #                       floored at settled_mtd_revenue * MTD margin %
    now = _now()
    # 5 settled MTD loads (rev 5000 / cost 3500 = 30% margin) on the 1st.
    rows = [_row("X-Trux", pd.Timestamp(now.year, now.month, 1), 5000, 3500) for _ in range(5)]
    # 50 settled loads at last month's end — inside the trailing window, outside MTD.
    prior_end = _prior_month_end(now)
    rows += [_row("X-Trux", prior_end, 5000, 3500) for _ in range(50)]

    p = compute_margin_projection(_sheets(rows))
    xt = p["X-Trux"]

    # Settled MTD margin = 5 loads * (5000 - 3500); trailing margin % = 30%.
    assert round(xt["settled_mtd_margin"], 2) == 5 * 1500
    assert round(xt["trailing_margin_pct"], 4) == 0.30

    wdim = _working_days_in_month(now.year, now.month)
    wd_elapsed = _working_days_elapsed(now)
    s_rev = 5 * 5000          # settled MTD revenue
    t_rev = 55 * 5000         # trailing-window revenue (all 55 settled loads)
    # MTD pace once >= 5 working days have elapsed; trailing pace before that.
    if wd_elapsed >= 5 and s_rev > 0:
        expected_proj_rev = (s_rev / wd_elapsed) * wdim
    else:
        expected_proj_rev = (t_rev / DAYS) * wdim
    assert abs(xt["projected_revenue"] - expected_proj_rev) < 0.01

    # Projected margin = projected_revenue * MTD margin % (30%), floored at
    # settled_mtd_revenue * MTD margin % (= what this month has already earned).
    applied_pct = 0.30
    expected_pm = max(expected_proj_rev * applied_pct, s_rev * applied_pct)
    assert round(xt["projected_margin"], 2) == round(expected_pm, 2)


def test_unsettled_loads_excluded_from_settled_and_trailing():
    """Loads with no cost (Driver Rate = 0 — booked, not yet settled) are
    excluded from BOTH the settled-MTD floor and the trailing run-rate, which
    each filter to load cost > 0."""
    now = _now()
    rows = [
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 10_000, 0,    "Booked"),    # unsettled
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 10_000, 7000, "Delivered"),  # settled
    ]
    # Settled trailing history at last month's end.
    prior_end = _prior_month_end(now)
    for _ in range(20):
        rows.append(_row("X-Trux", prior_end, 10_000, 7000))

    p = compute_margin_projection(_sheets(rows))
    xt = p["X-Trux"]
    # Only the settled MTD load contributes: 10000 - 7000 = 3000.
    assert round(xt["settled_mtd_margin"], 2) == 3000
    # Trailing rate is settled-only, all at 30%.
    assert round(xt["trailing_margin_pct"], 4) == 0.30


def test_cancelled_loads_excluded():
    now = _now()
    rows = [
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 5000, 3500, "Cancelled"),
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 5000, 3500, "Delivered"),
    ]
    prior_end = _prior_month_end(now)
    for _ in range(10):
        rows.append(_row("X-Trux", prior_end, 5000, 3500, "Delivered"))

    p = compute_margin_projection(_sheets(rows))
    # Cancelled load excluded from the settled MTD floor — only the delivered one counts.
    assert round(p["X-Trux"]["settled_mtd_margin"], 2) == 1500


def test_xfreight_office_folds_into_xtrux_group():
    """The asset fleet includes both 'X-Trux, Inc' and 'XFreight' offices — they
    belong to the same group per _entity_group, so the projection aggregates them."""
    now = _now()
    rows = [
        _row("X-Trux, Inc", pd.Timestamp(now.year, now.month, 1), 5000, 3500),  # margin 1500
        _row("XFreight",    pd.Timestamp(now.year, now.month, 1), 3000, 2100),  # margin 900
    ]
    prior_end = _prior_month_end(now)
    for _ in range(20):
        rows.append(_row("X-Trux, Inc", prior_end, 5000, 3500))

    p = compute_margin_projection(_sheets(rows))
    # Both offices fold into X-Trux: settled MTD margin = 1500 + 900.
    assert round(p["X-Trux"]["settled_mtd_margin"], 2) == 2400


def test_combined_rate_is_revenue_weighted_not_simple_average():
    """Combined trailing rate = SUM(margin) / SUM(revenue) across entities,
    weighted by each entity's revenue share. A simple average of the per-entity
    rates would understate when one entity dominates the trailing window."""
    now = _now()
    rows = []
    # Tiny MTD just to give the entities a presence (negligible effect on trailing %)
    rows.append(_row("X-Trux", pd.Timestamp(now.year, now.month, 1), 1, 0.7))   # 30% margin
    rows.append(_row("X-Linx", pd.Timestamp(now.year, now.month, 1), 1, 0.9))   # 10% margin
    # Trailing-window history pushed into the prior month so it doesn't pollute MTD.
    # X-Trux gets 2x the revenue of X-Linx, so combined skews toward X-Trux's rate.
    prior_end = _prior_month_end(now)
    for _ in range(5):
        rows.append(_row("X-Trux", prior_end, 200_000, 140_000))   # 30% margin
        rows.append(_row("X-Linx", prior_end, 100_000, 90_000))    # 10% margin

    p = compute_margin_projection(_sheets(rows))
    # Per-entity rates land cleanly at 30% and 10%
    assert round(p["X-Trux"]["trailing_margin_pct"], 4) == 0.30
    assert round(p["X-Linx"]["trailing_margin_pct"], 4) == 0.10
    # Combined: total margin / total revenue, dominated by X-Trux's 2x weight.
    # X-Trux: $1M rev / $300K margin.  X-Linx: $500K rev / $50K margin.
    # Combined: $350K / $1.5M = 0.2333... (NOT a simple (30+10)/2 = 20% average)
    assert round(p["combined"]["trailing_margin_pct"], 4) == round(350_000 / 1_500_000, 4)
    assert round(p["combined"]["trailing_margin_pct"], 4) != 0.20


def test_missing_entity_returns_none_values():
    """No X-Linx data anywhere -> X-Linx entry exists with None values, not absent."""
    now = _now()
    rows = [_row("X-Trux", pd.Timestamp(now.year, now.month, 1), 5000, 3500)]
    prior_end = _prior_month_end(now)
    for _ in range(5):
        rows.append(_row("X-Trux", prior_end, 5000, 3500))

    p = compute_margin_projection(_sheets(rows))
    xl = p["X-Linx"]
    assert xl["settled_mtd_margin"] is None
    assert xl["trailing_margin_pct"] is None
    assert xl["projected_revenue"] is None
    assert xl["projected_margin"] is None


def test_days_metadata_present():
    """The pill in the tile shows the working-day basis; make sure those surface."""
    now = _now()
    rows = [_row("X-Trux", pd.Timestamp(now.year, now.month, 1), 1000, 700)]
    p = compute_margin_projection(_sheets(rows))
    assert p["working_days_in_month"] == _working_days_in_month(now.year, now.month)
    assert p["trailing_days"] == DAYS


if __name__ == "__main__":
    # Plain runner (no pytest dependency) so this can run in CI like the other
    # gated test files — CI invokes `python tests/<file>.py`.
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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
