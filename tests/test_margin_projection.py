"""Regression tests for compute_margin_projection.

Pins the contract:
    projected_revenue = booked MTD revenue * (days_in_month / day_of_month)
    projected_margin  = projected_revenue * trailing-90 settled margin %

  - 'booked MTD' includes unsettled loads (so the forward estimate captures
    activity the settled-only MTD tile excludes)
  - 'trailing-90 settled' = last 90 days of settled (Driver Rate > 0),
    non-cancelled loads
  - Combined trailing rate is revenue-weighted across X-Trux + X-Linx, NOT
    a simple average of the per-entity rates
  - Cancelled loads excluded from both windows
  - Empty inputs return {} (no crash)

Run:  pytest tests/test_margin_projection.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import compute_margin_projection  # noqa: E402


def _now():
    return pd.Timestamp.now()


def _row(office, pickup, rev, cost, status="Delivered"):
    return {"Office": office, "Scheduled Pickup": pickup,
            "Customer Revenue": rev, "Driver Rate": cost, "Load Status": status}


def _sheets(rows):
    return {"Loads": pd.DataFrame(rows)}


def test_empty_inputs_return_empty_dict():
    assert compute_margin_projection(None) == {}
    assert compute_margin_projection({}) == {}
    assert compute_margin_projection({"Loads": pd.DataFrame()}) == {}


def test_basic_projection_math():
    # The formula is the run-rate blend:
    #   projected_revenue = booked_mtd + daily_run_rate * days_remaining
    #   daily_run_rate    = trailing_90_revenue / 90
    # (The old naive "booked * factor" extrapolation was replaced because it
    # swung too wildly on day 1-2 of the month.)
    now = _now()
    # MTD: 1 settled load/day in the current month at rev=5000, cost=3500 (30% margin)
    rows = [_row("X-Trux", pd.Timestamp(now.year, now.month, d), 5000, 3500)
            for d in range(1, now.day + 1)]
    # 30 prior-month settled loads at the same rate.
    prior_end = pd.Timestamp(now.year, now.month, 1) - pd.Timedelta(days=1)
    for d in range(30):
        rows.append(_row("X-Trux", prior_end - pd.Timedelta(days=d), 5000, 3500))

    p = compute_margin_projection(_sheets(rows))
    xt = p["X-Trux"]

    # Booked MTD and trailing margin % are unaffected by the formula change.
    assert xt["booked_mtd"] == 5000 * now.day
    assert round(xt["trailing_margin_pct"], 4) == 0.30

    # Run-rate formula: compute expected projected_revenue from first principles.
    # Trailing window picks up all settled loads in the last 90 days, which
    # here is 30 prior-month loads + all current-month loads (their timestamps
    # are midnight which is before pd.Timestamp.now()).
    t_rev = (30 + now.day) * 5000
    daily_rr = t_rev / 90
    days_remaining = max(now.days_in_month - now.day, 0)
    expected_proj_rev = 5000 * now.day + daily_rr * days_remaining
    assert abs(xt["projected_revenue"] - expected_proj_rev) < 0.01

    # Projected margin = projected_revenue × trailing margin % (floor is settled
    # margin which is ≤ proj_margin when the month has positive trailing rate).
    assert round(xt["projected_margin"], 2) == round(xt["projected_revenue"] * 0.30, 2)


def test_booked_mtd_includes_unsettled_loads():
    """Loads with Driver Rate = 0 (booked, not yet settled) DO count toward
    booked MTD — that's the point of the basis switch. They do NOT contribute
    to the trailing-90 margin rate (which filters Driver Rate > 0)."""
    now = _now()
    rows = [
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 10_000, 0,    "Booked"),
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 10_000, 7000, "Delivered"),
    ]
    # Trailing-90 history (settled only)
    older = now - pd.Timedelta(days=45)
    for _ in range(20):
        rows.append(_row("X-Trux", older, 10_000, 7000))

    p = compute_margin_projection(_sheets(rows))
    xt = p["X-Trux"]
    assert xt["booked_mtd"] == 20_000                       # both loads counted
    assert round(xt["trailing_margin_pct"], 4) == 0.30      # only settled in rate
    # Unsettled load excluded from trailing despite being recent
    # (it has Driver Rate = 0)


def test_cancelled_loads_excluded():
    now = _now()
    rows = [
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 5000, 3500, "Cancelled"),
        _row("X-Trux", pd.Timestamp(now.year, now.month, 1), 5000, 3500, "Delivered"),
    ]
    older = now - pd.Timedelta(days=45)
    for _ in range(10):
        rows.append(_row("X-Trux", older, 5000, 3500, "Delivered"))

    p = compute_margin_projection(_sheets(rows))
    assert p["X-Trux"]["booked_mtd"] == 5000                # cancelled excluded


def test_xfreight_office_folds_into_xtrux_group():
    """The asset fleet includes both 'X-Trux, Inc' and 'XFreight' offices —
    they belong to the same group per _entity_group, so the projection
    aggregates them."""
    now = _now()
    rows = [
        _row("X-Trux, Inc", pd.Timestamp(now.year, now.month, 1), 5000, 3500),
        _row("XFreight",    pd.Timestamp(now.year, now.month, 1), 3000, 2100),
    ]
    older = now - pd.Timedelta(days=45)
    for _ in range(20):
        rows.append(_row("X-Trux, Inc", older, 5000, 3500))

    p = compute_margin_projection(_sheets(rows))
    assert p["X-Trux"]["booked_mtd"] == 8000                # both offices summed


def test_combined_rate_is_revenue_weighted_not_simple_average():
    """Combined trailing rate = SUM(margin) / SUM(revenue) across entities,
    weighted by each entity's revenue share. A simple average of the per-entity
    rates would understate when one entity dominates the trailing window."""
    now = _now()
    rows = []
    # Tiny MTD just to give booked_mtd a number (negligible effect on trailing %)
    rows.append(_row("X-Trux", pd.Timestamp(now.year, now.month, 1), 1, 0.7))   # 30% margin
    rows.append(_row("X-Linx", pd.Timestamp(now.year, now.month, 1), 1, 0.9))   # 10% margin
    # Trailing-90 history pushed into the prior month so it doesn't pollute MTD.
    # X-Trux gets 2x the revenue of X-Linx, so combined skews toward X-Trux's rate.
    prior_end = pd.Timestamp(now.year, now.month, 1) - pd.Timedelta(days=1)
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
    older = now - pd.Timedelta(days=45)
    for _ in range(5):
        rows.append(_row("X-Trux", older, 5000, 3500))

    p = compute_margin_projection(_sheets(rows))
    xl = p["X-Linx"]
    assert xl["booked_mtd"] is None
    assert xl["trailing_margin_pct"] is None
    assert xl["projected_revenue"] is None
    assert xl["projected_margin"] is None


def test_days_metadata_present():
    """The pill in the tile shows N/M days; make sure those values surface."""
    now = _now()
    rows = [_row("X-Trux", pd.Timestamp(now.year, now.month, 1), 1000, 700)]
    p = compute_margin_projection(_sheets(rows))
    assert p["days_in_month"] == now.days_in_month
    assert p["day_of_month"] == now.day
    assert p["trailing_days"] == 90


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
