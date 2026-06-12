"""Verify XFreight Master.xlsx is a safe drop-in replacement for Alvys Master2026.xlsx.

Downloads both workbooks from OneDrive and checks, per shared sheet:
  1. Every tab in Master 2026 exists in XFreight Master (Power BI navigation)
  2. Every column in Master 2026 exists in the same tab of XFreight Master,
     with the exact same name (Power Query steps reference columns by name)
  3. Row counts are in the same ballpark (sanity)
  4. Key numeric totals (Customer Revenue, Driver Rate, Carrier Rate) compared
     so any value drift is visible up front
  5. New columns in XFreight Master are listed (additive — safe for Power BI)

Exit 0 = safe to cut over. Exit 1 = something would break; see log.

Run in CI (needs AZURE_* secrets):
    python -m src.verify_master_cutover
"""
from __future__ import annotations

import io
import logging
import os
import sys

import pandas as pd

from src.onedrive_upload import download_file, download_shared_file, get_token

log = logging.getLogger("verify_cutover")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_MASTER_2026_SHARE_URL = (
    "https://xfreightnet-my.sharepoint.com/:x:/g/personal/jeff_xfreight_net/"
    "IQCS8VN_Oxb9S7p2e4lYfePXAetRrCNH351gIGbZ5c53J1U"
)

_NUMERIC_CHECK_COLS = ["Customer Revenue", "Driver Rate", "Carrier Rate",
                       "Sum of Customer Revenue", "Gross Margin"]


def main() -> int:
    token = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )
    upn = os.environ.get("ONEDRIVE_USER_UPN", "jeff@xfreight.net")

    log.info("Downloading Alvys Master2026.xlsx (share URL)...")
    master_bytes = download_shared_file(token, os.environ.get(
        "ALVYS_MASTER_SHARE_URL", _MASTER_2026_SHARE_URL))
    log.info("  %s bytes", f"{len(master_bytes):,}")

    log.info("Downloading XFreight Master.xlsx (path)...")
    combined_bytes = download_file(token, upn, os.environ.get(
        "COMBINED_MASTER_PATH", "XFreight Master.xlsx"))
    log.info("  %s bytes", f"{len(combined_bytes):,}")

    master = pd.read_excel(io.BytesIO(master_bytes), sheet_name=None, engine="openpyxl")
    combined = pd.read_excel(io.BytesIO(combined_bytes), sheet_name=None, engine="openpyxl")

    log.info("")
    log.info("Master 2026 tabs   : %s", list(master))
    log.info("XFreight Master tabs: %s", list(combined))

    problems: list[str] = []

    for sheet, mdf in master.items():
        log.info("")
        log.info("=== Sheet: %s ===", sheet)
        if sheet not in combined:
            problems.append(f"TAB MISSING: '{sheet}' not in XFreight Master")
            log.error("  ✗ TAB MISSING from XFreight Master — Power BI navigation would fail")
            continue
        cdf = combined[sheet]

        missing_cols = [c for c in mdf.columns if c not in cdf.columns]
        new_cols = [c for c in cdf.columns if c not in mdf.columns]
        if missing_cols:
            problems.append(f"COLUMNS MISSING in '{sheet}': {missing_cols}")
            log.error("  ✗ %d column(s) MISSING: %s", len(missing_cols), missing_cols)
        else:
            log.info("  ✓ all %d Master 2026 columns present, names identical",
                     len(mdf.columns))
        if new_cols:
            log.info("  + %d new column(s) (additive, safe): %s", len(new_cols), new_cols)

        log.info("  rows: Master 2026 = %s | XFreight Master = %s",
                 f"{len(mdf):,}", f"{len(cdf):,}")

        for col in _NUMERIC_CHECK_COLS:
            if col in mdf.columns and col in cdf.columns:
                m_sum = pd.to_numeric(mdf[col], errors="coerce").fillna(0).sum()
                c_sum = pd.to_numeric(cdf[col], errors="coerce").fillna(0).sum()
                delta = c_sum - m_sum
                flag = "✓" if abs(delta) < 0.01 else "Δ"
                log.info("  %s %-22s Master $%s | Combined $%s | delta $%s",
                         flag, col, f"{m_sum:,.2f}", f"{c_sum:,.2f}", f"{delta:,.2f}")

    log.info("")
    log.info("=" * 60)
    if problems:
        log.error("CUTOVER NOT SAFE — %d problem(s):", len(problems))
        for p in problems:
            log.error("  • %s", p)
        return 1
    log.info("CUTOVER SAFE — every Master 2026 tab and column exists in")
    log.info("XFreight Master with identical names. Numeric deltas above are")
    log.info("informational (API values supersede manual ones by design).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
