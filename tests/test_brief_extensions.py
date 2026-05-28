"""Regression tests for the executive-brief extensions:

  - hardened JW Logistics matcher (case/punctuation variants)
  - invoice-number normalization that handles QuickBooks' "T" prefix
  - QB-vs-Alvys AR reconciliation (totals, customer rollup, bill-by-bill)
  - Alvys AR with invoiced-only basis + JW exclusion + by-customer rollup
  - delivered-not-invoiced page logic
  - DVIR defect explosion using vehicleDefects / isResolved / DVIR startTime
  - compute_samsara on tz-aware safety timestamps (the crash this guards against)
  - _customer_name fallback through the customers lookup

Run directly (needs pandas):  python tests/test_brief_extensions.py
Or via pytest:                pytest tests/test_brief_extensions.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scorecard_email import (  # noqa: E402
    _norm_name, _is_ar_excluded, _norm_inv, _to_naive_dt, _cell,
    _is_direct_customer, compute_rpm_trend, build_page1,
    compute_alvys_ar, compute_alvys_uninvoiced, compute_qb_ar_detail,
    compute_ar_reconciliation, compute_ar_customer_reconciliation,
    compute_bill_reconciliation, compute_samsara, compute_alvys_entities,
)
from src.samsara_main import build_dvir_defects  # noqa: E402
from src import lookups  # noqa: E402
from src.column_mappings import _customer_name  # noqa: E402


def _today():
    return pd.Timestamp.now().normalize()


def _load(office, customer, load_no, rev, due_days, paid=0, status="Delivered",
          invoice_no=None, invoiced_offset=None):
    """One Alvys Loads row used across the AR tests."""
    today = _today()
    inv_off = invoiced_offset if invoiced_offset is not None else due_days + 30
    return {
        "Office": office, "Customer": customer, "Load #": load_no,
        "Customer Invoice Number": invoice_no,
        "Customer Revenue": rev, "Customer Payments": paid,
        "Customer Due Date": today - pd.Timedelta(days=due_days),
        "Invoiced Date": today - pd.Timedelta(days=inv_off),
        "Load Status": status,
    }


# ---------------------------------------------------------------------------
# JW exclusion: matcher must catch case/punctuation variants
# ---------------------------------------------------------------------------
def test_hardened_jw_matcher():
    for nm in ["JW Logistics", "jw logistics llc", "J.W. Logistics", "JW-Logistics",
               "J.W. Logistics, LLC", "  JW   Logistics  "]:
        assert _is_ar_excluded(nm), f"should exclude: {nm!r} -> {_norm_name(nm)!r}"
    for nm in ["JWL Freight", "Jonathan Walters", "JW Transport"]:
        assert not _is_ar_excluded(nm), f"should NOT exclude: {nm!r}"


# ---------------------------------------------------------------------------
# Invoice number normalization: strip a leading alpha prefix
# ---------------------------------------------------------------------------
def test_norm_inv_strips_leading_alpha():
    assert _norm_inv("T1006199") == "1006199"
    assert _norm_inv("1006199") == "1006199"
    assert _norm_inv("INV1001") == "1001"
    assert _norm_inv("T-1006199") == "1006199"
    assert _norm_inv("nan") == ""
    assert _norm_inv(None) == ""


# ---------------------------------------------------------------------------
# Alvys AR: invoiced-only basis, JW exclusion, X-Trux + X-Linx scope
# ---------------------------------------------------------------------------
def test_alvys_ar_basis_and_scope():
    loads = pd.DataFrame([
        _load("X-Trux, Inc", "Acme", "L1", 1000, 40),                          # X-Trux, invoiced, 31-60
        _load("X-Linx, Inc.", "Beta", "L2", 500, 5),                           # X-Linx, invoiced, 1-30
        _load("Truk-Way", "Gamma", "L3", 9999, 100),                           # out-of-scope office
        _load("X-Trux, Inc", "J.W. Logistics", "L4", 4000, 80),                # JW variant excluded
        _load("X-Trux, Inc", "Delta", "L5", 700, -10),                         # not yet due -> Current
        _load("X-Trux, Inc", "Echo", "L6", 800, 50, invoiced_offset=None),     # invoiced (control)
        _load("X-Trux, Inc", "UninvCo", "L7", 6000, 80,                        # delivered, NOT invoiced
              invoice_no=None, invoiced_offset=None, status="Delivered"),
    ])
    # Force UninvCo to be un-invoiced (Invoiced Date = NaT)
    loads.loc[loads["Customer"] == "UninvCo", "Invoiced Date"] = pd.NaT
    a = compute_alvys_ar({"Loads": loads})
    # Invoiced + in-scope + not-JW: Acme(1000) + Beta(500) + Delta(700) + Echo(800) = 3000.
    assert round(a["total"]) == 3000, a
    by = {r["name"]: r["amount"] for r in a["by_customer"].values()}
    for jw in ("J.W. Logistics", "JW Logistics", "JW Logistics LLC"):
        assert jw not in by, f"JW variant leaked into by_customer: {by}"
    # Per-bucket: Acme(1000, 40d) + Echo(800, 50d) -> 31-60 = 1800; Beta(500, 5d) -> 1-30;
    # Delta(700, due in future) -> current.
    assert round(a["d31_60"]) == 1800 and round(a["d1_30"]) == 500 and round(a["current"]) == 700
    # 61+ row list and 90+ customer rollup keys both present.
    assert "d61plus_rows" in a and "d91plus_customers" in a


# ---------------------------------------------------------------------------
# AR customer reconciliation: deltas sum to the headline variance
# ---------------------------------------------------------------------------
def test_ar_customer_reconciliation_sums_to_variance():
    qb = compute_qb_ar_detail(pd.DataFrame([
        {"Company": "X-Trux Inc", "Section": "Current", "Row_Type": "Data",
         "Customer": "Berry Plastics", "Open Balance": 2000},
        {"Company": "X-Linx Inc", "Section": "91 and over", "Row_Type": "Data",
         "Customer": "CH Robinson", "Open Balance": 4000},
        {"Company": "X-Trux Inc", "Section": "31 - 60", "Row_Type": "Data",
         "Customer": "QB Only Co", "Open Balance": 500},
    ]))
    aa = compute_alvys_ar({"Loads": pd.DataFrame([
        # Note name spelling variants on the Alvys side join via _norm_name.
        _load("X-Trux, Inc", "BERRY PLASTICS", "L1", 3000, 40),
        _load("X-Linx, Inc.", "CH ROBINSON", "L2", 6000, 95),
        _load("X-Trux, Inc", "Alvys Only LLC", "L3", 1500, 10),
    ])})
    rec = compute_ar_customer_reconciliation(qb, aa)
    # delta_total must equal qb.total_ar - alvys.total exactly.
    assert round(rec["delta_total"]) == round(qb["total_ar"] - aa["total"])
    by = {row["customer"].upper(): row for row in rec["rows"]}
    assert round(by["BERRY PLASTICS"]["delta"]) == 2000 - 3000     # QB lower -> negative
    assert round(by["CH ROBINSON"]["delta"]) == 4000 - 6000
    assert round(by["QB ONLY CO"]["delta"]) == 500                 # one-sided (QB only)
    assert round(by["ALVYS ONLY LLC"]["delta"]) == -1500           # one-sided (Alvys only)


# ---------------------------------------------------------------------------
# Bill reconciliation: auto-pick best key + T-prefix matching + no-match diag
# ---------------------------------------------------------------------------
def test_bill_reconciliation_matches_on_T_prefixed_load_number():
    qb = compute_qb_ar_detail(pd.DataFrame([
        {"Company": "X-Trux Inc", "Section": "Current", "Row_Type": "Data",
         "Customer": "Berry", "Num": "T1006199", "Open Balance": 2000},
        {"Company": "X-Trux Inc", "Section": "91 and over", "Row_Type": "Data",
         "Customer": "Echo", "Num": "T1006159", "Open Balance": 4000},
        {"Company": "X-Trux Inc", "Section": "31 - 60", "Row_Type": "Data",
         "Customer": "QB Only", "Num": "T9999999", "Open Balance": 700},
    ]))
    aa = compute_alvys_ar({"Loads": pd.DataFrame([
        # Alvys load # matches QB Num once the leading 'T' is stripped.
        _load("X-Trux, Inc", "Berry", "1006199", 2000, 40),
        _load("X-Trux, Inc", "Echo",  "1006159", 4500, 95),     # amount mismatch
        _load("X-Trux, Inc", "Alvys Only", "1006630", 1500, 80),
    ])})
    b = compute_bill_reconciliation(qb, aa)
    assert b["available"] and not b.get("no_match")
    assert b["key_used"] == "load", b
    assert b["matched"] == 2 and b["alvys_n"] == 3
    assert [r["invoice"] for r in b["alvys_only"]] == ["1006630"]
    assert len(b["mismatch"]) == 1 and round(b["mismatch"][0]["diff"]) == 500


def test_bill_reconciliation_no_match_returns_samples():
    qb = compute_qb_ar_detail(pd.DataFrame([
        {"Company": "X-Trux Inc", "Section": "Current", "Row_Type": "Data",
         "Customer": "C1", "Num": "XYZ-1", "Open Balance": 100},
    ]))
    aa = compute_alvys_ar({"Loads": pd.DataFrame([
        _load("X-Trux, Inc", "C2", "999", 200, 5),
    ])})
    b = compute_bill_reconciliation(qb, aa)
    assert b["available"] and b.get("no_match") is True
    assert b["alvys_sample"] and b["qb_sample"]


# ---------------------------------------------------------------------------
# Variance kind classification
# ---------------------------------------------------------------------------
def test_compute_ar_reconciliation_kinds():
    # within 1% -> good
    assert compute_ar_reconciliation({"total_ar": 1000.0}, {"total": 995.0})["kind"] == "good"
    # ~3% -> warn
    assert compute_ar_reconciliation({"total_ar": 1000.0}, {"total": 970.0})["kind"] == "warn"
    # >5% -> bad
    assert compute_ar_reconciliation({"total_ar": 1000.0}, {"total": 700.0})["kind"] == "bad"


# ---------------------------------------------------------------------------
# Delivered-not-invoiced page
# ---------------------------------------------------------------------------
def test_alvys_uninvoiced_pure_delivered_not_invoiced():
    today = _today()
    NA = pd.NaT
    loads = pd.DataFrame([
        # delivered + un-invoiced -> include
        {"Office": "X-Trux, Inc", "Customer": "Acme", "Load #": "1",
         "Customer Revenue": 1200, "Customer Payments": 0,
         "Actual Delivery": today - pd.Timedelta(days=10),
         "Scheduled Delivery": today - pd.Timedelta(days=30),
         "Invoiced Date": NA, "Load Status": "Delivered"},
        # invoiced -> exclude
        {"Office": "X-Trux, Inc", "Customer": "Beta", "Load #": "2",
         "Customer Revenue": 800, "Customer Payments": 0,
         "Actual Delivery": today - pd.Timedelta(days=5),
         "Scheduled Delivery": today - pd.Timedelta(days=20),
         "Invoiced Date": today - pd.Timedelta(days=2), "Load Status": "Delivered"},
        # delivered + un-invoiced but JW -> exclude
        {"Office": "X-Trux, Inc", "Customer": "JW Logistics", "Load #": "3",
         "Customer Revenue": 4000, "Customer Payments": 0,
         "Actual Delivery": today - pd.Timedelta(days=20),
         "Scheduled Delivery": today - pd.Timedelta(days=40),
         "Invoiced Date": NA, "Load Status": "Delivered"},
    ])
    u = compute_alvys_uninvoiced({"Loads": loads})
    assert u["count"] == 1 and round(u["total_revenue"]) == 1200
    # Actual delivery preferred over scheduled
    assert u["rows"][0]["days"] == 10


# ---------------------------------------------------------------------------
# Samsara: tz-aware safety timestamps don't crash compute_samsara
# ---------------------------------------------------------------------------
def test_compute_samsara_handles_tz_aware_timestamps():
    events = pd.DataFrame({
        "time": ["2026-05-28T01:00:00Z", "2026-05-27T12:00:00Z"],
        "Event Type": ["Harsh Brake", "Speeding"],
        "Severity": ["high", "med"],
        "Driver Name": ["A", "B"], "Unit": ["T1", "T2"],
        "Status": ["needsReview", "reviewed"],
    })
    defects = pd.DataFrame({
        "Reported": ["2026-05-28 00:10:00", "2026-04-01 00:00:00"],
        "Unit": ["T1", "T2"], "Driver": ["A", "B"],
        "Defect": ["tire", "light"], "Defect Type": ["Tire", "Light"],
        "Resolved": [False, True],
    })
    out = compute_samsara({"SafetyEvents": events, "DVIR_Defects": defects})
    # The mere fact this returns without raising is the regression we're guarding.
    assert out is not None and "windows" in out
    assert out["windows"]["events"]["mtd"] >= 1


def test_to_naive_dt_drops_timezone():
    d = _to_naive_dt(pd.Series(["2026-05-28T01:00:00Z", "2026-04-01T08:00:00+00:00"]))
    assert d.dt.tz is None
    assert d.notna().all()


# ---------------------------------------------------------------------------
# DVIR defect explosion: vehicleDefects + isResolved + DVIR startTime fallback
# ---------------------------------------------------------------------------
def test_build_dvir_defects_reads_vehicleDefects_and_uses_startTime():
    raw = [
        {  # one open + one resolved defect under vehicleDefects
            "id": "dvir1", "startTime": "2026-05-01T12:00:00Z",
            "vehicle": {"name": "T1"}, "driver": {"name": "A"},
            "type": "preTrip",
            "vehicleDefects": [
                {"defectType": "Tire", "isResolved": False,
                 "createdAtTime": "2026-05-01T12:30:00Z"},
                {"defectType": "Light", "isResolved": True,
                 "createdAtTime": "2026-05-01T12:31:00Z",
                 "resolvedBy": {"name": "MechBob"}},
            ],
        },
        {  # clean DVIR with no defects array
            "id": "dvir2", "startTime": "2026-05-02T08:00:00Z",
            "vehicle": {"name": "T2"}, "driver": {"name": "B"},
        },
        {  # trailer defect path
            "id": "dvir3", "startTime": "2026-05-03T09:00:00Z",
            "vehicle": {"name": "T3"}, "driver": {"name": "C"},
            "trailerDefects": [{"defectType": "Brakes", "isResolved": False,
                                "createdAtTime": "2026-05-03T09:15:00Z"}],
        },
    ]
    df = build_dvir_defects(raw)
    assert len(df) == 3
    # Reported dates resolved (defect createdAtTime), not all null.
    assert df["Reported"].notna().all() and (df["Reported"].astype(str) != "").all()
    # Resolved flag correctly read from isResolved
    assert sorted(df["Resolved"].tolist()) == [False, False, True]
    # Mechanic name from resolvedBy populates the notes column for the resolved one.
    notes = df[df["Resolved"]]["Mechanic Notes"].iloc[0]
    assert notes == "MechBob"


# ---------------------------------------------------------------------------
# _customer_name: falls back to customers lookup when CustomerName is blank
# ---------------------------------------------------------------------------
def test_customer_name_falls_back_to_lookup():
    lookups.customers_by_id.clear()
    lookups.customers_by_id["C1"] = {"Id": "C1", "Name": "Acme Logistics"}
    assert _customer_name({"CustomerName": "Direct Co"}) == "Direct Co"      # prefers direct
    assert _customer_name({"CustomerName": None, "CustomerId": "C1"}) == "Acme Logistics"
    assert _customer_name({"CustomerName": "", "CustomerId": "Cx"}) in (None, "")


# ---------------------------------------------------------------------------
# _cell maps pandas null / 'nan' to ''
# ---------------------------------------------------------------------------
def test_cell_collapses_null_to_empty_string():
    assert _cell(float("nan")) == "" and _cell(None) == "" and _cell("nan") == ""
    assert _cell("BERRY PLASTICS") == "BERRY PLASTICS"


# ---------------------------------------------------------------------------
# Direct vs broker customer classification + RPM trend tiles
# ---------------------------------------------------------------------------
def test_direct_customer_matcher_handles_prefixes_and_slashes():
    # Direct shippers — case-insensitive prefix match on the user-provided list.
    # Broker pass-throughs ("SHIPPER / BROKER") still count as direct freight when
    # the shipper segment is in the allow-list — the underlying shipper wins.
    for nm in ["BERRY PLASTICS", "Berry Plastics, Inc.", "amcor packaging",
               "BILLION Automotive", "Kozy Heat Fireplaces", "Innovative Office Products",
               "  KRAFT TOOL  ", "Dakota Pottery LLC",
               "BERRY PLASTICS / CH ROBINSON",        # brokered Berry -> direct
               "CH ROBINSON / BERRY PLASTICS"]:       # reverse order also caught
        assert _is_direct_customer(nm), f"should be direct: {nm!r}"
    # Broker-only or unknown names — no direct shipper anywhere in the string.
    for nm in ["CH Robinson", "ECHO GLOBAL LOGISTICS", "ECHO / NOLAN TRANSPORT",
               "Some Random Co", "", "nan", float("nan")]:
        assert not _is_direct_customer(nm), f"should NOT be direct: {nm!r}"


def test_compute_rpm_trend_splits_and_scopes_to_xtrux():
    today = pd.Timestamp.now().normalize()
    loads = pd.DataFrame([
        # Direct shipper, X-Trux office.
        {"Office": "X-Trux, Inc", "Customer": "BERRY PLASTICS",
         "Customer Revenue": 2400, "Total Dispatch Mileage": 1000,
         "Scheduled Pickup": today, "Load Status": "Delivered"},
        # Brokered (slash) under X-Trux — still direct because the shipper segment
        # ("BERRY PLASTICS") is in the allow-list.
        {"Office": "X-Trux, Inc", "Customer": "BERRY PLASTICS / CH ROBINSON",
         "Customer Revenue": 1800, "Total Dispatch Mileage": 1000,
         "Scheduled Pickup": today, "Load Status": "Delivered"},
        # Broker-only (no direct shipper anywhere in the name).
        {"Office": "X-Trux, Inc", "Customer": "CH ROBINSON",
         "Customer Revenue": 1500, "Total Dispatch Mileage": 1000,
         "Scheduled Pickup": today, "Load Status": "Delivered"},
        # Cancelled — excluded.
        {"Office": "X-Trux, Inc", "Customer": "AMCOR PACKAGING",
         "Customer Revenue": 9999, "Total Dispatch Mileage": 100,
         "Scheduled Pickup": today, "Load Status": "Cancelled"},
        # X-Linx brokerage — must be excluded by the office filter.
        {"Office": "X-Linx, Inc.", "Customer": "ECHO GLOBAL LOGISTICS",
         "Customer Revenue": 5000, "Total Dispatch Mileage": 100,
         "Scheduled Pickup": today, "Load Status": "Delivered"},
    ])
    out = compute_rpm_trend({"Loads": loads})
    d_labels, d_values = out["direct"]
    b_labels, b_values = out["broker"]
    c_labels, c_values = out["combined"]
    # 6-month window with current-month asterisk on all three series.
    for labels in (d_labels, b_labels, c_labels):
        assert len(labels) == 6 and labels[-1].endswith("*")
    # Direct = both Berry loads: (2400 + 1800) / (1000 + 1000) = $2.10
    assert round(d_values[-1], 2) == 2.10
    # Broker = plain CH ROBINSON: 1500 / 1000 = $1.50
    assert round(b_values[-1], 2) == 1.50
    # Combined = (2400 + 1800 + 1500) / 3000 = $1.90
    assert round(c_values[-1], 2) == 1.90
    # Prior months have no in-scope mileage -> 0, not NaN.
    assert d_values[0] == 0.0 and b_values[0] == 0.0 and c_values[0] == 0.0


def test_build_page1_renders_three_rpm_charts_in_xtrux_overview():
    # Smoke-render of build_page1 to confirm all three charts land in the HTML.
    alvys_entities = compute_alvys_entities({"Loads": pd.DataFrame([
        {"Office": "X-Trux, Inc", "Customer Revenue": 1000, "Driver Rate": 500,
         "Carrier Rate": 0, "Total Dispatch Mileage": 100, "Empty Dispatch Mileage": 10,
         "Scheduled Pickup": pd.Timestamp.now().normalize(), "Load Status": "Delivered"}])})
    months = ["Dec", "Jan", "Feb", "Mar", "Apr", "May*"]
    rpm_trend = {"direct":   (months, [2.5, 2.6, 2.4, 2.7, 2.8, 2.9]),
                 "broker":   (months, [1.9, 1.8, 1.7, 1.6, 1.85, 1.95]),
                 "combined": (months, [2.2, 2.2, 2.05, 2.15, 2.32, 2.42])}
    html = build_page1(None, alvys_entities, {}, {}, ([], []), ([], []), None,
                       "Thursday, May 28, 2026", rpm_trend=rpm_trend)
    assert "Overall &middot; rev / mile" in html
    assert "Direct customers" in html and "Broker freight" in html
    # Final-month value of each chart appears as the bar label.
    assert "$2.90" in html and "$1.95" in html and "$2.42" in html


# ---------------------------------------------------------------------------
# Tiny runner so the file works without pytest installed
# ---------------------------------------------------------------------------
def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            fails += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - fails}/{len(tests)} passed")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all())
