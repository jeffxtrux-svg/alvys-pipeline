"""One-off diagnostic: dump every mileage/cost-related column from the
Alvys Master 2026 workbook and show what each sums to for the current month's
X-Trux + XFreight loads. Compares against the Power BI numbers so we can see
which column the scorecard *should* be summing to match the report.

Disposable.
"""
from __future__ import annotations

import io
import logging
import os
import sys

import pandas as pd
from dotenv import load_dotenv

from src.onedrive_upload import download_file, download_shared_file, get_token
from src.scorecard_email import (
    ALVYS_DATE_CANDIDATES,
    OFFICE_COL_NEEDLES,
    _dates,
    _entity_group,
    _find_col,
    send_email,
)

log = logging.getLogger("diag_deadhead")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    load_dotenv()

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    upn = os.environ.get("ONEDRIVE_USER_UPN")
    share_url = os.environ.get("SCORECARD_ALVYS_SHARE_URL", "").strip()
    alvys_path = os.environ.get("SCORECARD_ALVYS_PATH", "Alvys Master 2026.xlsx")
    from_upn = os.environ.get("SCORECARD_FROM_UPN", upn)
    to_emails = [e.strip() for e in os.environ.get("SCORECARD_TO_EMAILS",
                                                    "jeff@xfreight.net").split(",") if e.strip()]
    if not all([tenant, client, secret, upn]):
        sys.exit("ERROR: AZURE_* + ONEDRIVE_USER_UPN required")

    token = get_token(tenant, client, secret)
    raw = (download_shared_file(token, share_url) if share_url
           else download_file(token, upn, alvys_path))
    sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        sys.exit("Loads sheet missing/empty")

    cols = list(loads.columns)
    needles = ("mile", "dispatch", "empty", "loaded")
    relevant = [c for c in cols if any(n in str(c).lower() for n in needles)]

    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    groups = loads[office_col].map(_entity_group) if office_col else None

    now = pd.Timestamp.now()
    mtd_start = now.normalize().replace(day=1)
    not_cancelled = (loads["Load Status"].astype(str).str.lower() != "cancelled"
                     if "Load Status" in loads.columns else pd.Series(True, index=loads.index))

    asset_mask = (groups == "X-Trux") if groups is not None else pd.Series(True, index=loads.index)
    mtd_mask = (dates >= mtd_start) & asset_mask
    mtd_mask_nc = mtd_mask & not_cancelled

    sub_all = loads[mtd_mask]
    sub_nc = loads[mtd_mask_nc]

    lines: list[str] = []
    lines.append("Deadhead diagnostic — Alvys Master 2026, May 2026 X-Trux + XFreight")
    lines.append("=" * 72)
    lines.append(f"As-of:                {now:%Y-%m-%d %H:%M}")
    lines.append(f"Office column:        {office_col!r}")
    lines.append(f"Date column used:     (auto from candidates)")
    lines.append(f"MTD window:           {mtd_start:%Y-%m-%d} to now")
    lines.append(f"Asset (X-Trux+XFreight) loads in MTD, ALL statuses:        {len(sub_all):,}")
    lines.append(f"Asset (X-Trux+XFreight) loads in MTD, EXCLUDING cancelled: {len(sub_nc):,}")
    lines.append("")
    lines.append("All mileage-related columns and their MTD sums:")
    lines.append(f"  {'column':45s} {'ALL':>14} {'NOT-CANCELLED':>16}")
    for c in relevant:
        all_sum = pd.to_numeric(sub_all[c], errors="coerce").sum()
        nc_sum = pd.to_numeric(sub_nc[c], errors="coerce").sum()
        lines.append(f"  {str(c)[:45]:45s} {all_sum:>14,.1f} {nc_sum:>16,.1f}")

    lines.append("")
    lines.append("Power BI table reference (May 2026, X-Trux + XFreight, from screenshot):")
    lines.append("  Dispatch Mileage:  165,717")
    lines.append("  Empty Mileage:      10,253")
    lines.append("  Dead Head %:         6.187%  (= 10,253 / 165,717)")
    lines.append("")
    lines.append("Find which two columns above match those Power BI numbers and we know")
    lines.append("exactly which columns the scorecard needs to sum.")
    lines.append("")
    lines.append("All Load Status values seen this MTD slice:")
    if "Load Status" in loads.columns:
        vc = sub_all["Load Status"].astype(str).value_counts()
        for k, v in vc.items():
            lines.append(f"  {k:30s} {v:>6}")
    lines.append("")
    lines.append("All Office values seen this MTD slice:")
    if office_col:
        vc = sub_all[office_col].astype(str).value_counts()
        for k, v in vc.items():
            lines.append(f"  {k:30s} {v:>6}")

    report = "\n".join(lines)
    log.info("\n%s", report)
    html = "<pre style='font-family:Consolas,Menlo,monospace;font-size:11px;'>" + (
        report.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ) + "</pre>"
    send_email(token, from_upn, to_emails, "Deadhead diagnostic — May 2026", html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
