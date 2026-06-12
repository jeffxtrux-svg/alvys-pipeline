"""Diagnose why the executive brief and Power BI disagree on MTD revenue/cost/margin.

Both read the same Alvys Master2026.xlsx, but they compute differently:

  PBI DAX : revenue = SUM over ALL loads (open loads included, $0 cost)
  Brief   : X-Trux scoped to settled loads only (Driver Rate > 0)

This script computes BOTH styles from the same file and prints the per-entity
difference, plus the specific loads that cause it (open loads carrying revenue,
and cancelled loads — the brief drops cancelled, raw DAX does not).

Run in CI (needs AZURE_* secrets):
    python -m src.diag_brief_vs_pbi
"""
from __future__ import annotations

import io
import logging
import os
import sys

import pandas as pd

from src.onedrive_upload import download_shared_file, get_token

log = logging.getLogger("diag_brief_pbi")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_MASTER_2026_SHARE_URL = (
    "https://xfreightnet-my.sharepoint.com/:x:/g/personal/jeff_xfreight_net/"
    "IQCS8VN_Oxb9S7p2e4lYfePXAetRrCNH351gIGbZ5c53J1U"
)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").fillna(0)
    return pd.Series(0.0, index=df.index)


def _entity(office: str) -> str:
    o = str(office).upper()
    if "LINX" in o:
        return "X-Linx"
    if "TRUX" in o or "FREIGHT" in o:
        return "X-Trux"
    return "Other"


def main() -> int:
    token = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )
    log.info("Downloading Alvys Master2026.xlsx ...")
    raw = download_shared_file(token, os.environ.get(
        "ALVYS_MASTER_SHARE_URL", _MASTER_2026_SHARE_URL))
    log.info("  %s bytes", f"{len(raw):,}")

    loads = pd.read_excel(io.BytesIO(raw), sheet_name="Loads", engine="openpyxl")

    office_col = next((c for c in loads.columns if "office" in c.lower()), None)
    if not office_col:
        log.error("No Office column found")
        return 1

    d = pd.to_datetime(loads.get("Scheduled Pickup"), errors="coerce")
    june = loads[(d >= "2026-06-01") & (d < "2026-07-01")].copy()
    june["__ent"] = june[office_col].map(_entity)
    june["__rev"] = _num(june, "Customer Revenue")
    june["__dr"] = _num(june, "Driver Rate")
    june["__cr"] = _num(june, "Carrier Rate")
    status = june.get("Load Status", pd.Series("", index=june.index)).astype(str).str.lower()
    june["__cancelled"] = status == "cancelled"

    log.info("")
    log.info("June 2026 loads in Master 2026: %d (%d cancelled)",
             len(june), int(june["__cancelled"].sum()))

    for ent in ("X-Trux", "X-Linx"):
        rows = june[(june["__ent"] == ent) & ~june["__cancelled"]]
        cancelled = june[(june["__ent"] == ent) & june["__cancelled"]]

        # PBI DAX style: every load counts; cost = DR (+CR for X-Linx)
        pbi_rev = rows["__rev"].sum()
        pbi_cost = (rows["__dr"] + (rows["__cr"] if ent == "X-Linx" else 0)).sum()
        pbi_margin = pbi_rev - pbi_cost

        # Brief style: X-Trux settled only (DR>0); X-Linx all loads
        if ent == "X-Trux":
            settled = rows[rows["__dr"] > 0]
            brief_rev = settled["__rev"].sum()
            brief_cost = settled["__dr"].sum()
        else:
            brief_rev, brief_cost = pbi_rev, pbi_cost
        brief_margin = brief_rev - brief_cost

        log.info("")
        log.info("=== %s (June, non-cancelled: %d loads) ===", ent, len(rows))
        log.info("  PBI-style  : revenue $%s | cost $%s | margin $%s",
                 f"{pbi_rev:,.2f}", f"{pbi_cost:,.2f}", f"{pbi_margin:,.2f}")
        log.info("  Brief-style: revenue $%s | cost $%s | margin $%s",
                 f"{brief_rev:,.2f}", f"{brief_cost:,.2f}", f"{brief_margin:,.2f}")
        log.info("  DELTA (PBI − brief): revenue $%s | margin $%s",
                 f"{pbi_rev - brief_rev:,.2f}", f"{pbi_margin - brief_margin:,.2f}")

        open_with_rev = rows[(rows["__dr"] == 0) & (rows["__rev"] > 0)]
        if len(open_with_rev):
            log.info("  → %d OPEN loads (DR=0) carry revenue totaling $%s — PBI counts these, brief excludes:",
                     len(open_with_rev), f"{open_with_rev['__rev'].sum():,.2f}")
            for _, r in open_with_rev.sort_values("__rev", ascending=False).head(15).iterrows():
                log.info("      load %-10s rev $%s", str(r.get("Load #", "?")),
                         f"{r['__rev']:,.2f}")
        if len(cancelled) and cancelled["__rev"].sum() > 0:
            log.info("  → %d CANCELLED loads carry revenue $%s — brief drops these; "
                     "if the PBI page has no Load Status filter, PBI counts them too",
                     len(cancelled), f"{cancelled['__rev'].sum():,.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
