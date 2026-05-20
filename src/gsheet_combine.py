"""Combine OneDrive reports into a single Google Sheet for KPI tracking.

Reads every .xlsx in three OneDrive locations:
  * root      — Alvys Master 2026.xlsx (Loads, Trips, Fuel)
  * /QuickBooks — QB_*.xlsx per report type, stacked across all companies
  * /Samsara  — Samsara Master.xlsx (Vehicles, Drivers, Trips, SafetyEvents, …)

Pushes one tab per (source workbook × sheet) into a single Google Sheet, then
rebuilds a `Dashboard` tab whose formulas roll those tabs up into lead-indicator
KPIs. A `_Meta` tab records the refresh timestamp and per-tab row counts.

First run: if GOOGLE_SHEET_ID is unset, a new sheet is created and its ID is
printed in the workflow log. Paste that ID into the GOOGLE_SHEET_ID repo
variable and re-run — subsequent runs reuse the same sheet.

Env vars:
    AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET  — Graph (shared)
    ONEDRIVE_USER_UPN                                      — e.g. jeff@xfreight.net
    GOOGLE_SERVICE_ACCOUNT_JSON                            — full JSON key content
    GOOGLE_SHEET_ID                                        — empty on first run
    GOOGLE_SHARE_WITH                                      — email to share new sheet with
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from .onedrive_download import download_file, list_folder
from .onedrive_upload import get_token

log = logging.getLogger("gsheet_combine")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ONEDRIVE_SOURCES = [
    ("", "Alvys"),
    ("QuickBooks", "QB"),
    ("Samsara", "Samsara"),
]

MAX_TAB_NAME = 80   # Google Sheets allows 100; leave headroom for prefix collisions
MAX_ROWS_PER_TAB = 50_000


# ---------------------------------------------------------------------------
# OneDrive → local xlsx files
# ---------------------------------------------------------------------------

def collect_xlsx_files(token: str, user_upn: str, work_dir: Path) -> list[tuple[str, Path]]:
    """Download every .xlsx from the configured OneDrive folders.

    Returns a list of (source_prefix, local_path) tuples.
    """
    downloads: list[tuple[str, Path]] = []
    for folder_path, prefix in ONEDRIVE_SOURCES:
        log.info("Listing OneDrive folder: /%s", folder_path or "(root)")
        items = list_folder(token, user_upn, folder_path)
        xlsx_items = [
            it for it in items
            if it.get("file") and it.get("name", "").lower().endswith(".xlsx")
        ]
        # For the root folder we only want the Alvys Master file — pulling every
        # xlsx in the user's OneDrive root would be noisy and unrelated.
        if folder_path == "":
            xlsx_items = [
                it for it in xlsx_items
                if "alvys" in it.get("name", "").lower() and "master" in it.get("name", "").lower()
            ]
        log.info("  Found %d .xlsx files", len(xlsx_items))
        for item in xlsx_items:
            name = item["name"]
            dest = work_dir / (folder_path or "root") / name
            log.info("  Downloading: %s/%s", folder_path or "(root)", name)
            download_file(token, user_upn, item["id"], dest)
            downloads.append((prefix, dest))
    return downloads


# ---------------------------------------------------------------------------
# xlsx → DataFrames keyed by tab name
# ---------------------------------------------------------------------------

_TAB_SAFE = re.compile(r"[\[\]\*\?:/\\]")


def make_tab_name(prefix: str, workbook_name: str, sheet_name: str) -> str:
    """Construct a stable Google Sheets tab name.

    Goals:
      * Same tab name whether Alvys file is "Alvys Master.xlsx" or "Alvys Master 2026.xlsx".
      * Drop the boilerplate "Sheet1" suffix on QB single-sheet workbooks.
      * No spaces (Sheets formulas don't need quoting when names are plain).
    """
    workbook_stem = Path(workbook_name).stem
    sheet_norm = sheet_name.strip()

    if sheet_norm.lower() in ("sheet1", "sheet"):
        base = workbook_stem
    else:
        stem_compact = re.sub(r"[\s_]+", "", workbook_stem).lower()
        if stem_compact.startswith(prefix.lower()):
            # Workbook already self-identifies (e.g. "Alvys Master.xlsx") — collapse it.
            base = f"{prefix}_{sheet_norm}"
        else:
            base = f"{prefix}_{workbook_stem}_{sheet_norm}"

    cleaned = _TAB_SAFE.sub(" ", base)
    cleaned = re.sub(r"\s+", "_", cleaned).strip("_")
    return cleaned[:MAX_TAB_NAME]


def read_workbook(prefix: str, path: Path) -> dict[str, pd.DataFrame]:
    """Read every sheet of an xlsx into DataFrames keyed by final tab name."""
    log.info("  Reading %s", path.name)
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:
        log.error("  Failed to open %s: %s", path.name, exc)
        return {}
    out: dict[str, pd.DataFrame] = {}
    for sheet in xl.sheet_names:
        df = xl.parse(sheet, dtype=object)
        df = df.where(pd.notna(df), "")
        if len(df) > MAX_ROWS_PER_TAB:
            log.warning("    Truncating %s/%s from %d to %d rows",
                        path.name, sheet, len(df), MAX_ROWS_PER_TAB)
            df = df.head(MAX_ROWS_PER_TAB)
        tab_name = make_tab_name(prefix, path.name, sheet)
        out[tab_name] = df
        log.info("    %s → %s (%d rows × %d cols)", sheet, tab_name, len(df), len(df.columns))
    return out


def collect_all_dataframes(downloads: list[tuple[str, Path]]) -> dict[str, pd.DataFrame]:
    """Aggregate sheets across all downloaded workbooks, de-duplicating tab names."""
    combined: dict[str, pd.DataFrame] = {}
    for prefix, path in downloads:
        for tab, df in read_workbook(prefix, path).items():
            tab_final = tab
            suffix = 2
            while tab_final in combined:
                tab_final = f"{tab[: MAX_TAB_NAME - 3]}_{suffix}"
                suffix += 1
            combined[tab_final] = df
    return combined


# ---------------------------------------------------------------------------
# Google Sheets push
# ---------------------------------------------------------------------------

def open_or_create_sheet(gc: gspread.Client, sheet_id: str, share_with: str) -> gspread.Spreadsheet:
    if sheet_id:
        return gc.open_by_key(sheet_id)
    log.warning("GOOGLE_SHEET_ID is empty — creating a new spreadsheet")
    sh = gc.create("X-Freight KPI Dashboard")
    if share_with:
        sh.share(share_with, perm_type="user", role="writer", notify=True)
        log.info("Shared new sheet with %s", share_with)
    log.warning("=" * 70)
    log.warning("NEW SHEET CREATED")
    log.warning("  ID:  %s", sh.id)
    log.warning("  URL: %s", sh.url)
    log.warning("Paste the ID into the GOOGLE_SHEET_ID repo variable, then re-run.")
    log.warning("=" * 70)
    return sh


def _df_to_values(df: pd.DataFrame) -> list[list]:
    """Convert DataFrame to a 2D list of JSON-serializable cell values."""
    if df.empty:
        return [list(df.columns)] if len(df.columns) else [["(no data)"]]
    header = [str(c) for c in df.columns]
    body = df.astype(object).where(pd.notna(df), "").values.tolist()
    cleaned: list[list] = []
    for row in body:
        cleaned.append([
            "" if v is None else (v if isinstance(v, (int, float, bool, str)) else str(v))
            for v in row
        ])
    return [header] + cleaned


def push_tabs(sh: gspread.Spreadsheet, tabs: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Write each DataFrame to its tab. Returns map of tab → row count."""
    existing = {ws.title: ws for ws in sh.worksheets()}
    row_counts: dict[str, int] = {}

    # Sheets requires at least one worksheet — keep "Sheet1" alive as a scratch
    # tab until we've added something, then delete it at the end.
    scratch = existing.get("Sheet1")

    for tab_name, df in tabs.items():
        values = _df_to_values(df)
        rows = max(len(values), 1)
        cols = max(len(values[0]) if values else 1, 1)

        if tab_name in existing:
            ws = existing[tab_name]
            ws.clear()
            ws.resize(rows=rows, cols=cols)
        else:
            ws = sh.add_worksheet(title=tab_name, rows=rows, cols=cols)
            existing[tab_name] = ws

        end_a1 = rowcol_to_a1(rows, cols)
        ws.update(values=values, range_name=f"A1:{end_a1}", value_input_option="RAW")
        row_counts[tab_name] = len(df)
        log.info("  Pushed %-50s %d rows × %d cols", tab_name, len(df), len(df.columns))
        time.sleep(0.4)  # gentle pacing for Sheets API quota (60 writes/min/user)

    if scratch is not None and len(existing) > 1 and scratch.title not in tabs:
        try:
            sh.del_worksheet(scratch)
        except Exception:
            pass

    return row_counts


# ---------------------------------------------------------------------------
# Dashboard tab
# ---------------------------------------------------------------------------

# Each KPI references one of the raw tabs. Formulas are resilient: IFERROR wraps
# everything so a missing tab or column shows "—" instead of breaking the sheet.
# Edit this list to add/remove KPIs without touching the rest of the module.
# Starter KPIs — intentionally formula-light (row counts + simple lookups) so they
# never break when columns shift. Once you confirm which source columns hold the
# numbers you care about (revenue, miles, customer name, status, etc.), swap these
# COUNTAs for SUMIF / RPM / margin formulas pointed at the right column letters.
DASHBOARD_KPIS: list[tuple[str, str, str]] = [
    # (Section, Label, Formula)
    ("Financial",  "QB P&L rows (all companies, YTD)",
        '=IFERROR(COUNTA(QB_ProfitAndLoss!A2:A), "—")'),
    ("Financial",  "QB Balance Sheet rows",
        '=IFERROR(COUNTA(QB_BalanceSheet!A2:A), "—")'),
    ("Financial",  "QB Cash Flow rows",
        '=IFERROR(COUNTA(QB_CashFlow!A2:A), "—")'),
    ("Financial",  "AR aging detail rows",
        '=IFERROR(COUNTA(QB_AgedReceivableDetail!A2:A), "—")'),
    ("Financial",  "AP aging detail rows",
        '=IFERROR(COUNTA(QB_AgedPayableDetail!A2:A), "—")'),
    ("Financial",  "Customers (all companies)",
        '=IFERROR(COUNTA(QB_Customers!A2:A), "—")'),
    ("Financial",  "Vendors (all companies)",
        '=IFERROR(COUNTA(QB_Vendors!A2:A), "—")'),

    ("Operations", "Total loads (Alvys, since start date)",
        '=IFERROR(COUNTA(Alvys_Loads!A2:A), "—")'),
    ("Operations", "Total trips (Alvys)",
        '=IFERROR(COUNTA(Alvys_Trips!A2:A), "—")'),
    ("Operations", "Fuel transactions (Alvys)",
        '=IFERROR(COUNTA(Alvys_Fuel!A2:A), "—")'),

    ("Safety",     "Samsara safety events (last %d days)" % 90,
        '=IFERROR(COUNTA(Samsara_SafetyEvents!A2:A), "—")'),
    ("Safety",     "Samsara DVIR submissions",
        '=IFERROR(COUNTA(Samsara_DVIRs!A2:A), "—")'),
    ("Safety",     "HOS log entries (30d)",
        '=IFERROR(COUNTA(Samsara_HOS_Logs!A2:A), "—")'),
    ("Safety",     "Active vehicles tracked",
        '=IFERROR(COUNTA(Samsara_Vehicles!A2:A), "—")'),
    ("Safety",     "Active drivers tracked",
        '=IFERROR(COUNTA(Samsara_Drivers!A2:A), "—")'),
    ("Safety",     "Recent Samsara trips",
        '=IFERROR(COUNTA(Samsara_Trips!A2:A), "—")'),
]


def build_dashboard_values(refresh_ts: str) -> list[list]:
    values: list[list] = [
        ["X-Freight KPI Dashboard"],
        [f"Last refreshed: {refresh_ts}"],
        ["Tabs prefixed Alvys_ / QB_ / Samsara_ hold the raw data. Edit"
         " src/gsheet_combine.py DASHBOARD_KPIS to add formulas."],
        [],
        ["Section", "KPI", "Value"],
    ]
    current_section = None
    for section, label, formula in DASHBOARD_KPIS:
        section_cell = section if section != current_section else ""
        current_section = section
        values.append([section_cell, label, formula])
    return values


def push_dashboard(sh: gspread.Spreadsheet, refresh_ts: str) -> None:
    values = build_dashboard_values(refresh_ts)
    rows = len(values)
    cols = max(len(r) for r in values)
    try:
        ws = sh.worksheet("Dashboard")
        ws.clear()
        ws.resize(rows=rows, cols=cols)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="Dashboard", rows=rows, cols=cols)
    end_a1 = rowcol_to_a1(rows, cols)
    ws.update(values=values, range_name=f"A1:{end_a1}", value_input_option="USER_ENTERED")

    # Reorder Dashboard to be the first tab for visibility.
    try:
        sh.reorder_worksheets([ws] + [w for w in sh.worksheets() if w.id != ws.id])
    except Exception as exc:
        log.warning("Could not reorder worksheets: %s", exc)


def push_meta(sh: gspread.Spreadsheet, refresh_ts: str, row_counts: dict[str, int]) -> None:
    rows = [["tab", "rows"]] + [[t, n] for t, n in sorted(row_counts.items())]
    rows.append([])
    rows.append(["last_refresh_cst", refresh_ts])
    try:
        ws = sh.worksheet("_Meta")
        ws.clear()
        ws.resize(rows=len(rows), cols=2)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="_Meta", rows=len(rows), cols=2)
    end_a1 = rowcol_to_a1(len(rows), 2)
    ws.update(values=rows, range_name=f"A1:{end_a1}", value_input_option="RAW")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _required(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        log.error("Missing required env var: %s", key)
        sys.exit(1)
    return val


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    tenant_id = _required("AZURE_TENANT_ID")
    client_id = _required("AZURE_CLIENT_ID")
    client_secret = _required("AZURE_CLIENT_SECRET")
    user_upn = _required("ONEDRIVE_USER_UPN")
    sa_json = _required("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
    share_with = os.environ.get("GOOGLE_SHARE_WITH", "").strip()

    log.info("=" * 70)
    log.info("OneDrive → Google Sheet combiner")
    log.info("=" * 70)

    log.info("Authenticating to Microsoft Graph…")
    graph_token = get_token(tenant_id, client_id, client_secret)

    log.info("Authenticating to Google Sheets…")
    creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=SCOPES)
    gc = gspread.authorize(creds)

    with tempfile.TemporaryDirectory(prefix="gsheet_combine_") as tmp:
        work_dir = Path(tmp)

        log.info("-" * 70)
        log.info("Step 1/4: Downloading xlsx files from OneDrive")
        log.info("-" * 70)
        downloads = collect_xlsx_files(graph_token, user_upn, work_dir)
        if not downloads:
            log.error("No .xlsx files found in any OneDrive source folder. Aborting.")
            sys.exit(1)

        log.info("-" * 70)
        log.info("Step 2/4: Reading sheets into DataFrames")
        log.info("-" * 70)
        tabs = collect_all_dataframes(downloads)
        log.info("Will push %d tabs to Google Sheets", len(tabs))

        log.info("-" * 70)
        log.info("Step 3/4: Opening Google Sheet")
        log.info("-" * 70)
        sh = open_or_create_sheet(gc, sheet_id, share_with)
        log.info("  Title: %s", sh.title)
        log.info("  URL:   %s", sh.url)
        if not sheet_id:
            # On first-run bootstrap, exit after creating so user can wire up the ID.
            return

        log.info("-" * 70)
        log.info("Step 4/4: Pushing tabs + Dashboard + _Meta")
        log.info("-" * 70)
        row_counts = push_tabs(sh, tabs)

        refresh_ts = datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d %H:%M %Z")
        push_dashboard(sh, refresh_ts)
        push_meta(sh, refresh_ts, row_counts)

    log.info("=" * 70)
    log.info("✓ Done — %s", sh.url)
    log.info("=" * 70)


if __name__ == "__main__":
    main()
