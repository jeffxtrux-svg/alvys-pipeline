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
    assert set(by) == {"Alvys", "QuickBooks", "Samsara", "SambaSafety", "Google Sheets KPI",
                       "Knowledge Base Wiki", "Upload Health Check", "Scorecard Health Check",
                       "Power BI XFreight Report"}
    assert by["Alvys"]["fresh"] is True              # 10h <= 30h
    assert by["QuickBooks"]["fresh"] is False        # 20h  > 8h
    assert by["Samsara"]["fresh"] is True            # 5h  <= 30h
    assert by["SambaSafety"]["modified"] is None and by["SambaSafety"]["fresh"] is None
    # Power BI unconfigured -> "not configured", never crashes / hits network.
    assert by["Power BI XFreight Report"]["run_detail"] == "not configured"
    # Knowledge base: nonexistent dir -> no size; GH_TOKEN unset -> no run time.
    assert by["Knowledge Base Wiki"]["measure"] is None
    # GH_TOKEN unset -> Actions leg skipped, run cells left blank.
    assert by["Alvys"]["run_detail"] == "&mdash;"
    # New fields used by the suggested-action column.
    assert by["Alvys"]["kind"] == "share"
    assert by["QuickBooks"]["run_ok"] is None        # no GH_TOKEN -> unknown
    # Suggested actions derive from the row state.
    assert "stale" in _suggest_action(by["QuickBooks"]).lower()      # QB is stale
    assert "PBI" in _suggest_action(by["Power BI XFreight Report"])  # unconfigured
    assert "file not found" in _suggest_action(by["SambaSafety"])    # no file


def test_suggest_action_cases():
    assert _suggest_action({"kind": "file", "modified": "x", "fresh": False,
                            "run_ok": True}) .startswith("Data is stale")
    assert _suggest_action({"kind": "file", "modified": "x", "fresh": True,
                            "run_ok": False}).startswith("Refresh failed")
    assert _suggest_action({"kind": "file", "modified": None, "fresh": None,
                            "run_ok": True}).startswith("Source file not found")
    assert _suggest_action({"kind": "pbi", "modified": None, "run_ok": None,
                            "run_detail": "not configured"}).startswith("Set PBI")
    assert _suggest_action({"kind": "run", "modified": None, "run_ok": None,
                            "run_detail": "&mdash;", "wf": "x.yml"}).startswith("No recent run")
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
         "run_icon": "X", "run_detail": "failure", "run_ok": False, "measure": None},
        {"label": "Knowledge Base Wiki", "kind": "wiki", "wf": "karpathy_compile.yml",
         "modified": _NOW - timedelta(hours=3), "stale_h": 3, "fresh": True, "max_h": 48,
         "run_icon": "OK", "run_detail": "success", "run_ok": True,
         "measure": {"total": 80, "wiki": 32, "raw": 42}},
        {"label": "Power BI XFreight Report", "kind": "pbi", "wf": None, "modified": None,
         "stale_h": None, "fresh": None, "max_h": 30, "run_icon": "&mdash;",
         "run_detail": "not configured", "run_ok": None, "measure": None},
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
    assert "Set PBI" in html                                 # Power BI unconfigured -> action
    assert "not configured" in html                          # Power BI run cell


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
