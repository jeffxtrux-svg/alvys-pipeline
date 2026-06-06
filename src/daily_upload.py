"""Daily MTD load report — replicates the manually-maintained
``Daily_Upload_MMDDYYYY.xlsx`` workbook by reading the Alvys Master 2026
xlsx on OneDrive, filtering to month-to-date, and writing a fresh dated
copy back to OneDrive (with email distribution).

Three tabs, each laid out exactly like the sample workbook the user
supplied:

  * **All Loads** — every MTD load (Cancelled excluded), grouped by
    Customer Sales Agent, with per-agent subtotals + a grand-total
    block at the bottom that includes the comprehensive
    "Mileage / Margin / Goal" projection.
  * **Customer Loads** — direct customers + no-customer rows (deadhead /
    repositioning legs that belong to the X-Trux operation). Same
    per-agent subtotal + simpler grand-total block.
  * **Spot Market** — broker freight. Same structure as Customer Loads.

Date filter is **first of the current calendar month → today** based on
the Scheduled Pickup column (matches PBI's monthly bucket).

Open-load empty-mileage estimate: if a load's Load Status isn't
``Completed`` or ``Invoiced`` and its Empty Dispatch Mileage column is
0/blank, substitute :data:`OPEN_EMPTY_ESTIMATE_MI` miles per the user's
spec so the report reads as a fair MTD snapshot even when in-flight
loads haven't been fully accounted yet.

Tunable constants used by the calc blocks live at the top of this
module — change them here, not in the worksheet:

  * :data:`TRUCK_PAY_PER_MI`   — assumed driver pay rate per mile
  * :data:`BREAK_EVEN_RPM`     — RPM needed to cover pay + overhead
  * :data:`GOAL_RPM`           — RPM target for the goal-analysis block
  * :data:`MARGIN_GOAL_MONTHLY` — monthly margin target
  * :data:`NUM_TRUCKS`         — current fleet count
"""
from __future__ import annotations

import io
import logging
import os
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import openpyxl
import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from src.onedrive_upload import (
    download_shared_file, ensure_folder, get_token, upload_file,
)
from src.scorecard_email import send_email

log = logging.getLogger("daily_upload")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")

CHI_TZ = ZoneInfo("America/Chicago")
OPEN_EMPTY_ESTIMATE_MI = 65
SETTLED_STATUSES = {"completed", "invoiced"}

# --- Goal-analysis tunables (match the manually-maintained sample) --------
TRUCK_PAY_PER_MI    = 1.85
BREAK_EVEN_RPM      = 2.81
GOAL_RPM            = 2.93
MARGIN_GOAL_MONTHLY = 160_000
NUM_TRUCKS          = 17

OUTPUT_COLS = [
    "Count", "Customer Sales Agent", "Load #", "Load Status", "Carrier",
    "Customer", "Pick City", "Pick State", "First Pick Status",
    "Drop City", "Drop State", "Last Drop Status",
    "Empty Dispatch Mileage", "Loaded Dispatch Mileage",
    "Customer Revenue", "Driver Rate", "Margin", "Margin %",
]

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


def _pick_source_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    for c in candidates:
        if c.strip().lower() in cols_lower:
            return cols_lower[c.strip().lower()]
    return None


def _find_col(df: pd.DataFrame, needles: list[str]) -> str | None:
    for needle in needles:
        for c in df.columns:
            if needle in str(c).lower():
                return c
    return None


def _to_naive_dt(series: pd.Series) -> pd.Series:
    d = pd.to_datetime(series, errors="coerce", utc=True)
    try:
        return d.dt.tz_localize(None)
    except (AttributeError, TypeError):
        return pd.to_datetime(series, errors="coerce")


def _resolve_columns(loads: pd.DataFrame) -> dict[str, str | None]:
    mapping = {
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
    resolved = {out: _pick_source_col(loads, candidates) for out, candidates in mapping.items()}
    missing = [k for k, v in resolved.items() if v is None]
    if missing:
        log.warning("Source columns not found, will be blank: %s", missing)
    return resolved


def _build_normalized(loads: pd.DataFrame, today_chi: pd.Timestamp) -> pd.DataFrame:
    cols = _resolve_columns(loads)
    date_col = _find_col(loads, ["scheduled pickup", "pickup date"])
    if not date_col:
        raise RuntimeError("No date column found in Loads sheet (expected 'Scheduled Pickup').")
    sub = loads.copy()
    dates = _to_naive_dt(sub[date_col])
    mtd_start = pd.Timestamp(today_chi.year, today_chi.month, 1)
    mtd_end   = pd.Timestamp(today_chi.year, today_chi.month, today_chi.day, 23, 59, 59)
    keep = dates.notna() & (dates >= mtd_start) & (dates <= mtd_end)
    sub = sub.loc[keep].copy()
    log.info("Filtered Loads to MTD %s..%s: %d rows", mtd_start.date(), mtd_end.date(), len(sub))

    if "Load Status" in sub.columns:
        before = len(sub)
        sub = sub[sub["Load Status"].astype(str).str.strip().str.lower() != "cancelled"]
        log.info("Dropped %d Cancelled loads (%d remaining)", before - len(sub), len(sub))

    out = pd.DataFrame()
    for out_col, src_col in cols.items():
        out[out_col] = sub[src_col].values if src_col else [None] * len(sub)

    for c in ("Empty Dispatch Mileage", "Loaded Dispatch Mileage",
              "Customer Revenue", "Driver Rate"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)

    status_lower = out["Load Status"].astype(str).str.strip().str.lower()
    is_open = ~status_lower.isin(SETTLED_STATUSES)
    needs_est = is_open & (out["Empty Dispatch Mileage"] <= 0)
    n_est = int(needs_est.sum())
    out.loc[needs_est, "Empty Dispatch Mileage"] = OPEN_EMPTY_ESTIMATE_MI
    if n_est:
        log.info("Set Empty Dispatch Mileage = %d mi for %d open loads (estimate)",
                 OPEN_EMPTY_ESTIMATE_MI, n_est)

    out["Margin"] = out["Customer Revenue"] - out["Driver Rate"]
    out["Margin %"] = (out["Margin"] / out["Customer Revenue"]).where(out["Customer Revenue"] != 0)

    return out


def _split_tabs(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    is_no_cust = df["Customer"].apply(_is_no_customer)
    is_direct  = df["Customer"].apply(_is_direct_customer)
    customer_mask = is_no_cust | is_direct
    return {
        "All Loads":      df.copy(),
        "Customer Loads": df.loc[customer_mask].copy(),
        "Spot Market":    df.loc[~customer_mask].copy(),
    }


# ---------------------------------------------------------------------------
# Xlsx writer — replicates the manual workbook's per-agent grouped layout
# ---------------------------------------------------------------------------

_NUM_FMT = {
    "Count":                  "#,##0",
    "Empty Dispatch Mileage": "#,##0",
    "Loaded Dispatch Mileage": "#,##0",
    "Customer Revenue":       '"$"#,##0.00',
    "Driver Rate":            '"$"#,##0.00',
    "Margin":                 '"$"#,##0.00',
    "Margin %":               "0.00%",
}
_HDR_FILL = PatternFill("solid", fgColor="F2F2F2")
_HDR_FONT = Font(bold=True)
_BOLD = Font(bold=True)


def _write_header(ws, row: int) -> int:
    for ci, name in enumerate(OUTPUT_COLS, start=1):
        cell = ws.cell(row=row, column=ci, value=name)
        cell.font = _HDR_FONT
        cell.fill = _HDR_FILL
    return row + 1


def _write_data_row(ws, row: int, count: int, rec: dict) -> int:
    values = [
        count,
        rec["Customer Sales Agent"], rec["Load #"], rec["Load Status"],
        rec["Carrier"], rec["Customer"],
        rec["Pick City"], rec["Pick State"], rec["First Pick Status"],
        rec["Drop City"], rec["Drop State"], rec["Last Drop Status"],
        rec["Empty Dispatch Mileage"], rec["Loaded Dispatch Mileage"],
        rec["Customer Revenue"], rec["Driver Rate"], rec["Margin"],
        rec["Margin %"],
    ]
    for ci, val in enumerate(values, start=1):
        cell = ws.cell(row=row, column=ci, value=val)
        col = OUTPUT_COLS[ci - 1]
        if col in _NUM_FMT:
            cell.number_format = _NUM_FMT[col]
    return row + 1


def _write_agent_subtotal(ws, row: int, agent: str, group: pd.DataFrame) -> int:
    """Per-agent subtotal block, matching the sample's layout exactly."""
    empty_mi  = float(group["Empty Dispatch Mileage"].sum())
    loaded_mi = float(group["Loaded Dispatch Mileage"].sum())
    total_mi  = empty_mi + loaded_mi
    revenue   = float(group["Customer Revenue"].sum())
    pay       = float(group["Driver Rate"].sum())
    margin    = revenue - pay
    rpm        = (revenue / total_mi) if total_mi else 0
    dh_pct     = (empty_mi / total_mi) if total_mi else 0
    pay_per_mi = (pay / total_mi) if total_mi else 0
    mgn_per_mi = (margin / total_mi) if total_mi else 0

    row += 1  # leading blank

    # Sum row — cols M..Q (13..17)
    ws.cell(row=row, column=13, value=empty_mi).number_format = "#,##0"
    ws.cell(row=row, column=14, value=loaded_mi).number_format = "#,##0"
    ws.cell(row=row, column=15, value=revenue).number_format = '"$"#,##0.00'
    ws.cell(row=row, column=16, value=pay).number_format = '"$"#,##0.00'
    ws.cell(row=row, column=17, value=margin).number_format = '"$"#,##0.00'
    for c in (13, 14, 15, 16, 17):
        ws.cell(row=row, column=c).font = _BOLD
    row += 2  # blank between sum and labeled calcs

    first = (agent or "").split()[0] if agent else ""
    label = f"{first} Totals" if first else "Totals"
    ws.cell(row=row, column=13, value=label).font = _BOLD
    ws.cell(row=row, column=14, value="RPM")
    ws.cell(row=row, column=15, value=rpm).number_format = '"$"#,##0.0000'
    row += 1

    for lbl, val, fmt in (
        ("Total Miles", total_mi, "#,##0"),
        ("DH %", dh_pct, "0.00%"),
        ("Average Truck Pay per Mile", pay_per_mi, '"$"#,##0.0000'),
        ("Average Margin Per Mile", mgn_per_mi, '"$"#,##0.0000'),
    ):
        ws.cell(row=row, column=14, value=lbl)
        ws.cell(row=row, column=15, value=val).number_format = fmt
        row += 1

    row += 4  # trailing blanks before next agent's repeated header
    return row


def _write_grand_total(ws, row: int, tab_df: pd.DataFrame, agents: list[str],
                        today_chi: pd.Timestamp, include_goal_block: bool) -> int:
    total_loads = len(tab_df)
    empty_mi  = float(tab_df["Empty Dispatch Mileage"].sum())
    loaded_mi = float(tab_df["Loaded Dispatch Mileage"].sum())
    total_mi  = empty_mi + loaded_mi
    revenue   = float(tab_df["Customer Revenue"].sum())
    pay       = float(tab_df["Driver Rate"].sum())
    margin    = revenue - pay
    rpm        = (revenue / total_mi) if total_mi else 0
    dh_pct     = (empty_mi / total_mi) if total_mi else 0
    pay_per_mi = (pay / total_mi) if total_mi else 0
    mgn_per_mi = (margin / total_mi) if total_mi else 0
    goal_mgn_per_mi    = GOAL_RPM - TRUCK_PAY_PER_MI
    diff_from_goal_rpm = rpm - GOAL_RPM
    pct_diff_from_goal = (diff_from_goal_rpm / GOAL_RPM) if GOAL_RPM else 0
    rev_missed = diff_from_goal_rpm * total_mi
    mgn_missed = rev_missed

    row = _write_header(ws, row)

    # Sum row
    ws.cell(row=row, column=1, value=total_loads).font = _BOLD
    ws.cell(row=row, column=13, value=empty_mi).number_format = "#,##0"
    ws.cell(row=row, column=14, value=loaded_mi).number_format = "#,##0"
    ws.cell(row=row, column=15, value=revenue).number_format = '"$"#,##0.00'
    ws.cell(row=row, column=16, value=pay).number_format = '"$"#,##0.00'
    ws.cell(row=row, column=17, value=margin).number_format = '"$"#,##0.00'
    for c in (1, 13, 14, 15, 16, 17):
        ws.cell(row=row, column=c).font = _BOLD
    row += 2

    # Per-agent percentage table headers (cols I/J/K) + RPM (cols N/O)
    ws.cell(row=row, column=9, value="% of Loads Booked").font = _BOLD
    ws.cell(row=row, column=10, value="% of Revenue").font = _BOLD
    ws.cell(row=row, column=11, value="% of Margin").font = _BOLD
    ws.cell(row=row, column=14, value="RPM")
    ws.cell(row=row, column=15, value=rpm).number_format = '"$"#,##0.0000'
    row += 1

    # Per-agent rows
    agent_metrics = []
    for ag in agents:
        if ag == "Unassigned":
            g = tab_df[tab_df["Customer Sales Agent"].astype(str).str.strip().isin(("", "nan", "None"))]
        else:
            g = tab_df[tab_df["Customer Sales Agent"].astype(str).str.strip() == ag]
        ag_rev = float(g["Customer Revenue"].sum())
        ag_mgn = float((g["Customer Revenue"] - g["Driver Rate"]).sum())
        agent_metrics.append({
            "first": (ag.split()[0] if ag else ""),
            "loads_pct": (len(g) / total_loads) if total_loads else 0,
            "rev_pct":   (ag_rev / revenue) if revenue else 0,
            "mgn_pct":   (ag_mgn / margin) if margin else 0,
        })

    goal_block_lines = [
        ("Goal RPM",                       GOAL_RPM,              '"$"#,##0.00'),
        ("Difference from Goal",           diff_from_goal_rpm,    '"$"#,##0.0000'),
        ("% of Difference from Goal",      pct_diff_from_goal,    "0.00%"),
        ("Total Miles",                    total_mi,              "#,##0"),
        ("DH %",                           dh_pct,                "0.00%"),
        ("Average Truck Pay per Mile",     pay_per_mi,            '"$"#,##0.0000'),
        ("Average Margin Per Mile",        mgn_per_mi,            '"$"#,##0.0000'),
        ("Goal Margin Per Mile",           goal_mgn_per_mi,       '"$"#,##0.0000'),
        ("Difference from Goal",           diff_from_goal_rpm,    '"$"#,##0.0000'),
        ("Revenue Missed Opportunity",     rev_missed,            '"$"#,##0.00'),
        ("Margin Missed Opportunity",      mgn_missed,            '"$"#,##0.00'),
    ]

    n_rows = max(len(agent_metrics) + 1, len(goal_block_lines))
    for i in range(n_rows):
        if i < len(agent_metrics):
            am = agent_metrics[i]
            ws.cell(row=row, column=8,  value=am["first"])
            ws.cell(row=row, column=9,  value=am["loads_pct"]).number_format = "0.00%"
            ws.cell(row=row, column=10, value=am["rev_pct"]).number_format = "0.00%"
            ws.cell(row=row, column=11, value=am["mgn_pct"]).number_format = "0.00%"
        elif i == len(agent_metrics):
            ws.cell(row=row, column=8, value="Total").font = _BOLD
            ws.cell(row=row, column=9,  value=1).number_format = "0.00%"
            ws.cell(row=row, column=10, value=1).number_format = "0.00%"
            ws.cell(row=row, column=11, value=1).number_format = "0.00%"
        if i < len(goal_block_lines):
            label, value, fmt = goal_block_lines[i]
            ws.cell(row=row, column=14, value=label)
            ws.cell(row=row, column=15, value=value).number_format = fmt
        row += 1

    if not include_goal_block:
        row += 1
        ws.cell(row=row, column=15, value=total_loads).font = _BOLD
        row += 1
        ws.cell(row=row, column=14, value="Percentage of Total Loads")
        ws.cell(row=row, column=15, value=1).number_format = "0.00%"
        return row + 1

    # All Loads only — full goal-analysis projection
    row += 1
    ws.cell(row=row, column=15, value=total_loads).font = _BOLD
    row += 1
    ws.cell(row=row, column=14, value="Percentage of Total Loads")
    ws.cell(row=row, column=15, value=1).number_format = "0.00%"
    row += 2

    ws.cell(row=row, column=2, value="We are at").font = _BOLD
    row += 1

    days_in_month = (pd.Timestamp(today_chi.year, today_chi.month, 1)
                     + pd.offsets.MonthEnd(0)).day
    day_of_month  = today_chi.day or 1
    est_mileage   = total_mi * (days_in_month / day_of_month) if day_of_month else total_mi

    cur_mpm = rpm - TRUCK_PAY_PER_MI
    be_mpm  = BREAK_EVEN_RPM - TRUCK_PAY_PER_MI
    gl_mpm  = GOAL_RPM - TRUCK_PAY_PER_MI

    cur_margin_est = est_mileage * cur_mpm
    be_margin_est  = est_mileage * be_mpm
    gl_margin_est  = est_mileage * gl_mpm

    cur_est_to_goal = cur_margin_est - MARGIN_GOAL_MONTHLY
    be_est_to_goal  = be_margin_est  - MARGIN_GOAL_MONTHLY
    gl_est_to_goal  = gl_margin_est  - MARGIN_GOAL_MONTHLY

    def _short(margin_gap, mpm):
        return (-margin_gap / mpm) if mpm else 0
    cur_short = _short(cur_est_to_goal, cur_mpm)
    be_short  = _short(be_est_to_goal,  be_mpm)
    gl_short  = _short(gl_est_to_goal,  gl_mpm)

    total_needed_cur = est_mileage + cur_short
    total_needed_be  = est_mileage + be_short
    total_needed_gl  = est_mileage + gl_short

    mi_per_truck     = total_mi   / NUM_TRUCKS if NUM_TRUCKS else 0
    est_mi_per_truck = est_mileage / NUM_TRUCKS if NUM_TRUCKS else 0
    need_pt_cur = total_needed_cur / NUM_TRUCKS if NUM_TRUCKS else 0
    need_pt_be  = total_needed_be  / NUM_TRUCKS if NUM_TRUCKS else 0
    need_pt_gl  = total_needed_gl  / NUM_TRUCKS if NUM_TRUCKS else 0
    short_pt_cur = need_pt_cur - est_mi_per_truck
    short_pt_be  = need_pt_be  - est_mi_per_truck
    short_pt_gl  = need_pt_gl  - est_mi_per_truck
    trucks_needed_cur = total_needed_cur / est_mi_per_truck if est_mi_per_truck else 0
    trucks_needed_be  = total_needed_be  / est_mi_per_truck if est_mi_per_truck else 0
    trucks_needed_gl  = total_needed_gl  / est_mi_per_truck if est_mi_per_truck else 0

    ws.cell(row=row, column=3, value="Break Even").font = _BOLD
    ws.cell(row=row, column=4, value="Goal").font = _BOLD
    proj_rows = [
        ("Dead Head",                   dh_pct,            dh_pct,            dh_pct,            "0.00%"),
        ("Trux RPM",                    rpm,               BREAK_EVEN_RPM,    GOAL_RPM,          '"$"#,##0.00'),
        ("Trux Margin Est",             cur_margin_est,    be_margin_est,     gl_margin_est,     '"$"#,##0.00'),
        ("Truck Miles",                 total_mi,          total_mi,          total_mi,          "#,##0"),
        ("Truck Pay",                   TRUCK_PAY_PER_MI,  TRUCK_PAY_PER_MI,  TRUCK_PAY_PER_MI,  '"$"#,##0.00'),
        ("Truck Margin Per Mile",       cur_mpm,           be_mpm,            gl_mpm,            '"$"#,##0.00'),
        ("Estimated Mileage",           est_mileage,       est_mileage,       est_mileage,       "#,##0"),
        ("Estimated Margin",            cur_margin_est,    be_margin_est,     gl_margin_est,     '"$"#,##0.00'),
        ("Margin Needed",               MARGIN_GOAL_MONTHLY, MARGIN_GOAL_MONTHLY, MARGIN_GOAL_MONTHLY, '"$"#,##0.00'),
        ("Estimate Margin to Goal",     cur_est_to_goal,   be_est_to_goal,    gl_est_to_goal,    '"$"#,##0.00'),
        ("Mileage Short Needed for Goal", cur_short, be_short, gl_short, "#,##0"),
        ("Total Miles Needed",          total_needed_cur,  total_needed_be,   total_needed_gl,   "#,##0"),
        ("Number of Trucks",            NUM_TRUCKS,        NUM_TRUCKS,        NUM_TRUCKS,        "0"),
        ("Mileage per truck",           mi_per_truck,      mi_per_truck,      mi_per_truck,      "#,##0"),
        ("Estimated Mileage per truck", est_mi_per_truck,  est_mi_per_truck,  est_mi_per_truck,  "#,##0"),
        ("Mileage Need per truck",      need_pt_cur,       need_pt_be,        need_pt_gl,        "#,##0"),
        ("Short Mileage per truck",     short_pt_cur,      short_pt_be,       short_pt_gl,       "#,##0"),
        ("Trucks Needed at Estimated Mileage", trucks_needed_cur, trucks_needed_be, trucks_needed_gl, "0.00"),
    ]
    for label, cv, bv, gv, fmt in proj_rows:
        ws.cell(row=row, column=1, value=label).font = _BOLD
        for ci, val in zip((2, 3, 4), (cv, bv, gv)):
            ws.cell(row=row, column=ci, value=val).number_format = fmt
        row += 1

    return row


def _agents_in_order(df: pd.DataFrame) -> list[str]:
    """Preserve agent order as they appear in the source data; treat empty/nan
    as a single 'Unassigned' bucket. De-dupes while preserving order."""
    seen: list[str] = []
    for v in df["Customer Sales Agent"].astype(str):
        a = v.strip()
        if a.lower() in ("", "nan", "none"):
            a = "Unassigned"
        if a not in seen:
            seen.append(a)
    return seen


def _write_tab(ws, df: pd.DataFrame, include_goal_block: bool,
                today_chi: pd.Timestamp) -> None:
    widths = {1: 7, 2: 22, 3: 11, 4: 13, 5: 18, 6: 30, 7: 18, 8: 6,
              9: 16, 10: 16, 11: 14, 12: 14, 13: 12, 14: 22, 15: 14,
              16: 12, 17: 12, 18: 9}
    for ci, w in widths.items():
        ws.column_dimensions[get_column_letter(ci)].width = w

    row = 1
    row = _write_header(ws, row)

    if df.empty:
        ws.cell(row=row, column=1, value="(no MTD loads)")
        return

    agents = _agents_in_order(df)
    for agent in agents:
        if agent == "Unassigned":
            group = df[df["Customer Sales Agent"].astype(str).str.strip().isin(("", "nan", "None"))]
        else:
            group = df[df["Customer Sales Agent"].astype(str).str.strip() == agent]
        for count, (_, rec) in enumerate(group.iterrows(), start=1):
            row = _write_data_row(ws, row, count, rec.to_dict())
        row = _write_agent_subtotal(ws, row, agent, group)

    row = _write_grand_total(ws, row, df, agents, today_chi, include_goal_block)


def _write_xlsx(tabs: dict[str, pd.DataFrame], file_path: Path,
                 today_chi: pd.Timestamp) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, df in tabs.items():
        ws = wb.create_sheet(title=name)
        _write_tab(ws, df, include_goal_block=(name == "All Loads"),
                    today_chi=today_chi)
        log.info("Tab %r: %d data rows", name, len(df))
    wb.save(file_path)
    log.info("Wrote %s", file_path)


def _summary_html(tabs: dict[str, pd.DataFrame], file_label: str) -> str:
    parts = ['<div style="font-family:-apple-system,Helvetica,Arial,sans-serif;'
              'font-size:14px;color:#1a1a1a;line-height:1.5;padding:24px;max-width:560px">']
    parts.append('<div style="font-weight:700;letter-spacing:1.5px;font-size:11px;'
                  'color:#c41e2a;text-transform:uppercase;margin-bottom:14px">'
                  'XFreight &middot; Daily MTD Upload</div>')
    parts.append(f"<p style='margin:0 0 12px'>Attached: <b>{file_label}</b> &mdash; "
                  "month-to-date load list refreshed for this morning, grouped by "
                  "Customer Sales Agent with per-agent subtotals.</p>")
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
        raise SystemExit("DAILY_UPLOAD_ALVYS_SHARE_URL is required.")
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
        _write_xlsx(tabs, local_path, today_chi)

        if out_folder:
            ensure_folder(token, upn, out_folder)
            log.info("Uploading to OneDrive folder %r as %s …", out_folder, file_label)
        else:
            log.info("Uploading to OneDrive root as %s …", file_label)
        upload_file(token, upn, out_folder, file_label, local_path)

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
