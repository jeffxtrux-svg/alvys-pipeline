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
from src.scorecard_email import (build_refresh_status_page, compute_refresh_status,  # noqa: E402
                                 _suggest_action)

_NOW = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)


def test_compute_refresh_status_shape_and_freshness():
    fakes = {
        "QuickBooks/QB_ProfitAndLoss.xlsx":     _NOW - timedelta(hours=20),  # > 8h  -> stale
        "Samsara/Samsara Master.xlsx":          _NOW - timedelta(hours=5),   # <=30h -> fresh
        "SambaSafety/SambaSafety_Master.xlsx":  None,                        # no file
        # Power BI falls back to the Desktop .pbix file time (no Service IDs set).
        "XFreight - Claude Working Files/02 - Power BI/XFreight Report.pbix": _NOW - timedelta(hours=4),
    }
    orig_fm, orig_sm = se.get_file_modified, se.get_shared_modified
    saved = {k: os.environ.pop(k, None) for k in ("GH_TOKEN", "PBI_WORKSPACE_ID", "PBI_DATASET_ID")}
    se.get_shared_modified = lambda token, url: _NOW - timedelta(hours=10)    # Alvys 10h -> fresh
    se.get_file_modified = lambda token, upn, path: fakes.get(path)
    try:
        rows = compute_refresh_status("tok", "upn@x", alvys_share="https://share",
                                      wiki_dir="/nonexistent-wiki", now=_NOW)
    finally:
        se.get_file_modified, se.get_shared_modified = orig_fm, orig_sm
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    by = {r["label"]: r for r in rows}
    assert set(by) == {"Alvys Master", "QuickBooks", "Samsara", "SambaSafety", "Google Sheets KPI",
                       "Daily MTD Upload", "Knowledge Base Wiki", "Upload Health Check",
                       "Scorecard Health Check", "Power BI XFreight Report"}
    # Feed/source-type labels.
    assert by["Alvys Master"]["feed"] == "Manual upload"
    assert by["QuickBooks"]["feed"] == "API"
    assert by["Samsara"]["feed"] == "API"
    assert by["Google Sheets KPI"]["feed"] == "Google API"
    assert by["Daily MTD Upload"]["feed"] == "Excel upload"
    assert by["SambaSafety"]["feed"] == "CSV combine"
    assert by["Alvys Master"]["fresh"] is True              # 10h <= 30h
    assert by["QuickBooks"]["fresh"] is False        # 20h  > 8h
    assert by["Samsara"]["fresh"] is True            # 5h  <= 30h
    assert by["SambaSafety"]["modified"] is None and by["SambaSafety"]["fresh"] is None
    # Power BI: no Service IDs -> falls back to the Desktop .pbix file time.
    assert by["Power BI XFreight Report"]["feed"] == "Power BI Desktop"
    assert by["Power BI XFreight Report"]["fresh"] is True            # .pbix 4h old <= 30h
    assert _suggest_action(by["Power BI XFreight Report"]) is None    # healthy -> no action
    # Knowledge base: nonexistent dir -> no size; GH_TOKEN unset -> no run time.
    assert by["Knowledge Base Wiki"]["measure"] is None
    # GH_TOKEN unset -> Actions leg skipped, run cells left blank.
    assert by["Alvys Master"]["run_detail"] == "&mdash;"
    # New fields used by the suggested-action column.
    assert by["Alvys Master"]["kind"] == "share"
    assert by["QuickBooks"]["run_ok"] is None        # no GH_TOKEN -> unknown
    # Suggested actions derive from the row state.
    assert "stale" in _suggest_action(by["QuickBooks"]).lower()      # QB is stale
    assert "file not found" in _suggest_action(by["SambaSafety"])    # no file
    assert by["SambaSafety"]["feed"] == "CSV combine"               # CSV source, not API


def test_suggest_action_cases():
    assert _suggest_action({"kind": "file", "modified": "x", "fresh": False,
                            "run_ok": True}) .startswith("Data is stale")
    assert _suggest_action({"kind": "file", "modified": "x", "fresh": True,
                            "run_ok": False}).startswith("Refresh failed")
    assert _suggest_action({"kind": "file", "modified": None, "fresh": None,
                            "run_ok": True}).startswith("Source file not found")
    assert _suggest_action({"kind": "run", "modified": None, "run_ok": None,
                            "run_detail": "&mdash;", "wf": "x.yml"}).startswith("No recent run")
    # Power BI (Desktop .pbix) cases.
    assert _suggest_action({"kind": "pbi", "modified": "x", "fresh": False,
                            "run_ok": None}).startswith("Open the report")
    assert _suggest_action({"kind": "pbi", "modified": None, "fresh": None,
                            "run_ok": None}).startswith("Report not found")
    assert _suggest_action({"kind": "pbi", "modified": "x", "fresh": True,
                            "run_ok": False}).startswith("Power BI refresh failed")
    assert _suggest_action({"kind": "pbi", "modified": "x", "fresh": True,
                            "run_ok": None}) is None
    # Manual upload (Alvys Master) cases.
    assert _suggest_action({"feed": "Manual upload", "modified": "x",
                            "fresh": False}).startswith("Stale")
    assert _suggest_action({"feed": "Manual upload", "modified": None,
                            "fresh": None}).startswith("File not found")
    assert _suggest_action({"feed": "Manual upload", "modified": "x", "fresh": True}) is None
    # Healthy source -> no action.
    assert _suggest_action({"kind": "file", "modified": "x", "fresh": True,
                            "run_ok": True}) is None


def test_build_refresh_status_page_renders_all_sources():
    status = [
        {"label": "Alvys", "kind": "share", "wf": "refresh.yml", "modified": _NOW - timedelta(hours=16),
         "stale_h": 16, "fresh": True, "max_h": 30, "run_icon": "OK", "run_detail": "success",
         "run_ok": True, "measure": None},
        {"label": "SambaSafety", "kind": "file", "wf": "sambasafety_refresh.yml",
         "modified": _NOW - timedelta(hours=80), "stale_h": 80, "fresh": False, "max_h": 60,
         "run_icon": "X", "run_detail": "failure", "run_ok": False, "measure": None,
         "feed": "CSV combine"},
        {"label": "Knowledge Base Wiki", "kind": "wiki", "wf": "karpathy_compile.yml",
         "modified": _NOW - timedelta(hours=3), "stale_h": 3, "fresh": True, "max_h": 48,
         "run_icon": "OK", "run_detail": "success", "run_ok": True,
         "measure": {"total": 80, "wiki": 32, "raw": 42}},
        {"label": "Power BI XFreight Report", "kind": "pbi", "wf": None,
         "modified": _NOW - timedelta(hours=5), "stale_h": 5, "fresh": True, "max_h": 30,
         "run_icon": "&mdash;", "run_detail": "&mdash;", "run_ok": None, "measure": None,
         "feed": "Power BI Desktop"},
    ]
    html = build_refresh_status_page(status, "Saturday, June 13, 2026")
    for label in ("Alvys", "SambaSafety", "Knowledge Base Wiki", "Power BI XFreight Report"):
        assert label in html
    assert "Data refresh status" in html
    assert "Date &amp; time" in html and "Age" in html       # dedicated date/time + age columns
    assert "Suggested action" in html                        # action column header
    assert "16h ago" in html                                 # relative age rendered
    assert "32 wiki / 42 raw files" in html                  # knowledge-base size measurement
    assert "Refresh failed" in html                          # SambaSafety failed run -> action
    assert "CSV combine" in html                             # SambaSafety relabeled as CSV source
    assert "Power BI Desktop" in html                        # Power BI tracked via .pbix file


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
