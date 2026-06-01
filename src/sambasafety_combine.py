"""Combine the raw SambaSafety CSV exports into the workbook the scorecard
email reads.

SambaSafety's "Risk Index Report" and "Violations Report" arrive as separate
CSVs with their own column conventions. This module folds them into a single
``SambaSafety_Master.xlsx`` with two sheets — ``Drivers`` and ``Violations`` —
shaped for ``compute_sambasafety`` in ``src.scorecard_email`` (page 9).

Mappings:
  risk_index_report.csv ->  Drivers sheet
    First Name + Last Name      ->  Driver Name
    License Number              ->  License Number
    License State               ->  License State
    License Status              ->  License Status   (e.g., VALID)
    License Expiration Date     ->  License Expiration
    Current Risk Index Score    ->  Risk Score       (0-100+ scale)
    (derived from score)        ->  Risk Category    (Clean/Activity/Exception
                                                       -> Low/Medium/High so
                                                       the reader's "high risk"
                                                       detection still fires)

  violationsReport.csv  ->  Violations sheet
    First Name + Last Name      ->  Driver Name
    Violation Date              ->  Violation Date
    Violation Description       ->  Violation Type
    Violation Score             ->  Points
    State of Violation          ->  State
    (derived from score)        ->  Severity         (>=8 Major, 4-7 Moderate,
                                                       <4 Minor; the reader's
                                                       red/yellow coloring keys
                                                       off this)

Run locally:
    python -m src.sambasafety_combine \\
        --risk-index path/to/risk_index_report.csv \\
        --violations path/to/violationsReport.csv \\
        --out output/SambaSafety_Master.xlsx
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from pathlib import Path

import pandas as pd


log = logging.getLogger(__name__)


# SambaSafety risk-index buckets, mapped to text categories our reader
# recognizes: page 9's high-risk detection looks for "high" in the category
# string. Without this mapping, all drivers would score below the numeric
# fallback threshold (SAMBA_HIGH_RISK_SCORE=70) and nothing would surface.
CLEAN_MAX = 0          # score == 0  -> "Low"   (Clean)
ACTIVITY_MAX = 15      # score 1-15  -> "Medium" (Activity)
                       # score >=16  -> "High"   (Exception)


def _risk_category(score) -> str:
    s = pd.to_numeric(score, errors="coerce")
    if pd.isna(s):
        return ""
    if s <= CLEAN_MAX:
        return "Low"
    if s <= ACTIVITY_MAX:
        return "Medium"
    return "High"


def _severity(violation_score) -> str:
    s = pd.to_numeric(violation_score, errors="coerce")
    if pd.isna(s):
        return "Minor"
    if s >= 8:
        return "Major"
    if s >= 4:
        return "Moderate"
    return "Minor"


def _driver_name(first, last) -> str:
    parts = []
    for p in (first, last):
        if pd.notna(p) and str(p).strip().lower() not in ("", "nan"):
            parts.append(str(p).strip())
    return " ".join(parts)


def _build_drivers(risk_df: pd.DataFrame) -> pd.DataFrame:
    """One row per driver, shape matched to compute_sambasafety's fuzzy reader."""
    if risk_df.empty:
        return pd.DataFrame(columns=[
            "Driver Name", "License Number", "License State", "License Status",
            "License Expiration", "Risk Score", "Risk Category",
        ])
    out = pd.DataFrame({
        "Driver Name": [
            _driver_name(f, l) for f, l in zip(risk_df["First Name"], risk_df["Last Name"])
        ],
        "License Number": risk_df["License Number"].astype(str).str.strip(),
        "License State": risk_df["License State"].astype(str).str.strip(),
        "License Status": risk_df["License Status"].astype(str).str.strip(),
        "License Expiration": pd.to_datetime(
            risk_df["License Expiration Date"], errors="coerce"
        ),
        "Risk Score": pd.to_numeric(
            risk_df["Current Risk Index Score"], errors="coerce"
        ),
        "Risk Category": risk_df["Current Risk Index Score"].apply(_risk_category),
    })
    out = out[out["Driver Name"].astype(str).str.strip() != ""]
    return out.reset_index(drop=True)


def _build_violations(viol_df: pd.DataFrame) -> pd.DataFrame:
    """One row per violation, shape matched to compute_sambasafety's fuzzy reader."""
    if viol_df.empty:
        return pd.DataFrame(columns=[
            "Driver Name", "Violation Date", "Violation Type", "Points",
            "State", "Severity",
        ])
    out = pd.DataFrame({
        "Driver Name": [
            _driver_name(f, l) for f, l in zip(viol_df["First Name"], viol_df["Last Name"])
        ],
        "Violation Date": pd.to_datetime(viol_df["Violation Date"], errors="coerce"),
        "Violation Type": viol_df["Violation Description"].astype(str).str.strip(),
        "Points": pd.to_numeric(viol_df["Violation Score"], errors="coerce"),
        "State": viol_df["State of Violation"].astype(str).str.strip(),
        "Severity": viol_df["Violation Score"].apply(_severity),
    })
    out = out[out["Driver Name"].astype(str).str.strip() != ""]
    return out.sort_values("Violation Date", ascending=False, na_position="last").reset_index(drop=True)


def combine_to_workbook(risk_csv: bytes | str | Path, violations_csv: bytes | str | Path) -> bytes:
    """Read the two raw SambaSafety CSVs and return the merged XLSX as bytes.
    Inputs may be paths or raw CSV bytes."""
    def _read(src):
        if isinstance(src, (bytes, bytearray)):
            return pd.read_csv(io.BytesIO(src))
        if isinstance(src, str) and "\n" in src:   # treat as raw CSV text
            return pd.read_csv(io.StringIO(src))
        return pd.read_csv(src)

    risk_df = _read(risk_csv)
    viol_df = _read(violations_csv)
    drivers = _build_drivers(risk_df)
    violations = _build_violations(viol_df)
    log.info("SambaSafety combine: %d drivers, %d violations", len(drivers), len(violations))

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        drivers.to_excel(writer, sheet_name="Drivers", index=False)
        violations.to_excel(writer, sheet_name="Violations", index=False)
    return buf.getvalue()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--risk-index", required=True, help="Path to risk_index_report.csv")
    ap.add_argument("--violations", required=True, help="Path to violationsReport.csv")
    ap.add_argument("--out", default="output/sambasafety/SambaSafety_Master.xlsx",
                    help="Output XLSX path")
    args = ap.parse_args()

    out_bytes = combine_to_workbook(args.risk_index, args.violations)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out_bytes)
    log.info("Wrote %s (%d bytes)", out_path, len(out_bytes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
