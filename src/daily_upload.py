"""Daily MTD load report — replicates the manually-maintained
``Daily_Upload_MMDDYYYY.xlsx`` workbook by reading the Alvys Master 2026
xlsx on OneDrive, filtering to month-to-date, and writing a fresh dated
copy back to OneDrive (with email distribution).

Three tabs, all sharing the same 18-column shape that matches the sample
the user supplied:

  * **All Loads** — every MTD load that wasn't Cancelled.
  * **Customer Loads** — direct customers + no-customer rows (deadhead /
    repositioning legs that belong to the X-Trux operation).
  * **Spot Market** — broker freight (everything else).

Date filter is **first of the current calendar month → today** based on
the Scheduled Pickup column (matches PBI's monthly bucket).

Open-load empty-mileage estimate: if a load's Load Status isn't
``Completed`` or ``Invoiced`` and its Empty Dispatch Mileage column is
0/blank, substitute **65 miles** as a reasonable estimate. The figure is
the historical deadhead average for the X-Trux network and was the user's
explicit ask so the report reads as a fair MTD snapshot even when
in-flight loads haven't been fully accounted yet.

Reuses the same Microsoft Graph helpers (``get_token``,
``download_shared_file``, ``upload_file``) the scorecard uses — single
Azure app, one auth path. The send-email path comes from
``src.scorecard_email.send_email`` for the same reason.
"""
from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from src.onedrive_upload import (
    download_shared_file, ensure_folder, get_token, upload_file,
)
from src.scorecard_email import send_email

log = logging.getLogger("daily_upload")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

CHI_TZ = ZoneInfo("America/Chicago")
OPEN_EMPTY_ESTIMATE_MI = 65
SETTLED_STATUSES = {"completed", "invoiced"}

# Output column order — exactly matches the sample workbook so downstream
# Power BI / Excel pivots that the user has authored against the existing
# file shape keep working without touching them.
OUTPUT_COLS = [
    "Count", "Customer Sales Agent", "Load #", "Load Status", "Carrier",
    "Customer", "Pick City", "Pick State", "First Pick Status",
    "Drop City", "Drop State", "Last Drop Status",
    "Empty Dispatch Mileage", "Loaded Dispatch Mileage",
    "Customer Revenue", "Driver Rate", "Margin", "Margin %",
]


def _find_col(df: pd.DataFrame, needles: list[str]) -> str | None:
    """First column whose lowercased name contains any of the needle substrings."""
    for needle in needles:
        for c in df.columns:
            if needle in str(c).lower():
                return c
    return None


def _pick_source_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """First column that exactly matches (case-insensitive) any candidate."""
    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    for c in candidates:
        if c.strip().lower() in cols_lower:
            return cols_lower[c.strip().lower()]
    return None


def _resolve_columns(loads: pd.DataFrame) -> dict[str, str | None]:
    """Map each output column to whichever source column carries it. Returns
    a dict of output_name -> source_column_name (or None if not present)."""
    # Exact-match candidates per output column. Order matters — first hit
    # wins, so the most-faithful names are listed first.
    mapping_candidates = {
        "Customer Sales Agent": ["Customer Sales Agent", "Sales Agent",
                                  "Salesperson", "Sales Rep", "Account Rep"],
        "Load #":               ["Load #", "Load Number", "Load Num", "Load"],
        "Load Status":          ["Load Status", "Status"],
        "Carrier":              ["Carrier", "Carrier Name"],
        "Customer":             ["Customer", "Customer Name"],
        "Pick City":            ["Pick City", "Pickup City", "First Pick City",
                                  "Origin City"],
        "Pick State":           ["Pick State", "Pickup State", "First Pick State",
                                  "Origin State"],
        "First Pick Status":    ["First Pick Status", "Pickup Status",
                                  "Pick Status"],
        "Drop City":            ["Drop City", "Delivery City", "Last Drop City",
                                  "Destination City"],
        "Drop State":           ["Drop State", "Delivery State",
                                  "Last Drop State", "Destination State"],
        "Last Drop Status":     ["Last Drop Status", "Delivery Status",
                                  "Drop Status"],
        "Empty Dispatch Mileage":  ["Empty Dispatch Mileage", "Empty Mileage",
                                     "Empty Miles", "Dead Head Miles", "DH Miles"],
        "Loaded Dispatch Mileage": ["Loaded Dispatch Mileage", "Loaded Mileage",
                                     "Loaded Miles"],
        "Customer Revenue":     ["Customer Revenue", "Revenue", "Total Revenue"],
        "Driver Rate":          ["Driver Rate", "Carrier Rate", "Driver Pay"],
    }
    resolved = {}
    for out_col, candidates in mapping_candidates.items():
        resolved[out_col] = _pick_source_col(loads, candidates)
        if resolved[out_col] is None:
            log.warning("Source column for %r not found — output will be blank.", out_col)
    return resolved


def _to_naive_dt(series: pd.Series) -> pd.Series:
    d = pd.to_datetime(series, errors="coerce", utc=True)
    try:
        return d.dt.tz_localize(None)
    except (AttributeError, TypeError):
        return pd.to_datetime(series, errors="coerce")


# Inline copies of the direct-customer heuristic — kept here instead of
# importing from scorecard_email so the daily-upload module stays
# independent of the scorecard's render pipeline.
DIRECT_CUSTOMERS = {
    "berry plastics", "rainbow play", "ascendant", "graham packaging",
    "lewis drug", "viaflex", "billion auto", "billion automotive",
    "dakota potter", "dakota potters", "innovative office",
    "magnum logistics inc - nd", "magnum logistics", "agco",
    "frontier ag", "frontier coop", "sun opta", "sunopta",
    "fortune logistics", "twin cities logistics", "twin city logistics",
    "moc products", "valley queen", "valley queen cheese",
}


def _is_direct_customer(name) -> bool:
    n = str(name).strip().lower()
    if not n or n == "nan":
        return False
    segments = [s.strip() for s in n.split("/")]
    return any(seg.startswith(kw) for seg in segments for kw in DIRECT_CUSTOMERS)


def _is_no_customer(name) -> bool:
    n = str(name).strip().lower()
    return n in ("", "nan", "none")


def _build_normalized(loads: pd.DataFrame, today_chi: pd.Timestamp) -> pd.DataFrame:
    """Apply the MTD filter, the open-load empty-estimate rule, and return
    a DataFrame in OUTPUT_COLS order (without the Count column — added per
    tab after splitting)."""
    cols = _resolve_columns(loads)

    # Date filter — Scheduled Pickup is the canonical column on Alvys Master
    # 2026. Fall back to the same set the scorecard probes so the script is
    # robust to header drift.
    date_col = _find_col(loads, ["scheduled pickup", "pickup date", "scheduled pickup"])
    if not date_col:
        raise RuntimeError("No date column found in Loads sheet (looked for "
                            "'Scheduled Pickup' / 'pickup date').")
    sub = loads.copy()
    dates = _to_naive_dt(sub[date_col])
    mtd_start = pd.Timestamp(today_chi.year, today_chi.month, 1)
    mtd_end   = pd.Timestamp(today_chi.year, today_chi.month, today_chi.day, 23, 59, 59)
    keep = dates.notna() & (dates >= mtd_start) & (dates <= mtd_end)
    sub = sub.loc[keep].copy()
    log.info("Filtered Loads to MTD %s..%s: %d rows",
             mtd_start.date(), mtd_end.date(), len(sub))

    if "Load Status" in sub.columns:
        before = len(sub)
        sub = sub[sub["Load Status"].astype(str).str.strip().str.lower() != "cancelled"]
        log.info("Dropped %d Cancelled loads (%d remaining)", before - len(sub), len(sub))

    out = pd.DataFrame()
    for out_col, src_col in cols.items():
        out[out_col] = sub[src_col].values if src_col else [None] * len(sub)

    # Coerce numerics
    for c in ("Empty Dispatch Mileage", "Loaded Dispatch Mileage",
              "Customer Revenue", "Driver Rate"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

    # Open-load empty-mileage estimate — per user spec, substitute 65 mi when
    # the load is still in-flight and Alvys hasn't yet billed an empty leg.
    status_lower = out["Load Status"].astype(str).str.strip().str.lower()
    is_open = ~status_lower.isin(SETTLED_STATUSES)
    needs_est = is_open & (out["Empty Dispatch Mileage"] <= 0)
    n_est = int(needs_est.sum())
    out.loc[needs_est, "Empty Dispatch Mileage"] = OPEN_EMPTY_ESTIMATE_MI
    if n_est:
        log.info("Set Empty Dispatch Mileage = %d mi for %d open loads (estimate)",
                 OPEN_EMPTY_ESTIMATE_MI, n_est)

    # Computed columns
    out["Margin"] = out["Customer Revenue"] - out["Driver Rate"]
    out["Margin %"] = (out["Margin"] / out["Customer Revenue"]).where(out["Customer Revenue"] != 0)

    return out


def _split_tabs(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Three tabs matching the sample workbook layout."""
    is_no_cust = df["Customer"].apply(_is_no_customer)
    is_direct  = df["Customer"].apply(_is_direct_customer)
    customer_mask = is_no_cust | is_direct
    spot_mask     = ~customer_mask

    tabs = {
        "All Loads":      df.copy(),
        "Customer Loads": df.loc[customer_mask].copy(),
        "Spot Market":    df.loc[spot_mask].copy(),
    }
    for name, t in tabs.items():
        # The sample numbers rows 1..N per tab in the Count column.
        t.insert(0, "Count", range(1, len(t) + 1))
        # Re-order to the exact sample shape just in case.
        tabs[name] = t[OUTPUT_COLS]
        log.info("Tab %r: %d rows", name, len(t))
    return tabs


def _write_xlsx(tabs: dict[str, pd.DataFrame], file_path: Path) -> None:
    """Write the three tabs to xlsx. Number formats match the sample
    (currency on Margin/Revenue/Rate, % on Margin %)."""
    with pd.ExcelWriter(file_path, engine="openpyxl") as xw:
        for name, df in tabs.items():
            df.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            # Apply column number formats. Headers are row 1; data starts row 2.
            from openpyxl.utils import get_column_letter
            col_idx = {c: i + 1 for i, c in enumerate(df.columns)}
            for c in ("Customer Revenue", "Driver Rate", "Margin"):
                if c in col_idx:
                    letter = get_column_letter(col_idx[c])
                    for cell in ws[letter][1:]:
                        cell.number_format = '"$"#,##0.00'
            if "Margin %" in col_idx:
                letter = get_column_letter(col_idx["Margin %"])
                for cell in ws[letter][1:]:
                    cell.number_format = "0.00%"
            for c in ("Empty Dispatch Mileage", "Loaded Dispatch Mileage", "Count"):
                if c in col_idx:
                    letter = get_column_letter(col_idx[c])
                    for cell in ws[letter][1:]:
                        cell.number_format = "#,##0"
    log.info("Wrote %s", file_path)


def _summary_html(tabs: dict[str, pd.DataFrame], file_label: str) -> str:
    """Two-line email body — a quick MTD snapshot above the attachment."""
    parts = ['<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;'
              'font-size:14px;color:#1a1a1a;line-height:1.5;padding:24px;max-width:560px">']
    parts.append('<div style="font-weight:700;letter-spacing:1.5px;font-size:11px;'
                  'color:#c41e2a;text-transform:uppercase;margin-bottom:14px">'
                  'XFreight · Daily MTD Upload</div>')
    parts.append(f"<p style='margin:0 0 12px'>Attached: <b>{file_label}</b> &mdash; "
                  "month-to-date load list refreshed for this morning.</p>")
    parts.append("<table cellpadding='6' cellspacing='0' style='border-collapse:collapse;"
                  "border:1px solid #ececec;border-radius:6px;font-size:12.5px;margin:6px 0 16px'>"
                  "<tr style='background:#fafafa;color:#6b6b6b;text-transform:uppercase;"
                  "font-size:10px;letter-spacing:.4px;font-weight:700;'>"
                  "<td>Tab</td><td align='right'>Loads</td>"
                  "<td align='right'>Revenue</td><td align='right'>Margin</td>"
                  "<td align='right'>Margin %</td></tr>")
    for name, df in tabs.items():
        rev = float(df["Customer Revenue"].sum() or 0)
        mgn = float(df["Margin"].sum() or 0)
        pct = (mgn / rev) if rev else 0
        parts.append(
            f"<tr><td style='border-top:1px solid #ececec'>{name}</td>"
            f"<td align='right' style='border-top:1px solid #ececec'>{len(df):,}</td>"
            f"<td align='right' style='border-top:1px solid #ececec'>${rev:,.0f}</td>"
            f"<td align='right' style='border-top:1px solid #ececec'>${mgn:,.0f}</td>"
            f"<td align='right' style='border-top:1px solid #ececec'>{pct*100:.1f}%</td></tr>"
        )
    parts.append("</table>")
    parts.append('<p style="margin:0;color:#6b6b6b;font-size:12px">'
                  f"Open loads with no empty mileage on file get a "
                  f"{OPEN_EMPTY_ESTIMATE_MI}-mi estimate. Source: "
                  "<i>Alvys Master 2026.xlsx</i> in OneDrive.</p>")
    parts.append("</div>")
    return "".join(parts)


def main() -> int:
    tenant = os.environ["AZURE_TENANT_ID"]
    client = os.environ["AZURE_CLIENT_ID"]
    secret = os.environ["AZURE_CLIENT_SECRET"]
    upn    = os.environ.get("ONEDRIVE_USER_UPN", "jeff@xfreight.net")
    share  = os.environ.get("DAILY_UPLOAD_ALVYS_SHARE_URL", "").strip()
    if not share:
        raise SystemExit("DAILY_UPLOAD_ALVYS_SHARE_URL is required "
                          "(use the same share URL as the scorecard).")
    out_folder = os.environ.get("DAILY_UPLOAD_FOLDER", "").strip("/")
    to_emails = [e.strip()
                 for e in os.environ.get("DAILY_UPLOAD_TO_EMAILS",
                                          "jeff@xfreight.net").split(",")
                 if e.strip()]

    token = get_token(tenant, client, secret)
    log.info("Reading Alvys Master 2026 via share URL…")
    workbook_bytes = download_shared_file(token, share)
    sheets = pd.read_excel(io.BytesIO(workbook_bytes), sheet_name=None)
    loads_key = next((k for k in sheets if k.strip().lower() == "loads"), None)
    if not loads_key:
        raise SystemExit(f"No 'Loads' sheet in workbook (have: {list(sheets)})")
    loads = sheets[loads_key]
    log.info("Loads sheet: %d rows, %d cols", len(loads), loads.shape[1])

    today_chi = pd.Timestamp.now(tz=CHI_TZ).normalize()
    normalized = _build_normalized(loads, today_chi)
    tabs = _split_tabs(normalized)

    file_label = f"Daily_Upload_{today_chi.strftime('%m%d%Y')}.xlsx"
    with tempfile.TemporaryDirectory() as tmp:
        local_path = Path(tmp) / file_label
        _write_xlsx(tabs, local_path)

        # Upload to OneDrive (creates folder if specified)
        if out_folder:
            ensure_folder(token, upn, out_folder)
            log.info("Uploading to OneDrive folder %r as %s …", out_folder, file_label)
        else:
            log.info("Uploading to OneDrive root as %s …", file_label)
        upload_file(token, upn, out_folder, file_label, local_path)

        # Email it with the xlsx attached
        if to_emails:
            with open(local_path, "rb") as fh:
                content_bytes = fh.read()
            send_email(
                token, upn, to_emails,
                f"XFreight Daily MTD Upload — {today_chi.strftime('%b %d, %Y')}",
                _summary_html(tabs, file_label),
                attachments=[{
                    "name": file_label,
                    "content_bytes": content_bytes,
                    "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                }],
            )

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
