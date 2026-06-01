"""Tests for the SambaSafety CSV combiner.

Covers the mapping from the raw Risk Index Report + Violations Report CSVs
(as SambaSafety actually emails them) into the two-sheet workbook the
scorecard's compute_sambasafety reader expects.

Run directly:  python tests/test_sambasafety_combine.py
Or via pytest: pytest tests/test_sambasafety_combine.py
"""
import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sambasafety_combine import (  # noqa: E402
    _build_drivers, _build_violations, _risk_category, _severity, _driver_name,
    combine_to_workbook,
)
from src.scorecard_email import compute_sambasafety  # noqa: E402


# Sample CSVs in SambaSafety's actual export format
RISK_CSV = """\
,Group Name,Current Risk Index Score,MVR Score,Custom Person ID,First Name,Last Name,License State,License Number,Latest MVR Date,License Status,License Expiration Date,Average Score
1,X-Trux Inc,42,12,,Todd,Schneckloth,SD,01234676,2026-04-06,VALID,2028-10-31,39
2,X-Trux Inc,26,0,,Bradly,Miles,SD,00893946,2026-01-26,VALID,2026-06-15,27
3,X-Trux Inc,8,8,,Michael,Hall,SD,01527417,2026-01-26,VALID,2031-01-04,8
4,X-Trux Inc,0,0,,Shane,Allen,SD,02981192,2026-03-30,VALID,2031-04-21,0
"""

VIOL_CSV = '"First Name","Last Name","MVR Score","Violation Date","Violation Description","Violation Score","State of Violation","State of License","Conviction Date","MVR Date","ACD","AVD","Docket Number","Group","License Number","License Status","License Type","Location","Most Recent Note","State Points"\n' \
    '"BRIAN","UJCICH","10","2024-10-23","DISOBEDIENCE TO TRAFFIC CONTROL DEVICE","4","OH","SD","2024-12-05","2026-03-09","M14","MA14","","X-Trux Inc","02473930","VALID","COMMERCIAL","OH - OHIO","",""\n' \
    '"MICHAEL","HALL","8","2025-02-24","CARELESS DRIVING","8","LA","SD","2025-04-22","2026-01-26","M81","MK02","","X-Trux Inc","01527417","VALID","COMMERCIAL","LA - LOUISIANA","",""\n' \
    '"Lonnie","Summerfield","0","2019-05-22","SPEEDING","","OH","PA","2019-06-05","2026-04-17","S93","SA01","","X-Trux Inc","23226969","VALID","COMMERCIAL","","NON-SANCTIONED",""\n'


def test_risk_category_thresholds():
    # SambaSafety buckets: Clean (0), Activity (1-15), Exception (16+).
    # We re-label as Low / Medium / High so the reader's "high" detector fires.
    assert _risk_category(0) == "Low"
    assert _risk_category(1) == "Medium"
    assert _risk_category(15) == "Medium"
    assert _risk_category(16) == "High"
    assert _risk_category(42) == "High"
    assert _risk_category(None) == ""
    assert _risk_category(float("nan")) == ""


def test_severity_thresholds():
    assert _severity(8) == "Major"
    assert _severity(12) == "Major"
    assert _severity(4) == "Moderate"
    assert _severity(7) == "Moderate"
    assert _severity(3) == "Minor"
    assert _severity(0) == "Minor"
    assert _severity(None) == "Minor"
    assert _severity("") == "Minor"


def test_driver_name_concat():
    assert _driver_name("Todd", "Schneckloth") == "Todd Schneckloth"
    assert _driver_name("BRIAN", "UJCICH") == "BRIAN UJCICH"
    assert _driver_name("Todd", None) == "Todd"
    assert _driver_name(None, "Smith") == "Smith"
    assert _driver_name(None, None) == ""
    # NaN-as-string variants from CSV reads
    assert _driver_name(float("nan"), "Smith") == "Smith"


def test_build_drivers_shape():
    risk_df = pd.read_csv(io.StringIO(RISK_CSV))
    drivers = _build_drivers(risk_df)
    assert len(drivers) == 4
    assert list(drivers.columns) == [
        "Driver Name", "License Number", "License State", "License Status",
        "License Expiration", "Risk Score", "Risk Category",
    ]
    todd = drivers.iloc[0]
    assert todd["Driver Name"] == "Todd Schneckloth"
    assert todd["License State"] == "SD"
    assert todd["Risk Score"] == 42
    assert todd["Risk Category"] == "High"   # 42 maps to High
    # Expiration should round-trip as a Timestamp
    assert pd.Timestamp(todd["License Expiration"]).year == 2028


def test_build_violations_shape_and_sort():
    viol_df = pd.read_csv(io.StringIO(VIOL_CSV))
    v = _build_violations(viol_df)
    assert len(v) == 3
    # Sorted newest-first
    dates = pd.to_datetime(v["Violation Date"])
    assert dates.iloc[0] > dates.iloc[1] > dates.iloc[2]
    # Severity mapping: score 8 -> Major, score 4 -> Moderate, blank -> Minor
    sev_by_driver = dict(zip(v["Driver Name"], v["Severity"]))
    assert sev_by_driver["MICHAEL HALL"] == "Major"
    assert sev_by_driver["BRIAN UJCICH"] == "Moderate"
    assert sev_by_driver["Lonnie Summerfield"] == "Minor"   # blank score


def test_combine_to_workbook_round_trip_through_reader():
    """End-to-end: produce the XLSX from raw CSVs, then run it through the
    page-9 reader to confirm the shape it produces is what the reader expects."""
    xlsx_bytes = combine_to_workbook(RISK_CSV.encode(), VIOL_CSV.encode())
    sheets = pd.read_excel(io.BytesIO(xlsx_bytes), sheet_name=None)
    assert set(sheets.keys()) == {"Drivers", "Violations"}

    samba = compute_sambasafety(sheets, now=pd.Timestamp("2026-06-01"))
    assert samba is not None
    assert samba["monitored"] == 4
    # High-risk = drivers with score >= 16 in our mapping -> Todd, Bradly
    assert len(samba["high_risk"]) == 2
    names = {d["name"] for d in samba["high_risk"]}
    assert names == {"Todd Schneckloth", "Bradly Miles"}
    # Bradly's license expires 2026-06-15 vs "now" 2026-06-01 -> 14 days,
    # within LICENSE_EXPIRY_WARN_DAYS=30 -> flagged as a license issue.
    issue_names = {d["name"] for d in samba["license_issues"]}
    assert "Bradly Miles" in issue_names


if __name__ == "__main__":
    fns = {k: v for k, v in dict(globals()).items()
           if k.startswith("test_") and callable(v)}
    for name, fn in fns.items():
        fn()
        print(f"  ok  {name}")
    print(f"\n{len(fns)} tests passed")
