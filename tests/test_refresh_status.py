"""Tests for the brief's final 'Data refresh status' page.

  - compute_refresh_status: per-source shape + fresh/stale logic (OneDrive
    helpers monkeypatched, GH_TOKEN unset so the Actions API leg is skipped —
    no network).
  - build_refresh_status_page: pure renderer shows every source, a Fresh badge,
    a Stale badge, and the run column.

Run directly (needs pandas):  python tests/test_refresh_status.py
Or via pytest:                pytest tests/test_refresh_status.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.scorecard_email as se  # noqa: E402
from src.scorecard_email import build_refresh_status_page, compute_refresh_status  # noqa: E402

_NOW = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)


def test_compute_refresh_status_shape_and_freshness():
    fakes = {
        "QuickBooks/QB_ProfitAndLoss.xlsx":     _NOW - timedelta(hours=20),  # > 8h  -> stale
        "Samsara/Samsara Master.xlsx":          _NOW - timedelta(hours=5),   # <=30h -> fresh
        "SambaSafety/SambaSafety_Master.xlsx":  None,                        # no file
    }
    orig_fm, orig_sm = se.get_file_modified, se.get_shared_modified
    gh_saved = os.environ.pop("GH_TOKEN", None)
    se.get_shared_modified = lambda token, url: _NOW - timedelta(hours=10)    # Alvys 10h -> fresh
    se.get_file_modified = lambda token, upn, path: fakes.get(path)
    try:
        rows = compute_refresh_status("tok", "upn@x", alvys_share="https://share", now=_NOW)
    finally:
        se.get_file_modified, se.get_shared_modified = orig_fm, orig_sm
        if gh_saved is not None:
            os.environ["GH_TOKEN"] = gh_saved

    by = {r["label"]: r for r in rows}
    assert set(by) == {"Alvys", "QuickBooks", "Samsara", "SambaSafety", "Google Sheets KPI"}
    assert by["Alvys"]["fresh"] is True              # 10h <= 30h
    assert by["QuickBooks"]["fresh"] is False        # 20h  > 8h
    assert by["Samsara"]["fresh"] is True            # 5h  <= 30h
    assert by["SambaSafety"]["modified"] is None     # no file -> fresh unknown
    assert by["SambaSafety"]["fresh"] is None
    assert by["Google Sheets KPI"]["max_h"] is None  # run-status only (no OneDrive file)
    # GH_TOKEN unset -> Actions leg skipped, run cells left blank.
    assert by["Alvys"]["run_detail"] == "&mdash;"


def test_build_refresh_status_page_renders_all_sources():
    status = [
        {"label": "Alvys", "modified": _NOW - timedelta(hours=16), "stale_h": 16,
         "fresh": True, "max_h": 30, "run_icon": "OK", "run_detail": "success"},
        {"label": "QuickBooks", "modified": _NOW - timedelta(hours=2), "stale_h": 2,
         "fresh": True, "max_h": 8, "run_icon": "OK", "run_detail": "success"},
        {"label": "SambaSafety", "modified": _NOW - timedelta(hours=80), "stale_h": 80,
         "fresh": False, "max_h": 60, "run_icon": "X", "run_detail": "failure"},
        {"label": "Google Sheets KPI", "modified": None, "stale_h": None,
         "fresh": None, "max_h": None, "run_icon": "OK", "run_detail": "success"},
    ]
    html = build_refresh_status_page(status, "Saturday, June 13, 2026")
    for label in ("Alvys", "QuickBooks", "SambaSafety", "Google Sheets KPI"):
        assert label in html
    assert "Data refresh status" in html
    assert "Fresh" in html                 # fresh badge present
    assert "Stale" in html                 # stale badge present
    assert "run-status only" in html       # Google Sheets KPI badge


def test_build_refresh_status_page_handles_empty():
    # No data at all still renders a valid page (no crash, table placeholder).
    html = build_refresh_status_page(None, "Saturday, June 13, 2026")
    assert "Data refresh status" in html


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
