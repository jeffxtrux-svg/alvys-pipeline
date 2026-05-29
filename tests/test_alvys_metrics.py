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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
