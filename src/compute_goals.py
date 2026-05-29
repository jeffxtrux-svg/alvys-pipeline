"""Goal calculator — X-Trux rate-per-mile algorithm.

Cost-per-mile is *derived from* the X-Trux RPM goal and the operating-ratio
target — not measured from QB P&L. The algorithm:

    cost_per_mile = TARGET_RPM * TARGET_OR

where TARGET_RPM is the X-Trux/XFreight revenue-per-mile target and TARGET_OR
is the operating ratio target (cost as a fraction of revenue). With the current
constants (TARGET_RPM=$2.92, TARGET_OR=0.95) this gives $2.774/mile — the
implied all-in cost per mile that the RPM goal assumes.

Hybrid RPM goal at each target margin scenario:

    RPM_floor = cost_per_mile / (1 - target_margin)
    RPM_goal  = max(RPM_floor, p75 of trailing-180-day monthly RPM)

The percentile remains data-driven (sourced from the Alvys workbook history)
so the goal won't drop below what the fleet has historically achieved.

Reads ONLY the Alvys workbook from OneDrive (for the historical RPM percentile
and per-month deadhead percentile). No QuickBooks read; no Goals & Trends
workbook read. Emails a plain-text report to SCORECARD_TO_EMAILS.
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
    TARGET_OR,
    TARGET_RPM,
    _col_any,
    _dates,
    _entity_group,
    _find_col,
    send_email,
)

log = logging.getLogger("compute_goals")

TARGET_MARGINS = (0.05, 0.10, 0.15, 0.20)
TRAILING_DAYS_PERCENTILE = 180
PERCENTILE_RPM = 0.75
PERCENTILE_DEADHEAD = 0.25


def algorithm_cost_per_mile(target_rpm: float = TARGET_RPM,
                            target_or: float = TARGET_OR) -> float:
    """X-Trux rate-per-mile cost algorithm.

    cost_per_mile = TARGET_RPM * TARGET_OR

    The RPM goal already encodes the price you intend to charge per mile; the
    operating ratio encodes what fraction of that price is consumed by cost.
    Their product is the implied all-in cost per mile at the goal RPM.
    """
    return target_rpm * target_or


def compute_xtrux_history(loads: pd.DataFrame, months: int = 6) -> list[dict]:
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
        loaded = float(_col_any(sub, ["Loaded Mileage", "Loaded Dispatch Mileage",
                                       "Loaded Miles"]).sum())
        empty = float(_col_any(sub, ["Empty Mileage", "Empty Dispatch Mileage",
                                      "Empty Miles"]).sum())
        # Match the scorecard's Power BI-aligned formulas: denominators are
        # Loaded miles (not Loaded + Empty), Dead Head % = Empty / Loaded.
        out.append({
            "month": str(period),
            "is_current_mtd": period == cur_period,
            "loads": int(len(sub)),
            "revenue": rev,
            "loaded": loaded,
            "empty": empty,
            "rpm": (rev / loaded) if loaded else None,
            "deadhead_pct": (empty / loaded) if loaded else None,
        })
    return out


def _percentile(values: list[float], p: float) -> float | None:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return float(pd.Series(vals).quantile(p))


def build_report(history: list[dict],
                 data_asof_alvys=None,
                 target_rpm: float = TARGET_RPM,
                 target_or: float = TARGET_OR) -> str:
    cpm = algorithm_cost_per_mile(target_rpm, target_or)

    # Closed-month history (drop the current MTD partial from the percentile basis).
    closed = [h for h in history if not h.get("is_current_mtd")]
    rpm_vals = [h["rpm"] for h in closed if h.get("rpm") is not None]
    dh_vals = [h["deadhead_pct"] for h in closed if h.get("deadhead_pct") is not None]
    p75_rpm = _percentile(rpm_vals, PERCENTILE_RPM)
    p25_dh = _percentile(dh_vals, PERCENTILE_DEADHEAD)

    def fmt_rpm(v): return f"${v:.3f}" if v is not None else "n/a"
    def fmt_pct(v): return f"{v*100:.2f}%" if v is not None else "n/a"
    def fmt_int(v): return f"{v:,.0f}" if v is not None else "n/a"
    def fmt_money(v): return f"${v:,.0f}" if v is not None else "n/a"

    today = pd.Timestamp.now().strftime("%B %d, %Y")

    lines: list[str] = []
    lines.append("Goal calculator — X-Trux/XFreight asset fleet")
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
    lines.append("--- COST DERIVATION (X-Trux rate-per-mile algorithm) ---")
    lines.append("  cost_per_mile = TARGET_RPM * TARGET_OR")
    lines.append(f"                = {fmt_rpm(target_rpm)} * {target_or:.4f}")
    lines.append(f"                = {fmt_rpm(cpm)}")
    lines.append("")
    lines.append("--- INPUT: trailing-6-month closed history (from Alvys workbook) ---")
    lines.append(f"  {'month':10s}  {'loads':>7}  {'revenue':>12}  {'loaded':>10}  {'rpm':>8}  {'deadhead':>10}")
    for h in history:
        tag = " *MTD" if h.get("is_current_mtd") else ""
        lines.append(f"  {h['month']:10s}  {h['loads']:>7,}  "
                     f"{fmt_money(h['revenue']):>12}  {h['loaded']:>10,.0f}  "
                     f"{fmt_rpm(h['rpm']):>8}  {fmt_pct(h['deadhead_pct']):>10}{tag}")
    lines.append("")
    lines.append("--- PERCENTILE GOAL (closed months only, current MTD excluded) ---")
    lines.append(f"  Closed months in sample:                {len(closed)}")
    lines.append(f"  p{int(PERCENTILE_RPM*100)} of monthly RPM:                   {fmt_rpm(p75_rpm)}")
    lines.append(f"  p{int(PERCENTILE_DEADHEAD*100)} of monthly Deadhead %:            {fmt_pct(p25_dh)}")
    lines.append("")
    lines.append("--- HYBRID RPM GOAL = max(cost-floor, p75) ---")
    lines.append(f"  cost-floor at margin m = cost_per_mile / (1 - m)")
    lines.append(f"  {'target margin':14s}  {'cost floor':>12}  {'p75 RPM':>12}  {'hybrid goal':>12}")
    for m in TARGET_MARGINS:
        floor = cpm / (1 - m) if (1 - m) > 0 else None
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
    lines.append("--- DEADHEAD GOAL (percentile only) ---")
    lines.append(f"  Recommended: p25 of closed-month deadhead % = {fmt_pct(p25_dh)}")
    lines.append("")
    lines.append("Notes:")
    lines.append("  - Cost-per-mile is derived from the X-Trux RPM goal, not")
    lines.append("    measured from QuickBooks. TARGET_RPM and TARGET_OR live")
    lines.append("    in src/scorecard_email.py — update the constants there.")
    lines.append("  - p75 of monthly RPM is the 75th-percentile of closed-month")
    lines.append("    RPM values: if you achieved it 1 month in 4 over the last")
    lines.append("    6 months, it is your stretch-but-proven target.")
    lines.append("  - All denominator math (RPM and Dead Head %) uses Loaded")
    lines.append("    Mileage, matching the Power BI XFreight Report.")
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

    token = get_token(tenant, client, secret)
    alvys_sheets = None
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

    history = compute_xtrux_history(loads, months=6)
    report_text = build_report(history)
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
