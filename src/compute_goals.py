"""Cost-floor + percentile hybrid goal calculator (one-off).

Computes proposed RPM and Deadhead goals for the X-Trux/XFreight asset fleet:

    RPM goal      = max( all_in_cost_per_mile * (1 + target_margin),
                         p75 of trailing-180-day monthly RPM )
    Deadhead goal = p25 of trailing-180-day monthly Deadhead %
                    (percentile only; cost-of-empty-mile cap is a future refinement)

Sources, no live API calls — reads what's already in OneDrive:
  - X-Trux Inc YTD P&L from QB_ProfitAndLoss.xlsx (Jan 1 -> today, "This Fiscal Year")
  - X-Trux + XFreight Alvys office loads from "Alvys Master 2026.xlsx"

The QB P&L window is YTD ('This Fiscal Year' macro). We compute cost/mile by
dividing YTD operating cost (Total COGS + Total Expense) by YTD X-Trux/XFreight
dispatch mileage in the same window — a density metric, so the slightly-longer
window (vs trailing-90) is fine for the floor.

Emails a plain-text report to SCORECARD_TO_EMAILS using the same Azure
Mail.Send credentials the scorecard uses.
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
    _col_any,
    _dates,
    _entity_group,
    _find_col,
    send_email,
)

log = logging.getLogger("compute_goals")

TARGET_MARGINS = (0.10, 0.15, 0.20)
TRAILING_DAYS_PERCENTILE = 180
PERCENTILE_RPM = 0.75
PERCENTILE_DEADHEAD = 0.25
QB_COMPANY = "X-Trux Inc"  # Asset-fleet company file in QB; XFreight office bills here.


def compute_xtrux_ytd_cost(pnl_df: pd.DataFrame) -> dict:
    """Return X-Trux Inc YTD COGS + Expenses + a label column reference."""
    label_col = "Account" if "Account" in pnl_df.columns else pnl_df.columns[-2]
    amt_col = "Total" if "Total" in pnl_df.columns else pnl_df.columns[-1]
    sub = pnl_df[pnl_df["Company"].astype(str) == QB_COMPANY]
    if sub.empty:
        log.warning("QB P&L has no rows for company %s", QB_COMPANY)
        return {}

    def grab(phrase: str):
        m = sub[sub[label_col].astype(str).str.strip() == phrase]
        if m.empty:
            return None
        vals = pd.to_numeric(m[amt_col], errors="coerce").dropna()
        return float(vals.iloc[-1]) if len(vals) else None

    income = grab("Total Income")
    cogs = grab("Total Cost of Goods Sold")
    opex = grab("Total Expenses")
    net = grab("Net Income")
    op_cost = (cogs or 0) + (opex or 0)
    return {
        "income": income,
        "cogs": cogs,
        "opex": opex,
        "net": net,
        "op_cost": op_cost or None,
    }


def compute_xtrux_ytd_miles(loads: pd.DataFrame) -> dict:
    """Return YTD X-Trux/XFreight asset-fleet mileage from the Alvys workbook."""
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if not office_col:
        return {}
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    ytd_start = pd.Timestamp(pd.Timestamp.now().year, 1, 1)
    not_cancelled = (loads["Load Status"].astype(str).str.lower() != "cancelled"
                     if "Load Status" in loads.columns else pd.Series(True, index=loads.index))
    asset_mask = loads[office_col].map(_entity_group) == "X-Trux"
    mask = (dates >= ytd_start) & not_cancelled & asset_mask
    sub = loads[mask]
    total_miles = float(_col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage",
                                       "Total Miles", "Total Mileage"]).sum())
    empty_miles = float(_col_any(sub, ["Empty Dispatch Mileage", "Empty Mileage",
                                       "Empty Miles"]).sum())
    revenue = float(_col_any(sub, ["Customer Revenue", "Revenue"]).sum())
    return {
        "loads": int(len(sub)),
        "miles": total_miles,
        "empty_miles": empty_miles,
        "revenue": revenue,
    }


def compute_monthly_history(loads: pd.DataFrame, months: int = 6) -> list[dict]:
    """Per-month RPM and Deadhead % for X-Trux/XFreight, last N closed months
    (plus current MTD as the most recent, marked separately)."""
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if not office_col:
        return []
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    not_cancelled = (loads["Load Status"].astype(str).str.lower() != "cancelled"
                     if "Load Status" in loads.columns else pd.Series(True, index=loads.index))
    asset_mask = loads[office_col].map(_entity_group) == "X-Trux"
    base = loads[not_cancelled & asset_mask].copy()
    base_dates = dates[not_cancelled & asset_mask]
    base["_month"] = base_dates.dt.to_period("M")
    now = pd.Timestamp.now()
    cur_period = pd.Period(year=now.year, month=now.month, freq="M")

    out: list[dict] = []
    for i in range(months, -1, -1):
        period = cur_period - i
        sub = base[base["_month"] == period]
        if sub.empty:
            continue
        rev = float(_col_any(sub, ["Customer Revenue", "Revenue"]).sum())
        miles = float(_col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage",
                                     "Total Miles", "Total Mileage"]).sum())
        empty = float(_col_any(sub, ["Empty Dispatch Mileage", "Empty Mileage",
                                     "Empty Miles"]).sum())
        out.append({
            "month": str(period),
            "is_current_mtd": period == cur_period,
            "loads": int(len(sub)),
            "revenue": rev,
            "miles": miles,
            "empty_miles": empty,
            "rpm": (rev / miles) if miles else None,
            "deadhead_pct": (empty / miles) if miles else None,
        })
    return out


def _percentile(values: list[float], p: float) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return float(pd.Series(vals).quantile(p))


def build_report(qb: dict, miles: dict, history: list[dict], data_asof_alvys=None) -> str:
    cost = qb.get("op_cost")
    yt_miles = miles.get("miles")
    cpm = (cost / yt_miles) if (cost and yt_miles) else None
    yt_rpm = (miles.get("revenue") / yt_miles) if (miles.get("revenue") and yt_miles) else None
    yt_dh = (miles.get("empty_miles") / yt_miles) if (miles.get("empty_miles") and yt_miles) else None

    # Closed-month history (drop the current MTD partial from the percentile basis).
    closed = [h for h in history if not h.get("is_current_mtd")]
    rpm_vals = [h["rpm"] for h in closed if h.get("rpm") is not None]
    dh_vals = [h["deadhead_pct"] for h in closed if h.get("deadhead_pct") is not None]
    p75_rpm = _percentile(rpm_vals, PERCENTILE_RPM)
    p25_dh = _percentile(dh_vals, PERCENTILE_DEADHEAD)

    def fmt_money(v): return f"${v:,.0f}" if v is not None else "n/a"
    def fmt_rpm(v): return f"${v:.3f}" if v is not None else "n/a"
    def fmt_pct(v): return f"{v*100:.2f}%" if v is not None else "n/a"
    def fmt_int(v): return f"{v:,.0f}" if v is not None else "n/a"

    today = pd.Timestamp.now().strftime("%B %d, %Y")
    ytd_label = f"Jan 1 - {today} (YTD, This Fiscal Year)"

    lines: list[str] = []
    lines.append("Goal calculator - X-Trux/XFreight asset fleet")
    lines.append("=" * 60)
    lines.append(f"As of: {today}")
    if data_asof_alvys is not None:
        try:
            t = pd.Timestamp(data_asof_alvys).tz_convert("America/Chicago")
        except Exception:
            t = pd.Timestamp(data_asof_alvys)
            try:
                t = t.tz_localize(None)
            except Exception:
                pass
        lines.append(f"Alvys workbook last modified: {t:%b %d, %Y %I:%M %p}")
    lines.append("")
    lines.append(f"Source: QB_ProfitAndLoss.xlsx -> {QB_COMPANY}, {ytd_label}")
    lines.append(f"        Alvys Master 2026.xlsx -> X-Trux + XFreight offices, same window")
    lines.append("")
    lines.append("--- INPUT: cost density ---")
    lines.append(f"  Total Income (YTD):                  {fmt_money(qb.get('income'))}")
    lines.append(f"  Total Cost of Goods Sold (YTD):      {fmt_money(qb.get('cogs'))}")
    lines.append(f"  Total Expenses (YTD):                {fmt_money(qb.get('opex'))}")
    lines.append(f"  Net Income (YTD):                    {fmt_money(qb.get('net'))}")
    lines.append(f"  Operating cost (COGS + Expenses):    {fmt_money(cost)}")
    lines.append(f"  X-Trux/XFreight dispatch miles (YTD):{fmt_int(yt_miles):>14}")
    lines.append(f"  All-in cost per mile:                {fmt_rpm(cpm)}")
    lines.append("")
    lines.append("--- INPUT: trailing-6-month closed history ---")
    lines.append(f"  {'month':10s}  {'loads':>7}  {'revenue':>12}  {'miles':>10}  {'rpm':>8}  {'deadhead':>10}")
    for h in history:
        tag = " *MTD" if h.get("is_current_mtd") else ""
        lines.append(f"  {h['month']:10s}  {h['loads']:>7,}  "
                     f"{fmt_money(h['revenue']):>12}  {h['miles']:>10,.0f}  "
                     f"{fmt_rpm(h['rpm']):>8}  {fmt_pct(h['deadhead_pct']):>10}{tag}")
    lines.append("")
    lines.append("--- PERCENTILE GOAL (closed months only, current MTD excluded) ---")
    lines.append(f"  Trailing-{TRAILING_DAYS_PERCENTILE}d months in sample: {len(closed)}")
    lines.append(f"  p{int(PERCENTILE_RPM*100)} of monthly RPM:           {fmt_rpm(p75_rpm)}")
    lines.append(f"  p{int(PERCENTILE_DEADHEAD*100)} of monthly Deadhead %:    {fmt_pct(p25_dh)}")
    lines.append(f"  YTD-weighted RPM (whole period):    {fmt_rpm(yt_rpm)}")
    lines.append(f"  YTD-weighted Deadhead % (whole period): {fmt_pct(yt_dh)}")
    lines.append("")
    lines.append("--- HYBRID RPM GOAL = max(cost-floor, p75) ---")
    lines.append(f"  {'target margin':14s}  {'cost floor':>12}  {'p75 RPM':>12}  {'hybrid goal':>12}")
    for m in TARGET_MARGINS:
        floor = (cpm * (1 + m)) if cpm is not None else None
        hybrid = None
        if floor is not None and p75_rpm is not None:
            hybrid = max(floor, p75_rpm)
        elif floor is not None:
            hybrid = floor
        elif p75_rpm is not None:
            hybrid = p75_rpm
        lines.append(f"  {m*100:>4.0f}%          "
                     f"{fmt_rpm(floor):>12}  {fmt_rpm(p75_rpm):>12}  {fmt_rpm(hybrid):>12}")
    lines.append("")
    lines.append("--- DEADHEAD GOAL (percentile only for now) ---")
    lines.append(f"  Recommended: p25 of closed-month deadhead % = {fmt_pct(p25_dh)}")
    lines.append("  (Cost-of-empty-mile cap can layer on top once fuel $/mi is wired in.)")
    lines.append("")
    lines.append("Notes:")
    lines.append("  - 'YTD' = 'This Fiscal Year' macro from QuickBooks (Jan 1 -> today).")
    lines.append("  - Cost basis is X-Trux Inc only; XFreight is an Alvys office that")
    lines.append("    bills under X-Trux Inc in QuickBooks.")
    lines.append("  - p75 of monthly RPM is the 75th-percentile of closed-month RPM")
    lines.append("    values: if you achieved it 1 month in 4 over the last 6 months,")
    lines.append("    it is your stretch-but-proven target.")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not all([tenant, client, secret, upn]):
        sys.exit("ERROR: AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET and ONEDRIVE_USER_UPN are required")
    from_upn = os.environ.get("SCORECARD_FROM_UPN", upn)
    to_emails = [e.strip() for e in os.environ.get("SCORECARD_TO_EMAILS", "jeff@xfreight.net").split(",")
                 if e.strip()]
    alvys_share = os.environ.get("SCORECARD_ALVYS_SHARE_URL", "").strip()
    alvys_path = os.environ.get("SCORECARD_ALVYS_PATH", "Alvys Master 2026.xlsx")
    qb_dir = os.environ.get("SCORECARD_QB_DIR", "QuickBooks").strip("/")

    token = get_token(tenant, client, secret)

    # Alvys workbook (prefer the share URL — same as scorecard).
    alvys_sheets = None
    data_asof_alvys = None
    if alvys_share:
        try:
            alvys_sheets = pd.read_excel(io.BytesIO(download_shared_file(token, alvys_share)),
                                         sheet_name=None)
            log.info("Read Alvys via share URL")
        except Exception as exc:
            log.warning("Could not read Alvys via share URL: %s", exc)
    if alvys_sheets is None:
        alvys_sheets = pd.read_excel(io.BytesIO(download_file(token, upn, alvys_path)),
                                     sheet_name=None)
        log.info("Read Alvys by path: %s", alvys_path)
    loads = alvys_sheets.get("Loads")
    if loads is None or loads.empty:
        sys.exit("ERROR: Alvys Loads sheet missing/empty")

    pnl_sheets = pd.read_excel(io.BytesIO(download_file(token, upn, f"{qb_dir}/QB_ProfitAndLoss.xlsx")),
                               sheet_name=None)
    pnl_df = next(iter(pnl_sheets.values()))

    qb = compute_xtrux_ytd_cost(pnl_df)
    miles = compute_xtrux_ytd_miles(loads)
    history = compute_monthly_history(loads, months=6)
    report_text = build_report(qb, miles, history, data_asof_alvys=data_asof_alvys)
    log.info("\n%s", report_text)

    html_body = "<pre style='font-family:Consolas,Menlo,monospace;font-size:12px;'>" + (
        report_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ) + "</pre>"
    subject = f"Goal calculator - X-Trux/XFreight - {pd.Timestamp.now():%b %d, %Y}"
    send_email(token, from_upn, to_emails, subject, html_body)
    try:
        from src.karpathy_writer import frontmatter, save
        body = frontmatter("Goal calculator report", "goals") + \
               "# Goal calculator — X-Trux/XFreight\n\n```text\n" + report_text + "\n```\n"
        save("goals", "goal-calculator", body)
    except Exception as exc:
        log.warning("Karpathy-Wiki archive skipped: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
