"""Daily KPI append — reads the existing OneDrive pipeline files and appends
one row to KPI_History/KPI_Trend.xlsx.

Runs once per day (6:30am CT, after QB / Alvys / Ramp / Recon all finish).
Skips silently if today's row already exists (idempotent).

Columns written:
    Date             YYYY-MM-DD (primary key)
    LoadsMTD         All In-P&L loads month-to-date
    RevenueTotalMTD  X-Trux + X-Linx combined MTD revenue
    RevenueXTruxMTD  X-Trux MTD revenue
    RevenueXLinxMTD  X-Linx MTD revenue
    RPM_OwnFleet     Revenue-per-mile, X-Trux own-fleet only
    DeadheadPct      Dead-head %, X-Trux own-fleet only
    AR_Open          QB total open AR (all companies)
    AR_60Plus        QB open AR 60+ days past due
    AP_GapCount      Ramp bills not yet entered in QB (action items only)
    AP_GapAmount     Dollar value of those bills
    FleetSafetyScore Samsara fleet average safety score

Required env / GitHub Secrets:
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
"""
from __future__ import annotations

import datetime
import io
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.onedrive_upload import (
    download_file as _od_download,
    ensure_folder,
    get_token,
    upload_file,
)
from src.scorecard_email import (
    _safe_read,
    compute_alvys,
    compute_alvys_entities,
    compute_qb_ar_detail,
    compute_samsara,
)

log = logging.getLogger("kpi_append")

_TREND_FOLDER = "KPI_History"
_TREND_FILE   = "KPI_Trend.xlsx"
_TREND_PATH   = f"{_TREND_FOLDER}/{_TREND_FILE}"


# ── KPI extraction ────────────────────────────────────────────────────────────

def _extract_kpis(tok: str, upn: str) -> dict:
    """Download the pipeline outputs and return today's KPI snapshot."""
    today_str = datetime.date.today().isoformat()
    row: dict = {"Date": today_str}
    missing: list[str] = []

    # ── Alvys → loads / revenue / RPM / deadhead ─────────────────────────────
    alvys_path = os.environ.get("ALVYS_PIPELINE_ONEDRIVE_PATH", "Alvys Pipeline.xlsx")
    alvys_sheets = _safe_read(tok, upn, alvys_path, missing, "Alvys Pipeline")
    if alvys_sheets:
        try:
            a = compute_alvys(alvys_sheets)
            if a:
                mtd = a.get("mtd") or {}
                row["LoadsMTD"] = mtd.get("loads")

                # Combined revenue via entity breakdown (X-Trux + X-Linx)
                entities = compute_alvys_entities(alvys_sheets, window_key="mtd")
                xtx_rev  = (entities or {}).get("X-Trux",  {}).get("revenue")
                xlx_rev  = (entities or {}).get("X-Linx",  {}).get("revenue")
                row["RevenueXTruxMTD"]  = xtx_rev
                row["RevenueXLinxMTD"]  = xlx_rev
                row["RevenueTotalMTD"]  = (
                    (xtx_rev or 0) + (xlx_rev or 0) or None
                )

                # Own-fleet (X-Trux, non-brokered) RPM + deadhead
                asset_mtd = (a.get("asset") or {}).get("mtd") or {}
                row["RPM_OwnFleet"]  = asset_mtd.get("rpm")
                dh = asset_mtd.get("deadhead")
                row["DeadheadPct"]   = round(dh * 100, 2) if dh is not None else None
        except Exception as exc:
            log.warning("Alvys KPI extraction failed: %s", exc)

    # ── QuickBooks AR → total open + 60+ bucket ───────────────────────────────
    qb_ar_path = os.environ.get("QB_AR_ONEDRIVE_PATH",
                                "QuickBooks/QB_AgedReceivableDetail.xlsx")
    qb_ar_sheets = _safe_read(tok, upn, qb_ar_path, missing, "QB AR aging")
    if qb_ar_sheets:
        try:
            # Combine all company sheets
            frames = [df for df in qb_ar_sheets.values()
                      if df is not None and not df.empty]
            if frames:
                combined = pd.concat(frames, ignore_index=True)
                ar = compute_qb_ar_detail(combined)
                row["AR_Open"]   = ar.get("total_open")
                row["AR_60Plus"] = ar.get("over_60")
        except Exception as exc:
            log.warning("QB AR KPI extraction failed: %s", exc)

    # ── Reconciliation → Ramp AP gap ─────────────────────────────────────────
    try:
        raw = _od_download(tok, upn, "Reconciliation/Recon_Master.xlsx")
        summ = pd.read_excel(io.BytesIO(raw), sheet_name="Summary")
        gap_row = summ[summ["Check"].astype(str).str.contains("NOT in QB", case=False)]
        if not gap_row.empty:
            row["AP_GapCount"]  = int(gap_row.iloc[0].get("Action_Needed", 0) or 0)
            amt_str = str(gap_row.iloc[0].get("Dollar_Amount", "") or "")
            row["AP_GapAmount"] = float(amt_str.replace("$", "").replace(",", "")) \
                if amt_str.startswith("$") else None
    except Exception as exc:
        log.info("Recon_Master not available (run accounting_recon first): %s", exc)

    # ── Samsara → fleet safety score ─────────────────────────────────────────
    samsara_path = os.environ.get("SAMSARA_ONEDRIVE_PATH",
                                  "Samsara/Samsara_Master.xlsx")
    samsara_sheets = _safe_read(tok, upn, samsara_path, missing, "Samsara")
    if samsara_sheets:
        try:
            sam = compute_samsara(samsara_sheets)
            fleet_score = (sam or {}).get("fleet", {}).get("fleet_score")
            row["FleetSafetyScore"] = round(float(fleet_score), 1) \
                if fleet_score is not None else None
        except Exception as exc:
            log.warning("Samsara KPI extraction failed: %s", exc)

    if missing:
        log.info("Sources not available (columns will be blank): %s", ", ".join(missing))
    return row


# ── trend file management ─────────────────────────────────────────────────────

_COLUMNS = [
    "Date", "LoadsMTD", "RevenueTotalMTD", "RevenueXTruxMTD", "RevenueXLinxMTD",
    "RPM_OwnFleet", "DeadheadPct", "AR_Open", "AR_60Plus",
    "AP_GapCount", "AP_GapAmount", "FleetSafetyScore",
]


def _load_trend(tok: str, upn: str) -> pd.DataFrame:
    try:
        raw = _od_download(tok, upn, _TREND_PATH)
        df = pd.read_excel(io.BytesIO(raw))
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        return df
    except Exception:
        log.info("KPI_Trend.xlsx not found — creating fresh.")
        return pd.DataFrame(columns=_COLUMNS)


def _append_row(df: pd.DataFrame, row: dict) -> tuple[pd.DataFrame, bool]:
    today = row["Date"]
    if today in df["Date"].values:
        log.info("Today's row (%s) already present — skipping.", today)
        return df, False
    new_row = pd.DataFrame([{c: row.get(c) for c in _COLUMNS}])
    df = pd.concat([df, new_row], ignore_index=True)
    df.sort_values("Date", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df, True


def _save_trend(df: pd.DataFrame, tok: str, upn: str) -> None:
    out = Path("output/kpi/KPI_Trend.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out, index=False)
    ensure_folder(tok, upn, _TREND_FOLDER)
    upload_file(tok, upn, _TREND_FOLDER, _TREND_FILE, out)
    log.info("Uploaded %s (%d rows)", _TREND_PATH, len(df))


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    for var in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET",
                "ONEDRIVE_USER_UPN"):
        if not os.environ.get(var):
            log.error("Missing required env var: %s", var)
            sys.exit(1)

    tok = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )
    upn = os.environ["ONEDRIVE_USER_UPN"]

    log.info("Extracting today's KPIs…")
    row = _extract_kpis(tok, upn)
    log.info("  KPIs: %s", {k: v for k, v in row.items() if v is not None})

    trend = _load_trend(tok, upn)
    trend, written = _append_row(trend, row)
    if written:
        _save_trend(trend, tok, upn)
    log.info("Done.")


if __name__ == "__main__":
    main()
