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

  InvalidLicenseReport.csv ->  Invalid Licenses sheet (optional)
    First Name + Last Name      ->  Driver Name
    License Status              ->  License Status   (DISQUALIFIED / SUSPENDED…)
    Latest Action (+ Date)      ->  Latest Action / Latest Action Date
    MVR Date / License # / State / Type / MVR Score / Group / Latest Note
                                ->  carried through verbatim
    The invalid statuses are ALSO overlaid onto the Drivers sheet (matched by
    license number, then by name) because the Risk Index export keeps showing
    VALID for a driver SambaSafety has already disqualified — without the
    overlay, page 2's license-issue detection would miss the disqualification.

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
import re
import sys
from pathlib import Path

import pandas as pd


log = logging.getLogger(__name__)


# Canonical FMCSA BASIC category names (lower-case, used to identify data rows).
_CSA_BASICS = frozenset({
    "unsafe driving", "maintenance", "hos compliance",
    "hours-of-service compliance", "crash indicator",
    "hazardous materials", "haz mat", "driver fitness",
    "controlled substances/alcohol", "controlled substances",
    "drugs/alcohol", "drugs & alcohol",
})


def _build_csa_scorecard(csa_csv) -> pd.DataFrame:
    """Parse a SambaSafety CSA2010 Preview Scorecard CSV into a clean DataFrame.

    Columns: Category, Percentile, BASICMeasure, SegmentViolations,
    RelevantInspections, SnapshotDate, DOTNumber, AvgPowerUnits.

    Parsing strategy: scan all rows; extract metadata from header text, then
    collect rows whose first cell matches a known BASIC category name. The
    percentile is the last numeric value per row; BASIC measure is
    second-to-last; first numeric is segment violations.
    """
    def _read_raw(src):
        # engine='python' handles rows with inconsistent field counts
        # (the C engine infers column count from row 1 and crashes on row N
        # if the new CSV export adds an extra column mid-file)
        kw = dict(header=None, dtype=str, engine="python", on_bad_lines="skip")
        if isinstance(src, (bytes, bytearray)):
            return pd.read_csv(io.BytesIO(src), **kw)
        if isinstance(src, str) and "\n" in src:
            return pd.read_csv(io.StringIO(src), **kw)
        return pd.read_csv(src, **kw)

    try:
        raw = _read_raw(csa_csv)
    except Exception as e:
        log.warning("CSA scorecard CSV parse error: %s", e)
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    # --- Extract metadata from any row that contains it -----------------
    meta = {"SnapshotDate": "", "DOTNumber": "", "AvgPowerUnits": ""}
    for _, row in raw.iterrows():
        row_str = " ".join(str(v) for v in row.values if pd.notna(v) and str(v).strip())
        if not row_str:
            continue
        m = re.search(r'[Ss]napshot\s+date[:\s]+(\d{1,2}/\d{1,2}/\d{4})', row_str)
        if m:
            meta["SnapshotDate"] = m.group(1)
        m = re.search(r'DOT#?\s*(\d+)', row_str)
        if m:
            meta["DOTNumber"] = m.group(1)
        m = re.search(r'Avg\s+Power\s+Units[:\s]+([\d.]+)', row_str)
        if m:
            meta["AvgPowerUnits"] = m.group(1)

    # --- Collect BASIC category rows ------------------------------------
    rows = []
    for _, row in raw.iterrows():
        vals = [str(v).strip() for v in row.values if pd.notna(v) and str(v).strip()]
        if not vals:
            continue
        first = vals[0].lower().rstrip("*").strip()
        if first not in _CSA_BASICS and not any(k in first for k in _CSA_BASICS):
            continue
        nums = []
        for v in vals[1:]:
            v_clean = v.rstrip("*").replace(",", "").strip()
            try:
                nums.append(float(v_clean))
            except ValueError:
                pass  # skip text cols (Based On, % Comparison)
        pct = nums[-1] if nums else float("nan")
        measure = nums[-2] if len(nums) >= 2 else float("nan")
        seg_viol = nums[0] if nums else float("nan")
        rel_insp = nums[1] if len(nums) >= 3 else seg_viol
        rows.append({
            "Category": vals[0].rstrip("*"),
            "Percentile": pct,
            "BASICMeasure": measure,
            "SegmentViolations": seg_viol,
            "RelevantInspections": rel_insp,
            "SnapshotDate": meta["SnapshotDate"],
            "DOTNumber": meta["DOTNumber"],
            "AvgPowerUnits": meta["AvgPowerUnits"],
        })

    if not rows:
        log.warning("CSA scorecard CSV: no BASIC category rows found")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=[
        "Category", "Percentile", "BASICMeasure", "SegmentViolations",
        "RelevantInspections", "SnapshotDate", "DOTNumber", "AvgPowerUnits",
    ])
    log.info("CSA scorecard: %d BASIC categories (snapshot: %s, DOT: %s)",
             len(df), meta["SnapshotDate"], meta["DOTNumber"])
    return df


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


_INVALID_COLS = [
    "Driver Name", "License Type", "License Status", "Latest Action",
    "Latest Action Date", "MVR Date", "License Number", "License State",
    "MVR Score", "Group", "Note",
]


def _norm_license(num) -> str:
    """Normalize a license number for matching: uppercase, alnum only,
    leading zeros stripped (risk index pads SD numbers — '01234676' vs
    the invalid report's '1234676')."""
    s = re.sub(r"[^A-Z0-9]", "", str(num or "").upper())
    return s.lstrip("0")


def _build_invalid_licenses(inv_df: pd.DataFrame) -> pd.DataFrame:
    """One row per driver flagged by the Invalid License Report."""
    if inv_df is None or inv_df.empty:
        return pd.DataFrame(columns=_INVALID_COLS)

    def _col(name, default=""):
        return inv_df[name] if name in inv_df.columns else pd.Series(
            [default] * len(inv_df), index=inv_df.index)

    out = pd.DataFrame({
        "Driver Name": [
            _driver_name(f, l)
            for f, l in zip(_col("First Name"), _col("Last Name"))
        ],
        "License Type": _col("License Type").astype(str).str.strip(),
        "License Status": _col("License Status").astype(str).str.strip(),
        "Latest Action": _col("Latest Action").astype(str).str.strip(),
        "Latest Action Date": pd.to_datetime(
            _col("Latest Action Date"), errors="coerce"),
        "MVR Date": pd.to_datetime(_col("MVR Date"), errors="coerce"),
        "License Number": _col("License Number").astype(str).str.strip(),
        "License State": _col("License State").astype(str).str.strip(),
        "MVR Score": pd.to_numeric(_col("MVR Score"), errors="coerce"),
        "Group": _col("Group").astype(str).str.strip(),
        "Note": _col("Latest Note").astype(str).str.strip(),
    })
    out = out[out["Driver Name"].astype(str).str.strip() != ""]
    return out.reset_index(drop=True)


def _overlay_invalid_status(drivers: pd.DataFrame,
                            invalid: pd.DataFrame) -> pd.DataFrame:
    """Stamp the Invalid License Report's status onto matching Drivers rows.

    The Risk Index export can keep reporting VALID after SambaSafety has
    disqualified the driver (the invalid report is the fresher signal), so
    the invalid status wins. Match by normalized license number first,
    falling back to case-insensitive full name."""
    if drivers.empty or invalid.empty:
        return drivers
    by_license = {
        _norm_license(r["License Number"]): str(r["License Status"]).strip()
        for _, r in invalid.iterrows() if _norm_license(r["License Number"])
    }
    by_name = {
        str(r["Driver Name"]).strip().lower(): str(r["License Status"]).strip()
        for _, r in invalid.iterrows() if str(r["Driver Name"]).strip()
    }
    n_hit = 0
    for idx, row in drivers.iterrows():
        status = (by_license.get(_norm_license(row.get("License Number")))
                  or by_name.get(str(row.get("Driver Name", "")).strip().lower()))
        if status and status.upper() != str(row.get("License Status", "")).strip().upper():
            drivers.at[idx, "License Status"] = status
            n_hit += 1
    if n_hit:
        log.info("Invalid-license overlay: %d driver(s) re-stamped on Drivers sheet", n_hit)
    return drivers


def combine_to_workbook(risk_csv: bytes | str | Path, violations_csv: bytes | str | Path,
                        csa_csv: bytes | str | Path | None = None,
                        invalid_csv: bytes | str | Path | None = None) -> bytes:
    """Read SambaSafety CSVs and return the merged XLSX as bytes.
    Inputs may be paths or raw CSV bytes.
    When csa_csv is provided, a 'CSA Scorecard' sheet is added.
    When invalid_csv is provided, an 'Invalid Licenses' sheet is added and
    the invalid statuses are overlaid onto the Drivers sheet."""
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
    csa = _build_csa_scorecard(csa_csv) if csa_csv is not None else pd.DataFrame()
    invalid = pd.DataFrame(columns=_INVALID_COLS)
    if invalid_csv is not None:
        try:
            invalid = _build_invalid_licenses(_read(invalid_csv))
        except Exception as e:
            log.warning("Invalid License Report parse error (%s) — sheet omitted", e)
    drivers = _overlay_invalid_status(drivers, invalid)
    log.info("SambaSafety combine: %d drivers, %d violations, %d CSA BASIC rows, "
             "%d invalid license(s)",
             len(drivers), len(violations), len(csa), len(invalid))

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        drivers.to_excel(writer, sheet_name="Drivers", index=False)
        violations.to_excel(writer, sheet_name="Violations", index=False)
        invalid.to_excel(writer, sheet_name="Invalid Licenses", index=False)
        if not csa.empty:
            csa.to_excel(writer, sheet_name="CSA Scorecard", index=False)
    return buf.getvalue()


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--risk-index", required=True, help="Path to risk_index_report.csv")
    ap.add_argument("--violations", required=True, help="Path to violationsReport.csv")
    ap.add_argument("--invalid", default=None,
                    help="Path to InvalidLicenseReport.csv (optional)")
    ap.add_argument("--out", default="output/sambasafety/SambaSafety_Master.xlsx",
                    help="Output XLSX path")
    args = ap.parse_args()

    out_bytes = combine_to_workbook(args.risk_index, args.violations,
                                    invalid_csv=args.invalid)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out_bytes)
    log.info("Wrote %s (%d bytes)", out_path, len(out_bytes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
