"""Verify XFreight Master.xlsx is a safe drop-in replacement for Alvys Master2026.xlsx.

Two levels of comparison:

LEVEL 1 — structure (tabs / column names / row counts / whole-file sums):
  catches anything that would break a Power BI query pointed at the new file.

LEVEL 2 — like-for-like June 2026 load-level diff on the Loads sheet:
  restricts both files to loads whose Load # appears in BOTH, compares
  Customer Revenue / Driver Rate / Carrier Rate / Gross Margin per load,
  and prints the worst mismatches so the source of any drift is obvious.
  Also reports loads present in only one file (date-coverage difference).

Exit 0 = structure safe. Value drift is reported but doesn't fail the run.

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

_DIFF_COLS = ["Customer Revenue", "Driver Rate", "Carrier Rate", "Gross Margin"]


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0)
    return pd.Series(0.0, index=df.index)


def _month_window(df: pd.DataFrame) -> pd.Series:
    """True for rows whose Scheduled Pickup falls in June 2026."""
    for c in ("Scheduled Pickup", "Scheduled Pickup Date", "Pickup Date"):
        if c in df.columns:
            d = pd.to_datetime(df[c], errors="coerce")
            return (d >= "2026-06-01") & (d < "2026-07-01")
    return pd.Series(False, index=df.index)


def _level2_loads_diff(mdf: pd.DataFrame, cdf: pd.DataFrame) -> None:
    log.info("")
    log.info("=" * 60)
    log.info("LEVEL 2 — June 2026 load-level diff (Loads sheet)")
    log.info("=" * 60)

    if "Load #" not in mdf.columns or "Load #" not in cdf.columns:
        log.warning("Load # column missing — cannot diff by load")
        return

    m = mdf[_month_window(mdf)].copy()
    c = cdf[_month_window(cdf)].copy()
    m["__key"] = m["Load #"].astype(str).str.strip()
    c["__key"] = c["Load #"].astype(str).str.strip()
    m = m.drop_duplicates(subset="__key")
    c = c.drop_duplicates(subset="__key")

    m_keys, c_keys = set(m["__key"]), set(c["__key"])
    both = m_keys & c_keys
    only_m = m_keys - c_keys
    only_c = c_keys - m_keys

    log.info("June 2026 loads: Master=%d | Combined=%d | in both=%d",
             len(m_keys), len(c_keys), len(both))
    if only_m:
        log.info("  only in Master 2026 (%d): %s", len(only_m),
                 sorted(only_m)[:15])
    if only_c:
        log.info("  only in XFreight Master (%d): %s", len(only_c),
                 sorted(only_c)[:15])

    mi = m.set_index("__key").loc[sorted(both)]
    ci = c.set_index("__key").loc[sorted(both)]

    for col in _DIFF_COLS:
        mv, cv = _num(mi, col), _num(ci, col)
        delta = (cv - mv).round(2)
        n_diff = int((delta.abs() > 0.01).sum())
        log.info("")
        log.info("--- %s: %d/%d loads differ | Master total $%s | Combined total $%s | delta $%s",
                 col, n_diff, len(both),
                 f"{mv.sum():,.2f}", f"{cv.sum():,.2f}", f"{(cv.sum()-mv.sum()):,.2f}")
        if n_diff:
            worst = delta.abs().sort_values(ascending=False).head(10)
            log.info("    worst mismatches (load #: master -> combined, delta):")
            for k in worst.index:
                log.info("      %-12s $%12,.2f -> $%12,.2f   (Δ $%s)",
                         k, mv.loc[k], cv.loc[k], f"{delta.loc[k]:,.2f}")

    # Carrier Rate population comparison — how many loads have CR > 0 in each
    m_cr, c_cr = _num(mi, "Carrier Rate"), _num(ci, "Carrier Rate")
    log.info("")
    log.info("--- Carrier Rate population: Master has CR>0 on %d loads, Combined on %d loads",
             int((m_cr > 0).sum()), int((c_cr > 0).sum()))
    gained = sorted(k for k in both if m_cr.loc[k] == 0 and c_cr.loc[k] > 0)[:10]
    lost = sorted(k for k in both if m_cr.loc[k] > 0 and c_cr.loc[k] == 0)[:10]
    if lost:
        log.info("    loads where Master has CR but Combined reads $0 (first 10): %s", lost)
    if gained:
        log.info("    loads where Combined has CR but Master reads $0 (first 10): %s", gained)


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

    # Level 2: like-for-like June 2026 load diff
    if "Loads" in master and "Loads" in combined:
        _level2_loads_diff(master["Loads"], combined["Loads"])

    log.info("")
    log.info("=" * 60)
    if problems:
        log.error("CUTOVER NOT SAFE — %d problem(s):", len(problems))
        for p in problems:
            log.error("  • %s", p)
        return 1
    log.info("STRUCTURE SAFE — every Master 2026 tab and column exists in")
    log.info("XFreight Master with identical names. Review the Level 2 value")
    log.info("diff above before trusting the numbers in Power BI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
