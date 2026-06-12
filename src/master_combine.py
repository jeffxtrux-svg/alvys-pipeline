"""
master_combine — build XFreight Master.xlsx from API output + manual gap fill.

Every time the Alvys pull completes, this module:
  1. Downloads the freshly uploaded Alvys Pipeline.xlsx (API data, every 2h)
  2. Downloads Alvys Master2026.xlsx (daily-maintained gap fill)
  3. For each shared sheet, detects columns present in Master 2026 but absent
     from the API output ("gap columns") and left-joins them onto the API rows
     using Load # as the join key.
  4. Rewrites Gross Margin = Customer Revenue − (Driver Rate + Carrier Rate)
     to keep the stored column consistent (matches master_fixer_gui.py logic).
  5. Uploads the result to OneDrive as XFreight Master.xlsx — the new single
     source of truth for Power BI and all reports.

Environment variables (all optional — defaults match current OneDrive layout):
  AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET  — shared Graph creds
  ONEDRIVE_USER_UPN            — default jeff@xfreight.net
  ALVYS_PIPELINE_PATH          — default "Alvys Pipeline.xlsx"
  ALVYS_MASTER_SHARE_URL       — SharePoint sharing URL for Alvys Master2026;
                                  preferred over path (resolves the exact file).
  ALVYS_MASTER_PATH            — fallback path if share URL not set/fails;
                                  default "Alvys Master2026.xlsx"
  COMBINED_MASTER_FILENAME     — default "XFreight Master.xlsx"
  COMBINED_MASTER_FOLDER       — OneDrive folder; default "" (root)
"""
from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import requests

from src.onedrive_upload import (
    download_file,
    download_shared_file,
    get_token,
    upload_file,
)

log = logging.getLogger("master_combine")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)

# Same sharing URL the scorecard uses — resolves the exact workbook Power BI reads.
_ALVYS_MASTER_SHARE_URL = (
    "https://xfreightnet-my.sharepoint.com/:x:/g/personal/jeff_xfreight_net/"
    "IQCS8VN_Oxb9S7p2e4lYfePXAetRrCNH351gIGbZ5c53J1U"
)

_LOAD_KEY_CANDIDATES = [
    "Load #", "Load#", "Load Number", "Load Num", "LoadNumber",
    "load #", "load#", "load_num",
]
_DR_CANDIDATES  = ["Driver Rate", "DriverRate", "Driver Pay"]
_CR_CANDIDATES  = ["Carrier Rate", "CarrierRate", "Sum of Carrier Rate", "Carrier Pay"]
_REV_CANDIDATES = ["Customer Revenue", "Revenue", "CustomerRevenue"]
_GM_CANDIDATES  = ["Gross Margin", "GrossMargin", "Margin"]


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols_lc = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in df.columns:
            return c
        if c.lower() in cols_lc:
            return cols_lc[c.lower()]
    return None


def _find_load_key(df: pd.DataFrame) -> str | None:
    return _find_col(df, _LOAD_KEY_CANDIDATES)


def _recompute_gm(df: pd.DataFrame, sheet: str) -> pd.DataFrame:
    """Rewrite Gross Margin = Customer Revenue − (Driver Rate + Carrier Rate).
    Matches the master_fixer_gui.py formula — DR + CR for all rows.
    """
    gm_col  = _find_col(df, _GM_CANDIDATES)
    rev_col = _find_col(df, _REV_CANDIDATES)
    dr_col  = _find_col(df, _DR_CANDIDATES)
    cr_col  = _find_col(df, _CR_CANDIDATES)
    if not (gm_col and rev_col and (dr_col or cr_col)):
        return df
    df = df.copy()
    rev = pd.to_numeric(df[rev_col], errors="coerce").fillna(0)
    dr  = pd.to_numeric(df[dr_col],  errors="coerce").fillna(0) if dr_col else 0
    cr  = pd.to_numeric(df[cr_col],  errors="coerce").fillna(0) if cr_col else 0
    computed = (rev - (dr + cr)).round(2)
    changed = int(
        (computed - pd.to_numeric(df[gm_col], errors="coerce").fillna(0))
        .abs().gt(0.005).sum()
    )
    df[gm_col] = computed
    if changed:
        log.info("  %-20s  GM recomputed on %d rows", sheet, changed)
    return df


# Columns where the API output is known-incomplete at the VALUE level: the
# column exists in both files, but the API reads 0/blank on rows where the
# manually maintained master has a real figure. For these, a per-row overlay
# fills API zeros/blanks from the master (API value wins when it's non-zero).
# Carrier Rate: the API maps the trip's Carrier.Rate.Amount, which is only
# populated on ~15% of brokered loads — the master carries the real carrier
# cost for the rest (June 2026 audit: master had CR on 112 loads, API on 15).
_VALUE_FILL_COLS = ["Carrier Rate"]


def _value_fill(sheet: str, api_df: pd.DataFrame, master_df: pd.DataFrame,
                api_key: str, mstr_key: str) -> pd.DataFrame:
    """Fill API zero/blank cells from the master for _VALUE_FILL_COLS."""
    for col in _VALUE_FILL_COLS:
        m_col = _find_col(master_df, [col])
        a_col = _find_col(api_df, [col])
        if not (m_col and a_col):
            continue
        m = master_df[[mstr_key, m_col]].copy()
        m["__k"] = m[mstr_key].astype(str).str.strip()
        m = m.drop_duplicates(subset="__k")
        m_vals = pd.to_numeric(m.set_index("__k")[m_col], errors="coerce")
        keys = api_df[api_key].astype(str).str.strip()
        api_vals = pd.to_numeric(api_df[a_col], errors="coerce").fillna(0)
        master_for_row = keys.map(m_vals).fillna(0)
        needs_fill = (api_vals == 0) & (master_for_row != 0)
        if needs_fill.any():
            api_df = api_df.copy()
            api_df.loc[needs_fill, a_col] = master_for_row[needs_fill]
            log.info("  %-20s  value-filled %s on %d row(s) from Master "
                     "(API read 0/blank, Master had a figure)",
                     sheet, col, int(needs_fill.sum()))
    return api_df


def _merge_sheet(
    sheet: str,
    api_df: pd.DataFrame,
    master_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Patch gap columns from master_df into api_df, then recompute GM."""
    if master_df is None or master_df.empty:
        return _recompute_gm(api_df, sheet)

    api_key  = _find_load_key(api_df)
    mstr_key = _find_load_key(master_df)

    if api_key and mstr_key:
        api_cols = set(api_df.columns)
        gap_cols = [c for c in master_df.columns
                    if c != mstr_key and c not in api_cols]
        if gap_cols:
            gap_df = (
                master_df[[mstr_key] + gap_cols]
                .drop_duplicates(subset=[mstr_key])
                .rename(columns={mstr_key: api_key})
            )
            api_df = api_df.merge(gap_df, on=api_key, how="left")
            log.info("  %-20s  patched %d gap col(s): %s",
                     sheet, len(gap_cols), gap_cols)
        else:
            log.info("  %-20s  API covers all Master cols — no gaps", sheet)
        api_df = _value_fill(sheet, api_df, master_df, api_key, mstr_key)
    else:
        log.info("  %-20s  no Load # column — skipping gap-fill", sheet)

    return _recompute_gm(api_df, sheet)


def build_combined(
    pipeline_bytes: bytes,
    master_bytes: bytes,
) -> dict[str, pd.DataFrame]:
    pipeline_sheets = pd.read_excel(
        io.BytesIO(pipeline_bytes), sheet_name=None, engine="openpyxl"
    )
    master_sheets = pd.read_excel(
        io.BytesIO(master_bytes), sheet_name=None, engine="openpyxl"
    )

    log.info("Pipeline sheets : %s", list(pipeline_sheets))
    log.info("Master 2026 sheets: %s", list(master_sheets))

    combined: dict[str, pd.DataFrame] = {}

    for sheet, api_df in pipeline_sheets.items():
        combined[sheet] = _merge_sheet(sheet, api_df, master_sheets.get(sheet))

    # Include any sheets that exist only in master (e.g. manual reference tabs)
    for sheet, master_df in master_sheets.items():
        if sheet not in pipeline_sheets:
            log.info("  %-20s  master-only — included as-is", sheet)
            combined[sheet] = master_df

    return combined


def _download_master(token: str, upn: str) -> bytes | None:
    """Download Alvys Master2026.xlsx — share URL first, path fallback."""
    share_url = os.environ.get("ALVYS_MASTER_SHARE_URL", _ALVYS_MASTER_SHARE_URL).strip()
    master_path = os.environ.get("ALVYS_MASTER_PATH", "Alvys Master2026.xlsx")

    if share_url:
        try:
            data = download_shared_file(token, share_url)
            log.info("Downloaded Master 2026 via share URL")
            return data
        except Exception as exc:
            log.warning("Share URL download failed (%s) — falling back to path", exc)

    try:
        data = download_file(token, upn, master_path)
        log.info("Downloaded Master 2026 via path: %s", master_path)
        return data
    except requests.HTTPError as exc:
        log.warning("Master 2026 not found at %s (%s) — combining pipeline only", master_path, exc)
        return None


def main() -> int:
    tenant  = os.environ.get("AZURE_TENANT_ID", "")
    client  = os.environ.get("AZURE_CLIENT_ID", "")
    secret  = os.environ.get("AZURE_CLIENT_SECRET", "")
    upn     = os.environ.get("ONEDRIVE_USER_UPN", "jeff@xfreight.net")

    pipeline_path   = os.environ.get("ALVYS_PIPELINE_PATH",     "Alvys Pipeline.xlsx")
    combined_name   = os.environ.get("COMBINED_MASTER_FILENAME", "XFreight Master.xlsx")
    combined_folder = os.environ.get("COMBINED_MASTER_FOLDER",  "")

    if not all([tenant, client, secret]):
        log.error("Missing Azure credentials — AZURE_TENANT_ID / CLIENT_ID / CLIENT_SECRET required")
        return 1

    log.info("=" * 60)
    log.info("Building combined master: %s", combined_name)
    log.info("  Pipeline : %s", pipeline_path)
    log.info("=" * 60)

    token = get_token(tenant, client, secret)

    log.info("Downloading %s …", pipeline_path)
    try:
        pipeline_bytes = download_file(token, upn, pipeline_path)
    except requests.HTTPError as exc:
        log.error("Cannot download pipeline file: %s", exc)
        return 1

    master_bytes = _download_master(token, upn)

    if master_bytes:
        combined = build_combined(pipeline_bytes, master_bytes)
    else:
        log.info("No master file — building combined from pipeline only (GM recompute)")
        pipeline_sheets = pd.read_excel(
            io.BytesIO(pipeline_bytes), sheet_name=None, engine="openpyxl"
        )
        combined = {s: _recompute_gm(df, s) for s, df in pipeline_sheets.items()}

    out_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "XFreight_Master.xlsx"

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for sheet_name, df in combined.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

    log.info("Wrote %s (%d sheets, %s bytes)",
             out_path.name, len(combined), f"{out_path.stat().st_size:,}")

    upload_file(token, upn, combined_folder, combined_name, out_path)

    log.info("=" * 60)
    log.info("SUCCESS — %s is live on OneDrive", combined_name)
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
