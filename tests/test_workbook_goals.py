"""Regression tests for read_workbook_goals.

Pins:
  - The brief's goal targets (RPM, deadhead, margin, truck pay/mile) are
    sourced from the Goals & Trends workbook's "JB Formula" sheet at
    runtime, not hardcoded.
  - When the workbook is unreachable, the URL is missing, or a specific
    label isn't found, DEFAULT_GOALS values stand for that field.
  - _scan_label_value walks every row/cell (the JB Formula sheet has an
    irregular label/value layout with multiple label-value pairs per row),
    matches the label case-insensitively, and returns the next cell.

Run:  pytest tests/test_workbook_goals.py
"""
import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import (  # noqa: E402
    DEFAULT_GOALS,
    _scan_label_value,
    read_workbook_goals,
)


def _jb_formula_sheet():
    """Reproduce the JB Formula tab's irregular layout — labels and values
    mixed across columns, several rows blank — so the scanner is exercised
    against realistic data."""
    return pd.DataFrame([
        # Header-ish row
        ["Goal Margin", "Brokerage", "Truck Line", "Total", None, None, "Brokerage", "Trucking"],
        # Row with split values
        [180000, 54000.0, 126000.0, 180000.0, "Per Month", 0.3, 0.7, None],
        [None, None, None, None, None, None, None, None],
        ["Margin Goal", 0.18, 0.3605, None, None, None, None, None],
        [None, None, None, None, None, None, None, None],
        ["Revenue Required", 300000.0, 349500.0, 649500.0, "Per Month", None, None, None],
        [None, None, None, None, None, None, None, None],
        ["Goals", None, None, None, None, None, None, None],
        ["Average RPM Goal", 2.33, None, None, None, None, "Current Truck Pay", 1.49],
        [None, None, None, None, None, None, None, None],
        ["Average Load Mileage", 1100.0, None, None, None, None, None, None],
    ])


def test_scan_label_value_finds_label_first_column():
    df = _jb_formula_sheet()
    assert _scan_label_value(df, "Average RPM Goal") == 2.33
    assert _scan_label_value(df, "Margin Goal") == 0.18


def test_scan_label_value_finds_label_in_middle_column():
    """JB Formula puts 'Current Truck Pay' as a secondary label at column 6;
    the scanner must find it and return the next column's value (1.49)."""
    df = _jb_formula_sheet()
    assert _scan_label_value(df, "Current Truck Pay") == 1.49


def test_scan_label_value_case_insensitive_and_trims():
    df = _jb_formula_sheet()
    assert _scan_label_value(df, "average rpm goal") == 2.33
    assert _scan_label_value(df, "  Margin Goal  ") == 0.18


def test_scan_label_value_returns_none_when_missing():
    df = _jb_formula_sheet()
    assert _scan_label_value(df, "Deadhead Goal") is None


def test_scan_label_value_skips_nan_next_cell():
    """If the cell to the right of the label is empty, return None (don't pick
    up something else from the row)."""
    df = pd.DataFrame([["Margin Goal", None, 0.99]])
    assert _scan_label_value(df, "Margin Goal") is None


def test_read_workbook_goals_no_url_returns_defaults():
    """Without a share URL, the workbook is skipped and defaults are returned
    unchanged — a local dev run without the env var must not crash."""
    g = read_workbook_goals(token=None, share_url=None)
    assert g == DEFAULT_GOALS


def test_read_workbook_goals_empty_token_falls_back():
    g = read_workbook_goals(token="", share_url="anything")
    assert g == DEFAULT_GOALS


def test_read_workbook_goals_applies_overrides(monkeypatch=None):
    """The workbook reader layers JB Formula values on top of DEFAULT_GOALS.
    We monkeypatch download_shared_file + pd.read_excel so the test doesn't
    need network or an actual .xlsx, but still exercises the layering."""
    import src.scorecard_email as se

    jb_df = _jb_formula_sheet()
    fake_sheets = {"JB Formula": jb_df, "Xfreight Trends": pd.DataFrame()}

    def fake_download(_t, _u):
        return b"fake bytes"

    def fake_read_excel(*_a, **_kw):
        return fake_sheets

    orig_download = se.download_shared_file
    orig_read_excel = pd.read_excel
    try:
        se.download_shared_file = fake_download
        pd.read_excel = fake_read_excel
        g = read_workbook_goals(token="t", share_url="u")
    finally:
        se.download_shared_file = orig_download
        pd.read_excel = orig_read_excel

    # JB Formula values applied
    assert g["rpm"] == 2.33                     # was DEFAULT 2.92
    assert g["margin"] == 0.18                  # was DEFAULT 0.18 (same)
    assert g["truck_pay_per_mile"] == 1.49      # was DEFAULT 1.49 (same)
    # Missing in workbook -> DEFAULT stands
    assert g["deadhead"] == DEFAULT_GOALS["deadhead"]


def test_read_workbook_goals_network_error_returns_defaults():
    """If the workbook can't be downloaded for any reason, the brief should
    fall back to defaults rather than crash mid-run."""
    import src.scorecard_email as se

    def boom(_t, _u):
        raise RuntimeError("graph 503 / try again later")

    orig = se.download_shared_file
    try:
        se.download_shared_file = boom
        g = read_workbook_goals(token="t", share_url="u")
    finally:
        se.download_shared_file = orig

    assert g == DEFAULT_GOALS


def test_read_workbook_goals_missing_sheet_returns_defaults():
    """Workbook is reachable but doesn't have a 'JB Formula' tab — defaults."""
    import src.scorecard_email as se

    def fake_download(_t, _u):
        return b"x"

    def fake_read_excel(*_a, **_kw):
        return {"Some Other Tab": pd.DataFrame([[1, 2, 3]])}

    orig_d, orig_r = se.download_shared_file, pd.read_excel
    try:
        se.download_shared_file = fake_download
        pd.read_excel = fake_read_excel
        g = read_workbook_goals(token="t", share_url="u")
    finally:
        se.download_shared_file = orig_d
        pd.read_excel = orig_r

    assert g == DEFAULT_GOALS


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
