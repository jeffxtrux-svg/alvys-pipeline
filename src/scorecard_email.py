"""
Daily KPI scorecard email for XFreight leadership.

Reads the latest pipeline outputs that already live in OneDrive (Alvys Master,
QuickBooks reports, Samsara Master), computes a key-metrics scorecard plus a
short executive overview, and emails an HTML report via Microsoft Graph.

It only READS from OneDrive — it does not re-pull the source APIs, so it never
touches the QuickBooks refresh-token rotation. Schedule it to run shortly after
the morning data refresh.

Run locally:
    python -m src.scorecard_email

Required env (same Azure app as the rest of the pipeline):
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN          OneDrive owner to read the files from
Optional:
    SCORECARD_FROM_UPN         mailbox to send from (default = ONEDRIVE_USER_UPN)
    SCORECARD_TO_EMAILS        comma-separated recipients (default jeff@xfreight.net)
    SCORECARD_ALVYS_PATH       default "Alvys Master.xlsx"
    SCORECARD_QB_DIR           default "QuickBooks"
    SCORECARD_SAMSARA_PATH     default "Samsara/Samsara Master.xlsx"
"""
from __future__ import annotations

import io
import logging
import numbers
import os
import sys
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

from src.onedrive_upload import download_file, get_token

log = logging.getLogger("scorecard_email")
GRAPH = "https://graph.microsoft.com/v1.0"

# Targets pulled from your Goals workbooks
TARGET_RPM = 2.33
TARGET_DEADHEAD = 0.075

ALVYS_DATE_CANDIDATES = ["Dispatched Date", "Invoiced Date", "Created", "Scheduled Pickup"]


# ----------------------------------------------------------------------
# Formatting helpers (always return a safe string)
# ----------------------------------------------------------------------
def _isnum(x) -> bool:
    # numbers.Number covers Python int/float AND numpy int64/float64 scalars
    return isinstance(x, numbers.Number) and not isinstance(x, bool) and bool(pd.notna(x))


def money(x) -> str:
    return f"${x:,.0f}" if _isnum(x) else "n/a"


def pct(x) -> str:
    return f"{x * 100:.1f}%" if _isnum(x) else "n/a"


def rpm(x) -> str:
    return f"${x:.2f}" if _isnum(x) else "n/a"


def num(x) -> str:
    return f"{x:,.0f}" if _isnum(x) else "n/a"


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Numeric view of a column; all-NaN series if the column is absent."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series([float("nan")] * len(df), index=df.index)


# ----------------------------------------------------------------------
# Alvys operational KPIs
# ----------------------------------------------------------------------
def _alvys_dates(df: pd.DataFrame) -> pd.Series:
    for c in ALVYS_DATE_CANDIDATES:
        if c in df.columns:
            d = pd.to_datetime(df[c], errors="coerce")
            if d.notna().sum() > 0:
                return d
    return pd.Series([pd.NaT] * len(df), index=df.index)


def alvys_window(loads: pd.DataFrame, dates: pd.Series, days: int) -> dict:
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    sub = loads[dates >= cutoff]
    if "Load Status" in sub.columns:
        sub = sub[sub["Load Status"].astype(str).str.lower() != "cancelled"]

    revenue = _col(sub, "Customer Revenue").sum()
    loaded = _col(sub, "Loaded Miles").sum()
    empty = _col(sub, "Empty Miles").sum()
    total = loaded + empty
    if "Gross Margin" in sub.columns:
        margin = _col(sub, "Gross Margin").sum()
    else:
        margin = revenue - _col(sub, "Driver Rate").sum()

    return {
        "loads": len(sub),
        "revenue": revenue if revenue else None,
        "miles": total if total else None,
        "deadhead": (empty / total) if total else None,
        "rpm": (revenue / total) if total else None,
        "margin": margin if margin else None,
        "margin_pct": (margin / revenue) if revenue else None,
    }


def compute_alvys(sheets: dict[str, pd.DataFrame]) -> dict | None:
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        log.warning("Alvys Loads sheet missing/empty")
        return None
    dates = _alvys_dates(loads)
    return {"7d": alvys_window(loads, dates, 7), "30d": alvys_window(loads, dates, 30)}


# ----------------------------------------------------------------------
# QuickBooks financial KPIs
# ----------------------------------------------------------------------
def compute_qb_pnl(df: pd.DataFrame) -> dict:
    label = "Account" if "Account" in df.columns else df.columns[-2]
    amount = "Total" if "Total" in df.columns else df.columns[-1]
    out: dict[str, dict] = {}
    for company, g in df.groupby("Company"):
        def grab(phrase: str):
            m = g[g[label].astype(str).str.strip() == phrase]
            if m.empty:
                return None
            return pd.to_numeric(m[amount], errors="coerce").dropna().iloc[-1] if len(
                pd.to_numeric(m[amount], errors="coerce").dropna()
            ) else None

        income = grab("Total Income")
        cogs = grab("Total Cost of Goods Sold")
        opex = grab("Total Expenses")
        net = grab("Net Income")
        op_ratio = (((cogs or 0) + (opex or 0)) / income) if income else None
        out[str(company)] = {"income": income, "net": net, "op_ratio": op_ratio}
    return out


def compute_qb_ar(df: pd.DataFrame) -> dict:
    bal = "Open Balance" if "Open Balance" in df.columns else df.columns[-1]
    out: dict[str, dict] = {}
    data = df[df["Row_Type"].astype(str) == "Data"] if "Row_Type" in df.columns else df
    for company, g in data.groupby("Company"):
        total = pd.to_numeric(g[bal], errors="coerce").sum()
        over90 = pd.to_numeric(
            g[g["Section"].astype(str).str.contains("91 or more", na=False)][bal],
            errors="coerce",
        ).sum() if "Section" in g.columns else None
        out[str(company)] = {"ar": total, "ar90": over90}
    return out


# ----------------------------------------------------------------------
# Samsara safety counts (robust counts only)
# ----------------------------------------------------------------------
def compute_samsara(sheets: dict[str, pd.DataFrame]) -> dict:
    def count(name: str):
        df = sheets.get(name)
        return len(df) if df is not None else None

    return {
        "safety_events": count("SafetyEvents"),
        "dvirs": count("DVIRs"),
        "hos_logs": count("HOS_Logs"),
    }


# ----------------------------------------------------------------------
# HTML rendering
# ----------------------------------------------------------------------
def _flag(value, target, lower_is_better) -> str:
    if not _isnum(value) or not _isnum(target):
        return ""
    good = value <= target if lower_is_better else value >= target
    color = "#1a7f37" if good else "#cc0000"
    arrow = "✓" if good else "▲"
    return f"<span style='color:{color};font-weight:bold'> {arrow}</span>"


def build_html(alvys, qb_pnl, qb_ar, samsara, missing) -> str:
    today = datetime.now().strftime("%A, %B %d, %Y")
    L: list[str] = [
        "<div style='font-family:Segoe UI,Arial,sans-serif;color:#222;max-width:720px'>",
        "<h2 style='margin-bottom:0'>XFreight — Daily Scorecard</h2>",
        f"<p style='color:#666;margin-top:4px'>{today}</p>",
    ]

    # ---- Executive overview ----
    L.append("<h3>Executive overview</h3><ul>")
    if alvys:
        w = alvys["7d"]
        L.append(
            f"<li><b>Last 7 days:</b> {num(w['loads'])} loads · {money(w['revenue'])} revenue · "
            f"RPM {rpm(w['rpm'])} (goal ${TARGET_RPM:.2f}) · deadhead {pct(w['deadhead'])} "
            f"(goal ≤{TARGET_DEADHEAD*100:.1f}%) · margin {pct(w['margin_pct'])}</li>"
        )
    if qb_pnl:
        losers = [c for c, v in qb_pnl.items() if _isnum(v["net"]) and v["net"] < 0]
        if losers:
            L.append(
                "<li><b>Watch:</b> negative net income (YTD) at "
                + ", ".join(losers) + ".</li>"
            )
    if qb_ar:
        big90 = [(c, v["ar90"]) for c, v in qb_ar.items() if _isnum(v["ar90"]) and v["ar90"] > 0]
        if big90:
            worst = max(big90, key=lambda t: t[1])
            L.append(f"<li><b>Collections:</b> {money(worst[1])} is 90+ days past due at {worst[0]}.</li>")
    L.append("</ul>")

    # ---- Operational ----
    if alvys:
        L.append("<h3>Operational (Alvys)</h3>")
        L.append("<table border='1' cellpadding='6' cellspacing='0' "
                 "style='border-collapse:collapse;font-size:14px'>")
        L.append("<tr style='background:#f0f0f0'><th align='left'>Metric</th>"
                 "<th>Last 7 days</th><th>Last 30 days</th><th>Goal</th></tr>")
        rows = [
            ("Loads", lambda w: num(w["loads"]), None, None),
            ("Revenue", lambda w: money(w["revenue"]), None, None),
            ("Total miles", lambda w: num(w["miles"]), None, None),
            ("Revenue / mile", lambda w: rpm(w["rpm"]) + _flag(w["rpm"], TARGET_RPM, False),
             None, f"${TARGET_RPM:.2f}"),
            ("Deadhead %", lambda w: pct(w["deadhead"]) + _flag(w["deadhead"], TARGET_DEADHEAD, True),
             None, f"≤{TARGET_DEADHEAD*100:.1f}%"),
            ("Gross margin %", lambda w: pct(w["margin_pct"]), None, None),
        ]
        for label, fn, _, goal in rows:
            L.append(
                f"<tr><td>{label}</td><td align='right'>{fn(alvys['7d'])}</td>"
                f"<td align='right'>{fn(alvys['30d'])}</td><td align='center'>{goal or ''}</td></tr>"
            )
        L.append("</table>")

    # ---- Financial ----
    if qb_pnl or qb_ar:
        L.append("<h3>Financial — YTD by entity (QuickBooks)</h3>")
        L.append("<table border='1' cellpadding='6' cellspacing='0' "
                 "style='border-collapse:collapse;font-size:14px'>")
        L.append("<tr style='background:#f0f0f0'><th align='left'>Entity</th><th>Revenue</th>"
                 "<th>Net income</th><th>Op. ratio</th><th>Open AR</th><th>AR 90+</th></tr>")
        companies = sorted(set(list(qb_pnl) + list(qb_ar)))
        for c in companies:
            p = qb_pnl.get(c, {})
            a = qb_ar.get(c, {})
            net = p.get("net")
            net_color = "#cc0000" if _isnum(net) and net < 0 else "#222"
            L.append(
                f"<tr><td>{c}</td><td align='right'>{money(p.get('income'))}</td>"
                f"<td align='right' style='color:{net_color}'>{money(net)}</td>"
                f"<td align='right'>{pct(p.get('op_ratio'))}</td>"
                f"<td align='right'>{money(a.get('ar'))}</td>"
                f"<td align='right'>{money(a.get('ar90'))}</td></tr>"
            )
        L.append("</table>")

    # ---- Safety ----
    if samsara:
        L.append("<h3>Safety (Samsara, recent window)</h3><ul>")
        L.append(f"<li>Safety events: {num(samsara['safety_events'])}</li>")
        L.append(f"<li>DVIRs: {num(samsara['dvirs'])}</li>")
        L.append(f"<li>HOS log entries: {num(samsara['hos_logs'])}</li>")
        L.append("</ul><p style='color:#666;font-size:12px'>Detailed fault-code / "
                 "unresolved-defect alerts are sent separately by the fleet alert job.</p>")

    if missing:
        L.append("<p style='color:#a15c00;font-size:12px'>Note: could not read "
                 + ", ".join(missing) + " from OneDrive this run — those sections may be blank.</p>")

    L.append("<hr><p style='color:#888;font-size:12px'>Generated automatically by the "
             "XFreight data pipeline. Figures are point-in-time from the latest data refresh.</p>")
    L.append("</div>")
    return "\n".join(L)


# ----------------------------------------------------------------------
# Email send (Microsoft Graph)
# ----------------------------------------------------------------------
def send_email(token: str, from_upn: str, to_emails: list[str], subject: str, html: str) -> None:
    url = f"{GRAPH}/users/{from_upn}/sendMail"
    message = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to_emails],
    }
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": message},
        timeout=30,
    )
    if resp.status_code == 202:
        log.info("Scorecard email sent to: %s", ", ".join(to_emails))
    else:
        log.error("sendMail failed [%s]: %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()


def _safe_read(token: str, upn: str, path: str, missing: list[str], label: str):
    try:
        return pd.read_excel(io.BytesIO(download_file(token, upn, path)), sheet_name=None)
    except Exception as exc:
        log.warning("Could not read %s (%s): %s", label, path, exc)
        missing.append(label)
        return None


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
    to_emails = [e.strip() for e in os.environ.get("SCORECARD_TO_EMAILS", "jeff@xfreight.net").split(",") if e.strip()]

    alvys_path = os.environ.get("SCORECARD_ALVYS_PATH", "Alvys Master.xlsx")
    qb_dir = os.environ.get("SCORECARD_QB_DIR", "QuickBooks").strip("/")
    samsara_path = os.environ.get("SCORECARD_SAMSARA_PATH", "Samsara/Samsara Master.xlsx")

    token = get_token(tenant, client, secret)
    missing: list[str] = []

    alvys_sheets = _safe_read(token, upn, alvys_path, missing, "Alvys Master")
    pnl_sheets = _safe_read(token, upn, f"{qb_dir}/QB_ProfitAndLoss.xlsx", missing, "QB P&L")
    ar_sheets = _safe_read(token, upn, f"{qb_dir}/QB_AgedReceivableDetail.xlsx", missing, "QB AR aging")
    samsara_sheets = _safe_read(token, upn, samsara_path, missing, "Samsara Master")

    alvys = compute_alvys(alvys_sheets) if alvys_sheets else None
    qb_pnl = compute_qb_pnl(next(iter(pnl_sheets.values()))) if pnl_sheets else {}
    qb_ar = compute_qb_ar(next(iter(ar_sheets.values()))) if ar_sheets else {}
    samsara = compute_samsara(samsara_sheets) if samsara_sheets else None

    html = build_html(alvys, qb_pnl, qb_ar, samsara, missing)
    subject = f"XFreight Daily Scorecard — {datetime.now():%b %d, %Y}"
    send_email(token, from_upn, to_emails, subject, html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
