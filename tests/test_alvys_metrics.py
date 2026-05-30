"""Regression tests for _alvys_metrics — the Power BI alignment contract.

These pin down the deadhead/RPM denominator choice (Loaded miles, NOT
Loaded + Empty) and the column-name fallbacks. If any of these break, the
Dead Head % MTD / RPM / X-Trux Mileage tiles will drift away from the
Power BI XFreight Report.

The numbers in the May 2026 fixture were taken from the live workbook
diagnostic so the test reproduces the exact Power BI table row:
    Customer Revenue 444,148.98  Loaded 165,717  Empty 10,253
    Dead Head %      = 10,253 / 165,717 = 6.187%
    Rev per Mile     = 444,148.98 / 165,717 = $2.680

Run:  pytest tests/test_alvys_metrics.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import _alvys_metrics  # noqa: E402


# ---------------------------------------------------------------------------
# Power BI row reproduction — May 2026 X-Trux + XFreight
# ---------------------------------------------------------------------------
def _pbi_row(empty_col="Empty Mileage", loaded_col="Loaded Mileage"):
    return pd.DataFrame({
        "Customer Revenue": [444148.98],
        loaded_col: [165717],
        empty_col: [10253],
        "Driver Rate": [303976.18],
    })


def test_deadhead_uses_empty_over_loaded():
    m = _alvys_metrics(_pbi_row())
    assert m["miles"] == 165717
    assert m["empty"] == 10253
    assert round(m["deadhead"], 5) == 0.06187   # Power BI's 6.187%


def test_rpm_uses_revenue_over_loaded():
    m = _alvys_metrics(_pbi_row())
    assert round(m["rpm"], 3) == 2.680           # Power BI's $2.680


def test_margin_is_revenue_minus_driver_rate():
    m = _alvys_metrics(_pbi_row())
    assert round(m["margin"], 2) == 140172.80
    assert round(m["margin_pct"], 4) == 0.3156   # Power BI's 31.56%


# ---------------------------------------------------------------------------
# Column-name preference — the manual workbook uses 'Empty Mileage' /
# 'Loaded Mileage', the pipeline output uses 'Empty Dispatch Mileage' /
# 'Loaded Dispatch Mileage'. Both must work; when both are present, the
# plain names win because that's what Power BI's table sums.
# ---------------------------------------------------------------------------
def test_pipeline_dispatch_column_names_also_work():
    m = _alvys_metrics(_pbi_row(empty_col="Empty Dispatch Mileage",
                                 loaded_col="Loaded Dispatch Mileage"))
    assert m["miles"] == 165717
    assert round(m["deadhead"], 5) == 0.06187


def test_plain_names_preferred_when_both_present():
    # Two columns with the same numbers — confirms _col_any picks the right one
    # without crashing; the value is identical because either is the right basis.
    df = _pbi_row()
    df["Loaded Dispatch Mileage"] = 999_999          # decoy: should NOT win
    df["Empty Dispatch Mileage"] = 999_999           # decoy: should NOT win
    m = _alvys_metrics(df)
    assert m["miles"] == 165717
    assert m["empty"] == 10253
    assert round(m["deadhead"], 5) == 0.06187


# ---------------------------------------------------------------------------
# Loaded-column fallback — when a workbook has only Total + Empty (no
# Loaded), derive Loaded = Total - Empty so the Power BI formula still
# computes against the same denominator.
# ---------------------------------------------------------------------------
def test_loaded_falls_back_to_total_minus_empty():
    df = pd.DataFrame({
        "Customer Revenue": [444148.98],
        "Total Dispatch Mileage": [175970],         # = 165717 loaded + 10253 empty
        "Empty Mileage": [10253],
        "Driver Rate": [303976.18],
    })
    m = _alvys_metrics(df)
    assert m["miles"] == 165717                      # derived
    assert round(m["deadhead"], 5) == 0.06187


# ---------------------------------------------------------------------------
# Edge cases — empty data and missing columns must NOT crash.
# ---------------------------------------------------------------------------
def test_empty_frame_returns_nones():
    m = _alvys_metrics(pd.DataFrame(columns=["Customer Revenue", "Loaded Mileage",
                                              "Empty Mileage", "Driver Rate"]))
    assert m["loads"] == 0
    assert m["revenue"] is None
    assert m["miles"] is None
    assert m["empty"] is None
    assert m["deadhead"] is None
    assert m["rpm"] is None


def test_zero_loaded_returns_none_deadhead_not_divide_by_zero():
    df = pd.DataFrame({
        "Customer Revenue": [1000],
        "Loaded Mileage": [0],
        "Empty Mileage": [50],                       # all-empty trip
        "Driver Rate": [200],
    })
    m = _alvys_metrics(df)
    assert m["deadhead"] is None                     # no denominator
    assert m["rpm"] is None


# ---------------------------------------------------------------------------
# Revenue column fallback — 'Customer Revenue' wins, plain 'Revenue' as
# the back-up so legacy workbooks still produce a number.
# ---------------------------------------------------------------------------
def test_revenue_falls_back_from_customer_revenue_to_revenue():
    df = pd.DataFrame({
        "Revenue": [10000],
        "Loaded Mileage": [1000],
        "Empty Mileage": [100],
        "Driver Rate": [3000],
    })
    m = _alvys_metrics(df)
    assert m["revenue"] == 10000
    assert m["rpm"] == 10.0
    assert round(m["margin_pct"], 2) == 0.70


# ---------------------------------------------------------------------------
# Page 1 Revenue / Mile tile MUST source rpm from _alvys_metrics, not
# recompute it from compute_alvys_entities revenue ÷ fleet miles. The two
# values are computed on different load filters (settled-only vs all
# non-cancelled), so dividing them creates an inflated mid-month rate that
# doesn't match Power BI. Pinning this so a future "simplification" doesn't
# revert it.
# ---------------------------------------------------------------------------
def test_revenue_per_mile_tile_matches_alvys_metrics_rpm():
    from src.scorecard_email import build_page1, rpm as rpm_fmt

    # Simulate the case that surfaced the bug: settled-only revenue is
    # smaller than all-revenue, but they share the same loaded-mile pool.
    # If the tile did _xt_rev / _xt_miles it would be inflated; if it
    # reads _alvys_metrics's rpm directly it stays at the Power BI value.
    target_rpm = 2.680
    alvys = {
        "7d": {},
        "mtd": {},
        "asset": {
            "7d": {"rpm": 2.5, "deadhead": 0.05},
            # _alvys_metrics-equivalent values: all-non-cancelled,
            # Loaded denominator. This is the Power BI basis.
            "mtd": {"rpm": target_rpm, "deadhead": 0.062, "miles": 165_717,
                    "empty": 10_253, "revenue": 444_149},
        },
        "fleet": {"miles": 165_717, "active_trucks": 25, "miles_per_truck": 6628},
    }
    # Entities revenue is SETTLED-ONLY — lower than 444,149 because some
    # MTD loads still haven't been settled. Dividing this by fleet.miles
    # would inflate the ratio above target_rpm.
    ent = {
        "X-Trux": {"revenue": 400_000, "cost": 280_000, "margin": 120_000,
                   "margin_pct": 0.30, "loads": 190, "unsettled": 8},
        "X-Linx": {"revenue": 200_000, "cost": 160_000, "margin": 40_000,
                   "margin_pct": 0.20, "loads": 80, "unsettled": 2},
    }
    html = build_page1(
        alvys, ent, {}, {"total_ar": 1e6, "total31": 2e5},
        ([], []), ([], []),
        {"windows": {}, "coaching": {}, "trend": {}, "detail": {}},
        "Today",
    )

    # The tile must render the target_rpm formatted via the brief's rpm()
    # helper. If the tile reverted to _xt_rev / _xt_miles, it would
    # produce 400_000 / 165_717 ≈ $2.413, NOT $2.680.
    assert rpm_fmt(target_rpm) in html, \
        f"Revenue / mile tile missing the Power BI-aligned value {rpm_fmt(target_rpm)}"
    inflated_or_wrong = rpm_fmt(400_000 / 165_717)
    assert inflated_or_wrong not in html, \
        f"Tile is showing the recomputed _xt_rev / _xt_miles value {inflated_or_wrong} — must use _alvys_metrics rpm instead"


# ---------------------------------------------------------------------------
# Bottom-line blurb MUST source RPM and Dead head % from the X-Trux/XFreight
# MTD asset slice — the same Power BI-aligned basis the tiles use. Older
# code used a 7d-rolling window, which gave readers a number they couldn't
# cross-check against the report. Pinning the MTD basis so it doesn't drift.
# ---------------------------------------------------------------------------
def test_bottom_line_uses_mtd_asset_rpm_and_deadhead():
    from src.scorecard_email import build_page1, rpm as rpm_fmt, pct as pct_fmt

    mtd_rpm, mtd_dh = 2.680, 0.062
    d7_rpm, d7_dh = 2.500, 0.050    # deliberately different so we can tell

    alvys = {
        "7d": {},
        "mtd": {},
        "asset": {
            "7d":  {"rpm": d7_rpm,  "deadhead": d7_dh},
            "mtd": {"rpm": mtd_rpm, "deadhead": mtd_dh, "miles": 165_717,
                    "empty": 10_253, "revenue": 444_149},
        },
        "fleet": {"miles": 165_717, "active_trucks": 25, "miles_per_truck": 6628},
    }
    ent = {
        "X-Trux": {"revenue": 400_000, "cost": 280_000, "margin": 120_000,
                   "margin_pct": 0.30, "loads": 190, "unsettled": 8},
        "X-Linx": {"revenue": 200_000, "cost": 160_000, "margin": 40_000,
                   "margin_pct": 0.20, "loads": 80, "unsettled": 2},
    }
    html = build_page1(
        alvys, ent, {}, {"total_ar": 1e6, "total31": 2e5},
        ([], []), ([], []),
        {"windows": {}, "coaching": {}, "trend": {}, "detail": {}},
        "Today",
    )

    # The MTD values must appear in the bottom-line blurb.
    assert f"RPM {rpm_fmt(mtd_rpm)}" in html, \
        f"Bottom-line RPM should be {rpm_fmt(mtd_rpm)} (MTD asset) not the 7d value"
    assert f"deadhead {pct_fmt(mtd_dh)}" in html, \
        f"Bottom-line deadhead should be {pct_fmt(mtd_dh)} (MTD asset) not the 7d value"

    # And the 7d values must NOT appear in the bottom-line context — if they
    # do, the bottom-line drifted back to the w7a source.
    assert f"RPM {rpm_fmt(d7_rpm)}" not in html, \
        "Bottom-line is showing the 7d RPM — must use MTD asset slice instead"

    # The window label should match the data window.
    assert "MTD" in html and "7d rolling" not in html, \
        "Bottom-line label must say MTD now that the numbers are MTD-basis"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
