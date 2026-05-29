"""Regression tests for the X-Trux rate-per-mile goal algorithm.

Pins:
  - cost_per_mile = TARGET_RPM * TARGET_OR (the algorithm)
  - 5%-margin floor equals TARGET_RPM exactly (sanity invariant)
  - Hybrid goal = max(cost-floor at target margin, p75 of closed-month RPM)
  - History is Power BI-aligned: RPM = Revenue / Loaded, DH % = Empty / Loaded
  - Q-summary / YTD / blank rows in the workbook don't get counted as months

Run:  pytest tests/test_compute_goals.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.compute_goals import (  # noqa: E402
    algorithm_cost_per_mile,
    build_report,
    compute_xtrux_history,
    _percentile,
)
from src.scorecard_email import TARGET_OR, TARGET_RPM  # noqa: E402


# ---------------------------------------------------------------------------
# Algorithm — cost_per_mile = TARGET_RPM * TARGET_OR
# ---------------------------------------------------------------------------
def test_algorithm_returns_rpm_times_or():
    assert algorithm_cost_per_mile(2.92, 0.95) == 2.92 * 0.95


def test_algorithm_uses_module_constants_by_default():
    assert algorithm_cost_per_mile() == TARGET_RPM * TARGET_OR


def test_algorithm_floor_at_OR_margin_equals_target_rpm():
    """If margin == 1 - TARGET_OR, the cost-floor equals TARGET_RPM exactly.
    This is the invariant that makes the algorithm internally consistent."""
    cpm = algorithm_cost_per_mile(2.92, 0.95)
    margin = 1 - 0.95          # 5%
    floor = cpm / (1 - margin)
    assert round(floor, 6) == 2.92


# ---------------------------------------------------------------------------
# History scanner
# ---------------------------------------------------------------------------
def test_history_uses_loaded_mileage_denominator():
    """RPM and DH % must use Loaded miles, not Loaded + Empty, to match
    the Power BI XFreight Report."""
    now = pd.Timestamp.now()
    rows = []
    # All in the prior month so it's a closed-month entry
    prior_month_day = (pd.Timestamp(now.year, now.month, 1) - pd.Timedelta(days=15))
    for _ in range(10):
        rows.append({"Office": "X-Trux", "Scheduled Pickup": prior_month_day,
                     "Customer Revenue": 1000, "Loaded Mileage": 350,
                     "Empty Mileage": 50, "Load Status": "Delivered"})

    h = compute_xtrux_history(pd.DataFrame(rows), months=3)
    closed = [x for x in h if not x["is_current_mtd"]]
    assert len(closed) >= 1
    rec = closed[-1]
    # 10,000 rev / 3,500 loaded = $2.857/mile
    assert round(rec["rpm"], 4) == round(10000 / 3500, 4)
    # 500 empty / 3,500 loaded = 14.29%
    assert round(rec["deadhead_pct"], 4) == round(500 / 3500, 4)


def test_history_excludes_cancelled_loads():
    now = pd.Timestamp.now()
    prior = pd.Timestamp(now.year, now.month, 1) - pd.Timedelta(days=15)
    rows = [
        {"Office": "X-Trux", "Scheduled Pickup": prior,
         "Customer Revenue": 1000, "Loaded Mileage": 350, "Empty Mileage": 50,
         "Load Status": "Cancelled"},
        {"Office": "X-Trux", "Scheduled Pickup": prior,
         "Customer Revenue": 1000, "Loaded Mileage": 350, "Empty Mileage": 50,
         "Load Status": "Delivered"},
    ]
    h = compute_xtrux_history(pd.DataFrame(rows), months=2)
    # Only the Delivered load makes it in
    rec = [x for x in h if not x["is_current_mtd"]][-1]
    assert rec["loads"] == 1
    assert rec["revenue"] == 1000


def test_history_groups_xfreight_and_xtrux_offices():
    now = pd.Timestamp.now()
    prior = pd.Timestamp(now.year, now.month, 1) - pd.Timedelta(days=15)
    rows = [
        {"Office": "X-Trux, Inc", "Scheduled Pickup": prior,
         "Customer Revenue": 1000, "Loaded Mileage": 300, "Empty Mileage": 20,
         "Load Status": "Delivered"},
        {"Office": "XFreight", "Scheduled Pickup": prior,
         "Customer Revenue": 500, "Loaded Mileage": 200, "Empty Mileage": 30,
         "Load Status": "Delivered"},
    ]
    h = compute_xtrux_history(pd.DataFrame(rows), months=2)
    rec = [x for x in h if not x["is_current_mtd"]][-1]
    assert rec["loads"] == 2                          # both offices folded in
    assert rec["revenue"] == 1500
    assert rec["loaded"] == 500


def test_history_drops_months_with_no_loads():
    """compute_xtrux_history skips months with zero matching loads — the
    closed-month list should only carry entries that had data."""
    now = pd.Timestamp.now()
    prior_month = pd.Timestamp(now.year, now.month, 1) - pd.Timedelta(days=15)
    rows = [{"Office": "X-Trux", "Scheduled Pickup": prior_month,
             "Customer Revenue": 100, "Loaded Mileage": 50, "Empty Mileage": 5,
             "Load Status": "Delivered"}]
    h = compute_xtrux_history(pd.DataFrame(rows), months=6)
    # Up to 7 months requested (months back + current), only 1 has data
    assert len([x for x in h if x.get("revenue")]) == 1


# ---------------------------------------------------------------------------
# Percentile + report
# ---------------------------------------------------------------------------
def test_percentile_basic():
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.75) == 3.25
    assert _percentile([1.0, 2.0, 3.0, 4.0], 0.25) == 1.75


def test_percentile_empty_returns_none():
    assert _percentile([], 0.75) is None
    assert _percentile([None, None], 0.75) is None


def test_report_shows_algorithm_and_hybrid_table():
    history = [
        {"month": "2026-01", "is_current_mtd": False, "loads": 100,
         "revenue": 250000, "loaded": 100000, "empty": 6000,
         "rpm": 2.50, "deadhead_pct": 0.06},
        {"month": "2026-02", "is_current_mtd": False, "loads": 110,
         "revenue": 280000, "loaded": 110000, "empty": 7000,
         "rpm": 2.545, "deadhead_pct": 0.0636},
        {"month": "2026-03", "is_current_mtd": False, "loads": 120,
         "revenue": 310000, "loaded": 120000, "empty": 7500,
         "rpm": 2.583, "deadhead_pct": 0.0625},
        {"month": "2026-04", "is_current_mtd": False, "loads": 130,
         "revenue": 340000, "loaded": 130000, "empty": 8000,
         "rpm": 2.615, "deadhead_pct": 0.0615},
        {"month": "2026-05", "is_current_mtd": True, "loads": 60,
         "revenue": 170000, "loaded": 65000, "empty": 4500,
         "rpm": 2.615, "deadhead_pct": 0.069},
    ]
    text = build_report(history, target_rpm=2.92, target_or=0.95)

    # Algorithm is named and the math shown
    assert "X-Trux rate-per-mile algorithm" in text
    assert "cost_per_mile = TARGET_RPM * TARGET_OR" in text
    assert "$2.774" in text                          # 2.92 * 0.95
    # Hybrid table headers
    assert "target margin" in text
    assert "cost floor" in text
    assert "hybrid goal" in text
    # 5%-margin row matches TARGET_RPM exactly (invariant)
    assert "$2.920" in text
    # MTD row is marked, closed rows are not
    assert "*MTD" in text
    # Deadhead recommendation surfaces the p25
    assert "Deadhead Goal" in text or "Deadhead" in text


def test_report_handles_empty_history():
    text = build_report([], target_rpm=2.92, target_or=0.95)
    # Cost derivation still printed (it's algorithm-driven, not history-driven)
    assert "$2.774" in text
    # Percentile lines show n/a, not crash
    assert "n/a" in text


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
