"""
Daily executive brief email for XFreight leadership.

Reads the latest pipeline outputs that already live in OneDrive (Alvys Master
2026, QuickBooks reports + AR history, Samsara Master), computes a multi-page
executive brief, and emails an HTML report via Microsoft Graph.

It only READS from OneDrive — it does not re-pull the source APIs, so it never
touches the QuickBooks refresh-token rotation. Schedule it to run shortly after
the morning data refresh.

Layout (see also the design previews):
  Page 1 — KPI tiles, bottom line, AR 6-month trend chart, P&L by entity,
           safety 24h/7d/MTD tiles, safety 6-month trend charts.
  Page 2 — safety & compliance detail, LAST 24 HOURS only.
  Page 3 — AR overdue, 31+ days only.

Run locally:
    python -m src.scorecard_email

Required env (same Azure app as the rest of the pipeline):
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN          OneDrive owner to read the files from
Optional:
    SCORECARD_FROM_UPN         mailbox to send from (default = ONEDRIVE_USER_UPN)
    SCORECARD_TO_EMAILS        comma-separated recipients (default jeff@xfreight.net)
    SCORECARD_ALVYS_PATH       default "Alvys Master 2026.xlsx"
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
TARGET_OR = 0.95
COACH_EVENT_THRESHOLD = 2  # drivers with >= this many safety events in window need coaching

# Power BI's XFreight Report filters by Scheduled Pickup, so match that for MTD/window math.
ALVYS_DATE_CANDIDATES = [
    "Scheduled Pickup", "Dispatched Date", "Invoiced Date", "Delivered",
    "Delivery Date", "Created", "Scheduled Delivery",
]

# ----------------------------------------------------------------------
# Formatting helpers (always return a safe string)
# ----------------------------------------------------------------------
def _isnum(x) -> bool:
    return isinstance(x, numbers.Number) and not isinstance(x, bool) and bool(pd.notna(x))


def money(x) -> str:
    return f"${x:,.0f}" if _isnum(x) else "n/a"


def money_m(x) -> str:
    if not _isnum(x):
        return "n/a"
    return f"${x/1e6:.2f}M" if abs(x) >= 1e6 else f"${x/1e3:.0f}K"


def pct(x) -> str:
    return f"{x * 100:.1f}%" if _isnum(x) else "n/a"


def rpm(x) -> str:
    return f"${x:.2f}" if _isnum(x) else "n/a"


def num(x) -> str:
    return f"{x:,.0f}" if _isnum(x) else "n/a"


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce")
    return pd.Series([float("nan")] * len(df), index=df.index)


def _col_any(df: pd.DataFrame, names: list[str]) -> pd.Series:
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce")
    return pd.Series([float("nan")] * len(df), index=df.index)


def _find_col(df: pd.DataFrame, needles: list[str]) -> str | None:
    """First column whose lowercased name contains one of the needle substrings."""
    for needle in needles:
        for c in df.columns:
            if needle in str(c).lower():
                return c
    return None


def _dates(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for c in candidates:
        if c in df.columns:
            d = pd.to_datetime(df[c], errors="coerce")
            if d.notna().sum() > 0:
                return d
    # fuzzy fallback: any column that looks like a date/time
    fuzzy = _find_col(df, ["date", "time", "reported"])
    if fuzzy:
        return pd.to_datetime(df[fuzzy], errors="coerce")
    return pd.Series([pd.NaT] * len(df), index=df.index)


def _last_6_months() -> list[tuple[int, int]]:
    today = pd.Timestamp.now()
    out: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(6):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    out.reverse()
    return out


def _monthly_counts(dates: pd.Series) -> tuple[list[str], list[int]]:
    d = pd.to_datetime(dates, errors="coerce").dropna()
    labels, counts = [], []
    months = _last_6_months()
    for i, (yy, mm) in enumerate(months):
        c = int(((d.dt.year == yy) & (d.dt.month == mm)).sum()) if len(d) else 0
        lab = pd.Timestamp(year=yy, month=mm, day=1).strftime("%b")
        if i == len(months) - 1:
            lab += "*"
        labels.append(lab)
        counts.append(c)
    return labels, counts


# ----------------------------------------------------------------------
# Window helpers
# ----------------------------------------------------------------------
def _windows() -> dict[str, pd.Timestamp]:
    now = pd.Timestamp.now()
    return {
        "now": now,
        "24h": now - pd.Timedelta(hours=24),
        "7d": now.normalize() - pd.Timedelta(days=7),
        "30d": now.normalize() - pd.Timedelta(days=30),
        "mtd": now.normalize().replace(day=1),
    }


# ----------------------------------------------------------------------
# Alvys operational KPIs (from the manual Alvys Master 2026 file)
# ----------------------------------------------------------------------
def _alvys_metrics(sub: pd.DataFrame) -> dict:
    revenue = _col_any(sub, ["Customer Revenue", "Revenue"]).sum()
    loaded = _col_any(sub, ["Loaded Dispatch Mileage", "Loaded Mileage", "Loaded Miles"]).sum()
    empty = _col_any(sub, ["Empty Dispatch Mileage", "Empty Mileage", "Empty Miles"]).sum()
    # Power BI's "Dispatch Mileage" basis = the Total Dispatch Mileage column (Rev/Mile & Dead Head %).
    total_col = _col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage", "Total Miles", "Total Mileage"])
    total = total_col.sum() if total_col.notna().any() else (loaded + empty)
    # Gross margin = revenue - (driver + carrier). Fuel is already inside those rates.
    driver = _col(sub, "Driver Rate").fillna(0)
    carrier = _col_any(sub, ["Carrier Rate", "Posted Carrier Rate"]).fillna(0)
    cost = float((driver + carrier).sum())
    margin = revenue - cost
    return {
        "loads": len(sub),
        "revenue": revenue if revenue else None,
        "miles": total if total else None,
        "empty": empty if empty else None,
        "deadhead": (empty / total) if total else None,
        "rpm": (revenue / total) if total else None,
        "margin": margin if margin else None,
        "margin_pct": (margin / revenue) if revenue else None,
    }


def compute_alvys(sheets: dict[str, pd.DataFrame] | None) -> dict | None:
    if not sheets:
        return None
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        log.warning("Alvys Loads sheet missing/empty")
        return None
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    if "Load Status" in loads.columns:
        loads = loads[loads["Load Status"].astype(str).str.lower() != "cancelled"]
        dates = dates.loc[loads.index]
    w = _windows()
    win_specs = (("24h", w["24h"]), ("7d", w["7d"]), ("30d", w["30d"]), ("mtd", w["mtd"]))
    out = {key: _alvys_metrics(loads[dates >= start]) for key, start in win_specs}

    # RPM and deadhead are asset-carrier metrics — compute an X-Trux/XFreight-only
    # variant (exclude X-Linx brokerage) for those tiles.
    office_col = _find_col(loads, ["invoice as", "invoiced as", "office", "tender as"])
    if office_col:
        is_asset = loads[office_col].map(_entity_group) == "X-Trux"
        a_loads, a_dates = loads[is_asset], dates[is_asset]
        out["asset"] = {key: _alvys_metrics(a_loads[a_dates >= start]) for key, start in win_specs}
        # Fleet metrics (X-Trux/XFreight, MTD): active trucks + miles per truck.
        a_mtd = a_loads[a_dates >= w["mtd"]]
        truck_col = _find_col(a_loads, ["truck"])
        active = None
        if truck_col:
            tv = a_mtd[truck_col].dropna().astype(str).str.strip()
            tv = tv[(tv != "") & (tv.str.lower() != "nan") & (tv != "0")]
            active = int(tv.nunique())
        miles_mtd = out["asset"]["mtd"]["miles"]
        out["fleet"] = {
            "active_trucks": active,
            "miles": miles_mtd,
            "miles_per_truck": (miles_mtd / active) if (active and miles_mtd) else None,
        }
    return out


# Per-entity split. XFreight and X-Trux are combined into one "X-Trux" line on
# all reporting; X-Linx (brokerage) is reported separately.
ENTITY_ORDER = ["X-Trux", "X-Linx"]


def _entity_group(office) -> str | None:
    s = str(office).upper()
    if "LINX" in s:
        return "X-Linx"
    if "TRUX" in s or "FREIGHT" in s:  # X-Trux + XFreight combined
        return "X-Trux"
    return None


def compute_alvys_entities(sheets: dict[str, pd.DataFrame] | None, window_key: str = "mtd") -> dict:
    """Revenue / cost / margin by entity (X-Trux incl. XFreight, X-Linx)."""
    if not sheets:
        return {}
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        return {}
    office_col = _find_col(loads, ["invoice as", "invoiced as", "office", "tender as"])
    if not office_col:
        return {}
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    mask = pd.Series(True, index=loads.index)
    if "Load Status" in loads.columns:
        mask &= loads["Load Status"].astype(str).str.lower() != "cancelled"
    mask &= dates >= _windows()[window_key]
    sub = loads[mask]
    groups = sub[office_col].map(_entity_group)
    out: dict[str, dict] = {}
    for ent in ENTITY_ORDER:
        rows = sub[groups == ent]
        if rows.empty:
            out[ent] = {"revenue": None, "cost": None, "margin": None, "margin_pct": None}
            continue
        rev_series = _col_any(rows, ["Customer Revenue", "Revenue"])
        revenue = rev_series.sum()
        rev_loads = int((rev_series.fillna(0) > 0).sum())  # revenue loads only
        # Fuel is already embedded in driver rate / carrier rate — do not add it again.
        driver = _col(rows, "Driver Rate").fillna(0)
        carrier = _col_any(rows, ["Carrier Rate", "Posted Carrier Rate"]).fillna(0)
        driver_sum, carrier_sum = float(driver.sum()), float(carrier.sum())
        cost = driver_sum + carrier_sum
        margin = revenue - cost
        out[ent] = {
            "revenue": revenue or None,
            "cost": cost or None,
            "margin": margin if revenue else None,
            "margin_pct": (margin / revenue) if revenue else None,
            "driver": driver_sum or None,
            "carrier": carrier_sum or None,
            "loads": rev_loads,
        }
    return out


# ----------------------------------------------------------------------
# QuickBooks financial KPIs
# ----------------------------------------------------------------------
def compute_alvys_ar(sheets: dict[str, pd.DataFrame] | None) -> dict:
    """Compute AR aging from Alvys pipeline Loads: balance = Customer Revenue − Customer Payments.

    Requires the pipeline-generated file (not the hand-maintained master) because
    it carries the Customer Payments (TotalPaid.Amount) column.  Returns {} if
    required columns are absent or no outstanding balance exists.

    Age buckets are days past the Customer Due Date (negative/zero = still current).
    """
    if not sheets:
        return {}
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        return {}

    rev_col  = _find_col(loads, ["customer revenue", "revenue"])
    paid_col = _find_col(loads, ["customer payments", "payments", "total paid"])
    due_col  = _find_col(loads, ["customer due date", "due date"])
    inv_col  = _find_col(loads, ["invoiced date", "invoice date"])

    if not rev_col or not paid_col:
        return {}   # can't compute balance without payment data

    sub = loads.copy()
    if "Load Status" in sub.columns:
        sub = sub[sub["Load Status"].astype(str).str.lower() != "cancelled"]

    rev     = pd.to_numeric(sub[rev_col],  errors="coerce").fillna(0)
    paid    = pd.to_numeric(sub[paid_col], errors="coerce").fillna(0)
    balance = (rev - paid).clip(lower=0)

    has_bal = balance > 0.01
    if not has_bal.any():
        return {}

    sub     = sub[has_bal].copy()
    balance = balance[has_bal]

    today = pd.Timestamp.now().normalize()
    if due_col and due_col in sub.columns:
        due = pd.to_datetime(sub[due_col], errors="coerce")
    elif inv_col and inv_col in sub.columns:
        due = pd.to_datetime(sub[inv_col], errors="coerce") + pd.Timedelta(days=30)
    else:
        return {"total": float(balance.sum())}

    age = (today - due).dt.days.fillna(0).clip(lower=0).astype(int)

    current = float(balance[age == 0].sum())
    d1_30   = float(balance[(age >= 1)  & (age <= 30)].sum())
    d31_60  = float(balance[(age >= 31) & (age <= 60)].sum())
    d61_90  = float(balance[(age >= 61) & (age <= 90)].sum())
    d91plus = float(balance[age >= 91].sum())
    total   = float(balance.sum())

    return {
        "total":   total,
        "current": current,
        "d1_30":   d1_30,
        "d31_60":  d31_60,
        "d61_90":  d61_90,
        "d91plus": d91plus,
        "overdue": d1_30 + d31_60 + d61_90 + d91plus,
    }


def compute_qb_pnl(df: pd.DataFrame) -> dict:
    label = "Account" if "Account" in df.columns else df.columns[-2]
    amount = "Total" if "Total" in df.columns else df.columns[-1]
    out: dict[str, dict] = {}
    for company, g in df.groupby("Company"):
        def grab(phrase: str):
            m = g[g[label].astype(str).str.strip() == phrase]
            if m.empty:
                return None
            vals = pd.to_numeric(m[amount], errors="coerce").dropna()
            return vals.iloc[-1] if len(vals) else None

        income = grab("Total Income")
        cogs = grab("Total Cost of Goods Sold")
        opex = grab("Total Expenses")
        net = grab("Net Income")
        op_ratio = (((cogs or 0) + (opex or 0)) / income) if income else None
        out[str(company)] = {
            "income": income, "cogs": cogs, "opex": opex, "net": net, "op_ratio": op_ratio,
        }
    return out


def qb_company_totals(qb_pnl: dict) -> dict:
    income = sum(v["income"] for v in qb_pnl.values() if _isnum(v.get("income")))
    cogs = sum(v["cogs"] for v in qb_pnl.values() if _isnum(v.get("cogs")))
    opex = sum(v["opex"] for v in qb_pnl.values() if _isnum(v.get("opex")))
    net = sum(v["net"] for v in qb_pnl.values() if _isnum(v.get("net")))
    return {
        "income": income or None,
        "net": net or None,
        "op_ratio": ((cogs + opex) / income) if income else None,
    }


# --- AR aging detail (page 3, 31+ only) --------------------------------
# Customer/vendor names excluded from AR aging tables and totals.
# Use lowercase; matching is case-insensitive prefix (so "JW Logistics LLC" also matches).
_AR_DETAIL_EXCLUDE: frozenset[str] = frozenset({"jw logistics"})


def _ar_bucket(section: str) -> str | None:
    s = str(section).lower()
    if "31" in s and "60" in s:
        return "31&ndash;60"
    if "61" in s and "90" in s:
        return "61&ndash;90"
    if "91" in s or "and over" in s or ("over" in s and "90" in s):
        return "91+"
    return None  # Current / 1-30 excluded


def compute_qb_ar_detail(df: pd.DataFrame) -> dict:
    data = df[df["Row_Type"].astype(str) == "Data"] if "Row_Type" in df.columns else df
    amt_col = _find_col(df, ["open balance", "amount", "balance"]) or df.columns[-1]
    cust_col = _find_col(df, ["customer", "name"])
    date_col = _find_col(df, ["date"])
    due_col = _find_col(df, ["due"])
    num_col = _find_col(df, ["num", "invoice", "transaction #"])

    # Build a boolean mask excluding customers in _AR_DETAIL_EXCLUDE.
    if cust_col and cust_col in data.columns and _AR_DETAIL_EXCLUDE:
        excl_mask = data[cust_col].astype(str).str.strip().str.lower().apply(
            lambda n: any(n.startswith(e) for e in _AR_DETAIL_EXCLUDE)
        )
        data = data[~excl_mask]

    rows: list[dict] = []
    totals = {"31&ndash;60": 0.0, "61&ndash;90": 0.0, "91+": 0.0}
    for _, r in data.iterrows():
        bucket = _ar_bucket(r.get("Section", ""))
        if bucket is None:
            continue
        amt = pd.to_numeric(pd.Series([r.get(amt_col)]), errors="coerce").iloc[0]
        if not _isnum(amt) or amt == 0:
            continue
        totals[bucket] += float(amt)
        rows.append({
            "customer": str(r.get(cust_col, "")) if cust_col else "",
            "invoice": str(r.get(num_col, "")) if num_col else "",
            "date": str(r.get(date_col, "")) if date_col else "",
            "due": str(r.get(due_col, "")) if due_col else "",
            "amount": float(amt),
            "bucket": bucket,
        })
    rows.sort(key=lambda x: ({"31&ndash;60": 0, "61&ndash;90": 1, "91+": 2}[x["bucket"]], -x["amount"]))
    total_ar = pd.to_numeric(data[amt_col], errors="coerce").dropna().sum() if amt_col in data.columns else None
    return {"rows": rows, "totals": totals, "total31": sum(totals.values()),
            "total_ar": float(total_ar) if _isnum(total_ar) else None}


def compute_balance_history(df: pd.DataFrame | None, value_col: str = "Total_AR") -> tuple[list[str], list[float]]:
    if df is None or df.empty or "AsOf" not in df.columns or value_col not in df.columns:
        return [], []
    g = df.groupby("AsOf")[value_col].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum()
    )
    g = g.sort_index().tail(6)
    labels, values = [], []
    items = list(g.items())
    for i, (ym, v) in enumerate(items):
        try:
            lab = pd.Timestamp(ym + "-01").strftime("%b")
        except Exception:
            lab = str(ym)
        if i == len(items) - 1:
            lab += "*"
        labels.append(lab)
        values.append(float(v))
    return labels, values


# ----------------------------------------------------------------------
# Samsara safety & compliance
# ----------------------------------------------------------------------
SAFETY_DATE = ["time", "Event Time", "Time", "occurredAtTime", "startTime", "Start Time"]
HOSV_DATE = ["startTime", "Start Time", "violationStartTime", "time", "Time"]
DVIR_DATE = ["Reported", "createdAtMs", "createdAt"]


def _count_windows(dates: pd.Series) -> dict:
    w = _windows()
    d = pd.to_datetime(dates, errors="coerce")
    return {
        "24h": int((d >= w["24h"]).sum()),
        "7d": int((d >= w["7d"]).sum()),
        "mtd": int((d >= w["mtd"]).sum()),
    }


def _coaching_by_window(events: pd.DataFrame, driver_col: str, dates: pd.Series) -> dict:
    """Count drivers exceeding the safety-event threshold, per window."""
    w = _windows()
    d = pd.to_datetime(dates, errors="coerce")
    out = {}
    for key, start in (("24h", w["24h"]), ("7d", w["7d"]), ("mtd", w["mtd"])):
        sub = events[d >= start]
        if driver_col and driver_col in sub.columns and len(sub):
            counts = sub.groupby(sub[driver_col].astype(str)).size()
            out[key] = int((counts >= COACH_EVENT_THRESHOLD).sum())
        else:
            out[key] = 0
    return out


def compute_samsara(sheets: dict[str, pd.DataFrame] | None) -> dict | None:
    if not sheets:
        return None
    events = sheets.get("SafetyEvents")
    hosv = sheets.get("HOS_Violations")
    defects = sheets.get("DVIR_Defects")
    w = _windows()
    out: dict = {"windows": {}, "trend": {}, "detail": {}, "coaching": {"24h": 0, "7d": 0, "mtd": 0}}

    # Safety events
    if events is not None and not events.empty:
        ed = _dates(events, SAFETY_DATE)
        out["windows"]["events"] = _count_windows(ed)
        out["trend"]["events"] = _monthly_counts(ed)
        dcol = _find_col(events, ["driver name", "driver"])
        out["coaching"] = _coaching_by_window(events, dcol, ed)
        out["detail"]["events"] = _detail_rows(
            events[ed >= w["24h"]], ed[ed >= w["24h"]],
            [("driver name", "driver"), ("unit", "vehicle"), ("event type",),
             ("severity",), ("status", "reviewed", "coaching")],
        )

    # HOS violations
    if hosv is not None and not hosv.empty:
        hd = _dates(hosv, HOSV_DATE)
        out["windows"]["hos"] = _count_windows(hd)
        out["trend"]["hos"] = _monthly_counts(hd)
        out["detail"]["hos"] = _detail_rows(
            hosv[hd >= w["24h"]], hd[hd >= w["24h"]],
            [("driver name", "driver"), ("violation type", "type"), ("status",)],
        )

    # DVIR defects (open)
    if defects is not None and not defects.empty:
        dd = _dates(defects, DVIR_DATE)
        resolved = defects["Resolved"] if "Resolved" in defects.columns else pd.Series([False] * len(defects))
        open_mask = ~resolved.astype(bool)
        opd = defects[open_mask]
        opdd = dd[open_mask]
        out["windows"]["dvir"] = _count_windows(opdd)
        out["trend"]["dvir"] = _monthly_counts(dd)
        out["detail"]["dvir"] = _detail_rows(
            opd[opdd >= w["24h"]], opdd[opdd >= w["24h"]],
            [("unit",), ("driver",), ("defect",), ("defect type",), ("resolved",)],
        )

    return out


def _detail_rows(df: pd.DataFrame, dates: pd.Series, fields: list[tuple]) -> list[dict]:
    """Build display rows: each field is a tuple of fuzzy column-name needles."""
    rows: list[dict] = []
    if df is None or df.empty:
        return rows
    d = pd.to_datetime(dates, errors="coerce")
    cols = {needles[0]: _find_col(df, list(needles)) for needles in fields}
    order = df.index
    for idx in order:
        r = df.loc[idx]
        rec = {"time": d.loc[idx].strftime("%H:%M") if pd.notna(d.loc[idx]) else ""}
        for key, col in cols.items():
            rec[key] = str(r.get(col, "")) if col else ""
        rows.append(rec)
    return rows[:25]


# ----------------------------------------------------------------------
# HTML design system
# ----------------------------------------------------------------------
NAVY = "#102a43"; INK = "#1a202c"; MUTE = "#64748b"; LINE = "#e2e8f0"; TILEBG = "#f8fafc"
GOOD = "#15803d"; GOODBG = "#dcfce7"; WARN = "#b45309"; WARNBG = "#fef3c7"
BAD = "#b91c1c"; BADBG = "#fee2e2"; ACCENT = "#dd6b20"; BLUE = "#2b6cb0"
FONT = "font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;"


def _pill(t, k):
    bg = {"good": GOODBG, "warn": WARNBG, "bad": BADBG, "mute": "#eef2f7"}[k]
    fg = {"good": GOOD, "warn": WARN, "bad": BAD, "mute": MUTE}[k]
    return (f"<span style='display:inline-block;background:{bg};color:{fg};font-size:11px;"
            f"font-weight:700;padding:2px 8px;border-radius:10px;white-space:nowrap'>{t}</span>")


def _tile(label, value, sub):
    return (f"<td width='25%' style='padding:6px;' valign='top'><div style='background:{TILEBG};"
            f"border:1px solid {LINE};border-radius:10px;padding:14px 14px 12px;'>"
            f"<div style='font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:{MUTE};font-weight:700;'>{label}</div>"
            f"<div style='font-size:26px;font-weight:800;color:{INK};margin:6px 0 6px;line-height:1;'>{value}</div>"
            f"<div style='font-size:12px;color:{MUTE};'>{sub}</div></div></td>")


def _tile_div(label, value, sub):
    """Tile body without the <td> wrapper, for stacking two tiles in one cell."""
    return (f"<div style='background:{TILEBG};border:1px solid {LINE};border-radius:10px;"
            f"padding:14px 14px 12px;margin-bottom:12px;'>"
            f"<div style='font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:{MUTE};font-weight:700;'>{label}</div>"
            f"<div style='font-size:26px;font-weight:800;color:{INK};margin:6px 0 6px;line-height:1;'>{value}</div>"
            f"<div style='font-size:12px;color:{MUTE};'>{sub}</div></div>")


def _mwtile(label, v24, v7, vmtd, hk="mute"):
    hb = {"good": GOODBG, "warn": WARNBG, "bad": BADBG, "mute": "#eef2f7"}[hk]
    hf = {"good": GOOD, "warn": WARN, "bad": BAD, "mute": MUTE}[hk]
    def c(tag, val, s=False):
        col = INK if s else MUTE
        return (f"<td align='center' style='padding:2px 2px;'><div style='font-size:9px;text-transform:uppercase;"
                f"letter-spacing:.4px;color:{MUTE};'>{tag}</div><div style='font-size:18px;font-weight:800;"
                f"color:{col};line-height:1.1;'>{val}</div></td>")
    return (f"<td width='25%' style='padding:6px;' valign='top'><div style='background:#fff;border:1px solid {LINE};"
            f"border-radius:10px;padding:12px 10px 10px;'><div style='font-size:11px;letter-spacing:.5px;"
            f"text-transform:uppercase;color:{hf};font-weight:700;background:{hb};display:inline-block;"
            f"padding:2px 8px;border-radius:8px;margin-bottom:8px;'>{label}</div>"
            f"<table width='100%' cellpadding='0' cellspacing='0'><tr>{c('24h', v24, True)}{c('7d', v7)}{c('MTD', vmtd)}</tr></table></div></td>")


def _bar_chart(title, months, values, sub="", fmt=str):
    if not months:
        return (f"<td valign='top' style='padding:6px;'><div style='border:1px solid {LINE};border-radius:10px;"
                f"padding:14px;color:{MUTE};font-size:12px;'>{title}: data pending</div></td>")
    maxv = max(values) if max(values) else 1
    H = 84
    bar = lbl = ""
    for i, (m, v) in enumerate(zip(months, values)):
        h = max(int(round(H * v / maxv)), (3 if v > 0 else 0))
        last = (i == len(months) - 1)
        bc = ACCENT if last else BLUE
        bar += (f"<td valign='bottom' align='center' style='padding:0 5px;'>"
                f"<div style='font-size:10.5px;font-weight:700;color:{INK};margin-bottom:3px;white-space:nowrap;'>{fmt(v)}</div>"
                f"<div style='width:22px;height:{h}px;background:{bc};border-radius:3px 3px 0 0;margin:0 auto;'></div></td>")
        lcol = INK if last else MUTE
        lbl += (f"<td align='center' style='font-size:10px;color:{lcol};font-weight:{'700' if last else '400'};"
                f"padding-top:4px;'>{m}</td>")
    return (f"<td valign='top' style='padding:6px;'><div style='border:1px solid {LINE};border-radius:10px;padding:12px 12px 10px;'>"
            f"<div style='font-size:12px;font-weight:800;color:{NAVY};margin-bottom:2px;'>{title}</div>"
            f"<div style='font-size:11px;color:{MUTE};margin-bottom:10px;'>{sub}</div>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='height:{H+22}px;'><tr>{bar}</tr></table>"
            f"<table width='100%' cellpadding='0' cellspacing='0'><tr>{lbl}</tr></table></div></td>")


def _section(t, span=4):
    return (f"<tr><td colspan='{span}' style='padding:18px 6px 6px;'><div style='font-size:13px;font-weight:800;"
            f"letter-spacing:.5px;text-transform:uppercase;color:{NAVY};border-bottom:2px solid {LINE};"
            f"padding-bottom:6px;'>{t}</div></td></tr>")


def _header(sub, pg, date_str):
    return (f"<table width='100%' cellpadding='0' cellspacing='0' style='background:{NAVY};'><tr>"
            f"<td style='padding:18px 24px;'><div style='color:#fff;font-size:20px;font-weight:800;letter-spacing:1px;'>XFREIGHT</div>"
            f"<div style='color:#9fb3c8;font-size:13px;margin-top:2px;'>{sub}</div></td>"
            f"<td align='right' style='padding:18px 24px;color:#9fb3c8;font-size:13px;'>{date_str}<br>"
            f"<span style='color:#637b94;font-size:11px;'>Page {pg} of 3</span></td></tr></table>")


def _th(cells, al):
    return "<tr>" + "".join(
        f"<td align='{a}' style='padding:8px 8px;font-size:10px;text-transform:uppercase;letter-spacing:.4px;"
        f"color:{MUTE};font-weight:700;background:{TILEBG};border-bottom:1px solid {LINE};'>{c}</td>"
        for c, a in zip(cells, al)) + "</tr>"


def _tr(cells, al, acc=None):
    out = ""
    for i, (cc, a) in enumerate(zip(cells, al)):
        col = INK; wt = "400"
        if acc and acc[i]:
            col = {"good": GOOD, "warn": WARN, "bad": BAD, "mute": MUTE}[acc[i]]; wt = "700"
        out += (f"<td align='{a}' style='padding:8px 8px;font-size:12.5px;color:{col};font-weight:{wt};"
                f"border-bottom:1px solid {LINE};'>{cc}</td>")
    return f"<tr>{out}</tr>"


def _table(hc, al, rows, span=4):
    if not rows:
        rows = (f"<tr><td colspan='{len(hc)}' style='padding:12px 8px;color:{MUTE};font-size:12.5px;'>"
                f"None in this window.</td></tr>")
    return (f"<tr><td colspan='{span}' style='padding:0 6px;'><table width='100%' cellpadding='0' cellspacing='0' "
            f"style='border:1px solid {LINE};border-radius:8px;border-collapse:separate;overflow:hidden;'>"
            f"{_th(hc, al)}{rows}</table></td></tr>")


def _brief(text, k="mute"):
    bar = {"good": GOOD, "warn": WARN, "bad": BAD, "mute": ACCENT}[k]
    return (f"<tr><td colspan='4' style='padding:3px 6px;'><div style='border-left:3px solid {bar};background:#fbfdff;"
            f"padding:8px 12px;font-size:13px;color:{INK};line-height:1.45;'>{text}</div></td></tr>")


def _flag_kind(value, target, lower_is_better) -> str:
    if not _isnum(value) or not _isnum(target):
        return "mute"
    good = value <= target if lower_is_better else value >= target
    return "good" if good else "bad"


# ----------------------------------------------------------------------
# Page builders
# ----------------------------------------------------------------------
def build_page1(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, date_str, alvys_ar=None) -> str:
    co = qb_company_totals(qb_pnl) if qb_pnl else {}
    w7 = (alvys or {}).get("7d", {})
    wmtd = (alvys or {}).get("mtd", {})
    w7a = ((alvys or {}).get("asset") or {}).get("7d", w7)  # X-Trux/XFreight only

    fleet = (alvys or {}).get("fleet", {})
    empty_td = "<td width='25%' style='padding:6px;'></td>"
    recv_left = ("<td width='25%' valign='top' style='padding:6px;'>"
                 + _tile_div("Total receivables &middot; AR", money(qb_ar.get("total_ar") if qb_ar else None), _pill("all open AR", "mute"))
                 + _tile_div("AR 31+ overdue", money(qb_ar.get("total31") if qb_ar else None), _pill("see pg 3", "bad"))
                 + "</td>")
    _xt, _xl = (alvys_entities or {}).get("X-Trux", {}), (alvys_entities or {}).get("X-Linx", {})
    # Top-line tiles: X-Trux/XFreight only — matches Power BI's default XFreight + X-Trux view.
    pay_tile = _tile("Driver Rate &middot; MTD", money(_xt.get("driver")),
                     _pill("X-Trux + XFreight", "mute"))
    _xf_loads = (_xt.get("loads") or 0) + (_xl.get("loads") or 0)
    loads_tile = _tile("X-Trux Loads &middot; MTD", num(_xt.get("loads")),
                       _pill("X-Trux + XFreight", "mute"))
    # X-Linx (brokerage) overview tiles: revenue, carrier cost, margin, margin %.
    _xl_rev, _xl_carrier = _xl.get("revenue"), _xl.get("carrier")
    _xl_loads = _xl.get("loads")
    _xl_margin = (_xl_rev - _xl_carrier) if (_isnum(_xl_rev) and _isnum(_xl_carrier)) else _xl.get("margin")
    _xl_mpct = (_xl_margin / _xl_rev) if (_isnum(_xl_rev) and _xl_rev and _isnum(_xl_margin)) else None
    _xl_rpl = (_xl_rev / _xl_loads) if (_isnum(_xl_rev) and _isnum(_xl_loads) and _xl_loads) else None
    _xl_mpl = (_xl_margin / _xl_loads) if (_isnum(_xl_margin) and _isnum(_xl_loads) and _xl_loads) else None
    xlinx_tiles = (_tile("Total loads &middot; MTD", num(_xl_loads), _pill("X-Linx", "mute"))
                   + _tile("Revenue / load &middot; MTD", money(_xl_rpl), _pill("X-Linx", "mute"))
                   + _tile("Margin / load &middot; MTD", money(_xl_mpl), _pill("X-Linx", "mute"))
                   + _tile("Margin % &middot; MTD", pct(_xl_mpct), _pill("X-Linx", "mute")))
    # X-Trux (asset) overview: mileage, loads, revenue/mile, revenue/load.
    _xt_rev = _xt.get("revenue")
    _xt_loads, _xt_miles = _xt.get("loads"), fleet.get("miles")
    _xt_rpm = (_xt_rev / _xt_miles) if (_isnum(_xt_rev) and _isnum(_xt_miles) and _xt_miles) else None
    _xt_rpl = (_xt_rev / _xt_loads) if (_isnum(_xt_rev) and _isnum(_xt_loads) and _xt_loads) else None
    xtrux_r1 = (_tile("X-Trux Mileage &middot; MTD", num(_xt_miles), _pill("X-Trux + XFreight", "mute"))
                + _tile("X-Trux Loads &middot; MTD", num(_xt_loads), _pill("X-Trux + XFreight", "mute"))
                + _tile("Revenue / mile &middot; MTD", rpm(_xt_rpm), _pill("X-Trux", "mute"))
                + _tile("Revenue / load &middot; MTD", money(_xt_rpl), _pill("X-Trux", "mute")))
    _xt_asset = ((alvys or {}).get("asset") or {}).get("mtd", {})
    xtrux_r2 = (_tile("Dead head % &middot; MTD", pct(_xt_asset.get("deadhead")),
                      "goal &le;7.5% " + _pill("DH", _flag_kind(_xt_asset.get("deadhead"), TARGET_DEADHEAD, True)))
                + _tile("Empty miles &middot; MTD", num(_xt_asset.get("empty")), _pill("X-Trux + XFreight", "mute"))
                + _tile("Active trucks &middot; MTD", num(fleet.get("active_trucks")), _pill("X-Trux + XFreight", "mute"))
                + _tile("Avg miles / truck &middot; MTD", num(fleet.get("miles_per_truck")), _pill("X-Trux + XFreight", "mute")))
    margin_tile = _tile("XFreight Margin &middot; MTD", money(_xt.get("margin")), _pill("X-Trux + XFreight", "mute"))
    t1 = (_tile("XFreight Revenue &middot; MTD", money(_xt.get("revenue")), _pill("X-Trux + XFreight", "mute"))
          + pay_tile
          + margin_tile
          + _tile("Gross margin &middot; MTD", pct(_xt.get("margin_pct")), ""))
    t1b = loads_tile + empty_td + empty_td + empty_td

    # AR & AP 6-month balance trend
    ar_labels, ar_vals = ar_hist if ar_hist else ([], [])
    ap_labels, ap_vals = ap_hist if ap_hist else ([], [])
    ar_chart = _bar_chart("AR &mdash; receivable balance", ar_labels, ar_vals,
                          "total open AR by month-end &middot; *as-of", fmt=money_m)
    ap_chart = _bar_chart("AP &mdash; payable balance", ap_labels, ap_vals,
                          "total open AP by month-end &middot; *as-of", fmt=money_m)

    def _dir(vals, noun):
        if not vals:
            return f"{noun} history pending."
        delta = vals[-1] - vals[0]
        return (f"{noun} {'up' if delta > 0 else 'down'} {money_m(abs(delta))} over 6 months "
                f"({money_m(vals[0])} &rarr; {money_m(vals[-1])}).")
    ar_rising = bool(ar_vals and ar_vals[-1] > ar_vals[0])
    ar_insight = _dir(ar_vals, "AR") + " " + _dir(ap_vals, "AP")
    if ar_rising:
        ar_insight += " Receivables growing &mdash; watch the 91+ bucket."

    # Safety tiles + trend charts
    sf = (samsara or {})
    sw = sf.get("windows", {})
    def swv(metric, k):
        return sw.get(metric, {}).get(k, 0)
    safety_tiles = (
        _mwtile("Safety events", swv("events", "24h"), swv("events", "7d"), swv("events", "mtd"), "warn")
        + _mwtile("HOS violations", swv("hos", "24h"), swv("hos", "7d"), swv("hos", "mtd"), "bad")
        + _mwtile("Open DVIR defects", swv("dvir", "24h"), swv("dvir", "7d"), swv("dvir", "mtd"), "warn")
        + _mwtile("Coaching due", sf.get("coaching", {}).get("24h", 0),
                  sf.get("coaching", {}).get("7d", 0), sf.get("coaching", {}).get("mtd", 0), "warn"))
    tr = sf.get("trend", {})
    def chart(metric, title, sub):
        ml = tr.get(metric)
        return _bar_chart(title, ml[0] if ml else [], ml[1] if ml else [], sub)
    safety_charts = (chart("events", "Safety events", "per month &middot; *MTD")
                     + chart("hos", "HOS violations", "per month &middot; *MTD")
                     + chart("dvir", "DVIR defects", "reported/mo &middot; *MTD"))

    # Revenue / cost / margin by entity (Alvys 2026, MTD). XFreight folded into X-Trux.
    entity_rows = ""
    tot_rev = tot_cost = tot_marg = 0.0
    for ent in ENTITY_ORDER:
        e = (alvys_entities or {}).get(ent, {})
        mk = e.get("margin")
        label = ent + (" (incl. XFreight)" if ent == "X-Trux" else " (brokerage)")
        entity_rows += _tr(
            [label, money(e.get("revenue")), money(e.get("cost")), money(mk), pct(e.get("margin_pct"))],
            ["left", "right", "right", "right", "right"],
            [None, None, None, ("bad" if (_isnum(mk) and mk < 0) else "good"), None])
        if _isnum(e.get("revenue")):
            tot_rev += e["revenue"]
        if _isnum(e.get("cost")):
            tot_cost += e["cost"]
        if _isnum(mk):
            tot_marg += mk
    total_pct = (tot_marg / tot_rev) if tot_rev else None
    entity_total = (
        f"<tr><td style='padding:8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>Total</td>"
        f"<td align='right' style='padding:8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>{money(tot_rev or None)}</td>"
        f"<td align='right' style='padding:8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>{money(tot_cost or None)}</td>"
        f"<td align='right' style='padding:8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>{money(tot_marg or None)}</td>"
        f"<td align='right' style='padding:8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>{pct(total_pct)}</td></tr>")

    # Alvys AR aging tiles (from pipeline file — has Customer Payments column).
    aar = alvys_ar or {}
    _aar_61plus = (aar.get("d61_90") or 0) + (aar.get("d91plus") or 0)
    alvys_ar_row = (
        _tile("Alvys AR &middot; Current", money(aar.get("current")), _pill("not overdue", "mute"))
        + _tile("Alvys AR &middot; 1&ndash;30 days", money(aar.get("d1_30")), _pill("past due", "warn"))
        + _tile("Alvys AR &middot; 31&ndash;60 days", money(aar.get("d31_60")), _pill("escalate", "warn"))
        + _tile("Alvys AR &middot; 61+ days", money(_aar_61plus or None), _pill("collections", "bad"))
    ) if aar.get("total") else ""

    bottom = (f"Profitable picture from the latest refresh. RPM {rpm(w7a.get('rpm'))} (goal $2.33), "
              f"deadhead {pct(w7a.get('deadhead'))} (goal &le;7.5%, X-Trux/XFreight). "
              f"{money(qb_ar.get('total31') if qb_ar else None)} is 31+ days overdue (see pg 3). "
              f"Safety: {swv('events', '24h')} events &amp; {swv('hos', '24h')} HOS violations in last 24h.")

    return (f"{_header('Morning Executive Brief', 1, date_str)}"
            f"<div style='padding:18px 24px 4px;'><div style='background:#0f2742;border-radius:10px;padding:14px 18px;"
            f"color:#e6eef7;font-size:14px;line-height:1.5;'><span style='color:{ACCENT};font-weight:800;"
            f"text-transform:uppercase;font-size:11px;letter-spacing:.6px;'>Bottom line</span><br>{bottom}</div></div>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"{_section('XFreight Overview')}"
            f"<tr>{t1}</tr><tr>{t1b}</tr>"
            f"{_section('Revenue / cost / margin by entity &middot; MTD')}"
            f"{_table(['Entity', 'Revenue', 'Cost', 'Margin', 'Margin %'], ['left', 'right', 'right', 'right', 'right'], entity_rows + entity_total)}"
            f"{_section('X-Trux Overview')}<tr>{xtrux_r1}</tr><tr>{xtrux_r2}</tr>"
            f"{_section('X-Linx Overview')}<tr>{xlinx_tiles}</tr>"
            f"{_section('Receivables &amp; payables &mdash; 6-month balance trend')}<tr>{recv_left}{ar_chart}{ap_chart}</tr>"
            f"{_brief(ar_insight, 'bad' if ar_rising else 'good')}"
            + (f"{_section('Alvys AR &mdash; aging by due date &middot; all open invoices')}<tr>{alvys_ar_row}</tr>"
               if alvys_ar_row else "")
            + f"{_section('Safety &amp; compliance &mdash; 24h / 7d / MTD &middot; X-Trux / XFreight fleet')}<tr>{safety_tiles}</tr>"
            + f"{_section('Safety &amp; compliance &mdash; 6-month trend (MTD)')}<tr>{safety_charts}</tr>"
            + f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            + f"Orange bar = current month (MTD, partial). Sources: Alvys Master 2026, QuickBooks, Samsara.</div>")


def build_page2(samsara, date_str) -> str:
    detail = (samsara or {}).get("detail", {})
    win = (samsara or {}).get("windows", {})

    def rows_hos():
        return "".join(_tr([r.get("driver name", ""), r.get("time", ""), r.get("violation type", ""), r.get("status", "")],
                           ["left", "left", "left", "left"], [None, None, "bad", None])
                       for r in detail.get("hos", []))

    def rows_events():
        return "".join(_tr([r.get("driver name", ""), r.get("unit", ""), r.get("time", ""), r.get("event type", ""),
                            r.get("severity", ""), r.get("status", "")],
                           ["left", "left", "left", "left", "left", "left"],
                           [None, None, None, None,
                            ("bad" if str(r.get("severity", "")).lower() == "high" else "warn"), None])
                       for r in detail.get("events", []))

    def rows_dvir():
        return "".join(_tr([r.get("unit", ""), r.get("driver", ""), r.get("time", ""), r.get("defect", ""),
                            r.get("defect type", ""), "Open"],
                           ["left", "left", "left", "left", "left", "left"],
                           [None, None, None, None, "warn", "bad"])
                       for r in detail.get("dvir", []))

    def rows_coach():
        # derived: drivers appearing >= threshold in 24h safety events
        ev = detail.get("events", [])
        by = {}
        for r in ev:
            d = r.get("driver name", "") or "(unknown)"
            by.setdefault(d, []).append(r.get("event type", ""))
        out = ""
        for d, types in by.items():
            if len(types) >= COACH_EVENT_THRESHOLD:
                out += _tr([d, ", ".join(t for t in types if t)[:60], str(len(types)), "Today", "New"],
                           ["left", "left", "right", "left", "left"], [None, None, "bad", None, "warn"])
        return out

    def w(metric, k="24h"):
        return win.get(metric, {}).get(k, 0)

    coach_rows = rows_coach()
    coach_count = coach_rows.count("<tr>")

    return (f"{_header('Safety &amp; Compliance Detail &mdash; last 24h &middot; X-Trux / XFreight fleet', 2, date_str)}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{_tile('Safety events &middot; 24h', num(w('events')), '')}"
            f"{_tile('HOS violations &middot; 24h', num(w('hos')), '')}"
            f"{_tile('Open DVIR defects &middot; 24h', num(w('dvir')), '')}"
            f"{_tile('Coaching flagged &middot; 24h', num(coach_count), '')}</tr>"
            f"{_section('HOS violations &mdash; last 24h')}"
            f"{_table(['Driver', 'Time', 'Violation', 'Status'], ['left', 'left', 'left', 'left'], rows_hos())}"
            f"{_section('Safety events &mdash; last 24h')}"
            f"{_table(['Driver', 'Unit', 'Time', 'Event', 'Severity', 'Status'], ['left', 'left', 'left', 'left', 'left', 'left'], rows_events())}"
            f"{_section('DVIR defects (open) &mdash; reported last 24h')}"
            f"{_table(['Unit', 'Driver', 'Time', 'Defect', 'Type', 'Status'], ['left', 'left', 'left', 'left', 'left', 'left'], rows_dvir())}"
            f"{_section('Coaching flagged &mdash; last 24h')}"
            f"{_table(['Driver', 'Reason', 'Events', 'Flagged', 'Status'], ['left', 'left', 'right', 'left', 'left'], coach_rows)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Last 24 hours only. Source: Samsara (SafetyEvents, HOS_Violations, DVIR_Defects). "
            f"Open defects older than 24h are tracked by the fleet alert job.</div>")


def build_page3(qb_ar, date_str) -> str:
    rows = ""
    for r in (qb_ar or {}).get("rows", []):
        k = "bad" if r["bucket"] == "91+" else "warn"
        rows += _tr([r["customer"], r["invoice"], r["date"], r["due"], money(r["amount"]), r["bucket"]],
                    ["left", "left", "left", "left", "right", "left"],
                    [None, None, None, None, (k if r["bucket"] == "91+" else None), k])
    totals = (qb_ar or {}).get("totals", {})
    total31 = (qb_ar or {}).get("total31")
    total_row = (f"<tr><td colspan='4' style='padding:9px 8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>"
                 f"Total 31+ days overdue</td><td align='right' style='padding:9px 8px;font-weight:800;color:{BAD};"
                 f"border-top:2px solid {LINE};'>{money(total31)}</td><td style='border-top:2px solid {LINE};'></td></tr>")
    return (f"{_header('Accounts Receivable &mdash; Overdue (31+ days)', 3, date_str)}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{_tile('31&ndash;60 days', money(totals.get('31&ndash;60')), _pill('watch', 'warn'))}"
            f"{_tile('61&ndash;90 days', money(totals.get('61&ndash;90')), _pill('escalate', 'warn'))}"
            f"{_tile('91+ days', money(totals.get('91+')), _pill('collections', 'bad'))}"
            f"{_tile('Total 31+', money(total31), _pill('overdue', 'bad'))}</tr>"
            f"{_section('Overdue invoices (31+ days) by customer &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'Invoice', 'Inv date', 'Due date', 'Amount', 'Bucket'], ['left', 'left', 'left', 'left', 'right', 'left'], rows + total_row)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Current and 1&ndash;30 day balances omitted by request. Source: QuickBooks A/R Aging Detail.</div>")


def build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing, alvys_ar=None) -> str:
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    pb = f"<div style='height:18px;background:#eef2f7;'></div>"
    note = ""
    if missing:
        note = (f"<div style='background:{WARNBG};color:{WARN};font-size:12px;padding:8px 24px;'>"
                f"Note: could not read {', '.join(missing)} this run &mdash; those sections may be blank.</div>")
    wrap = lambda inner: f"<div style='max-width:760px;margin:0 auto;background:#fff;'>{inner}</div>"
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'></head>"
            f"<body style='margin:0;background:#eef2f7;{FONT}'>"
            f"{wrap(note + build_page1(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, date_str, alvys_ar=alvys_ar))}{pb}"
            f"{wrap(build_page2(samsara, date_str))}{pb}"
            f"{wrap(build_page3(qb_ar, date_str))}"
            f"</body></html>")


# ----------------------------------------------------------------------
# Orchestration (testable without network)
# ----------------------------------------------------------------------
def build_report(alvys_sheets, pnl_sheets, ar_sheets, ar_hist_sheets, ap_hist_sheets, samsara_sheets, missing,
                 alvys_pipeline_sheets=None) -> str:
    alvys = compute_alvys(alvys_sheets) if alvys_sheets else None
    alvys_entities = compute_alvys_entities(alvys_sheets) if alvys_sheets else {}
    qb_pnl = compute_qb_pnl(next(iter(pnl_sheets.values()))) if pnl_sheets else {}
    qb_ar = compute_qb_ar_detail(next(iter(ar_sheets.values()))) if ar_sheets else {}
    ar_hist = compute_balance_history(next(iter(ar_hist_sheets.values())), "Total_AR") if ar_hist_sheets else ([], [])
    ap_hist = compute_balance_history(next(iter(ap_hist_sheets.values())), "Total_AP") if ap_hist_sheets else ([], [])
    samsara = compute_samsara(samsara_sheets) if samsara_sheets else None
    alvys_ar = compute_alvys_ar(alvys_pipeline_sheets) if alvys_pipeline_sheets else {}
    return build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing, alvys_ar=alvys_ar)


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

    alvys_path = os.environ.get("SCORECARD_ALVYS_PATH", "Alvys Master 2026.xlsx")
    alvys_pipeline_path = os.environ.get("SCORECARD_ALVYS_PIPELINE_PATH", "Alvys Pipeline.xlsx")
    qb_dir = os.environ.get("SCORECARD_QB_DIR", "QuickBooks").strip("/")
    samsara_path = os.environ.get("SCORECARD_SAMSARA_PATH", "Samsara/Samsara Master.xlsx")

    token = get_token(tenant, client, secret)
    missing: list[str] = []

    alvys_sheets = _safe_read(token, upn, alvys_path, missing, "Alvys Master 2026")
    alvys_pipeline_sheets = _safe_read(token, upn, alvys_pipeline_path, missing, "Alvys Pipeline")
    pnl_sheets = _safe_read(token, upn, f"{qb_dir}/QB_ProfitAndLoss.xlsx", missing, "QB P&L")
    ar_sheets = _safe_read(token, upn, f"{qb_dir}/QB_AgedReceivableDetail.xlsx", missing, "QB AR aging")
    ar_hist_sheets = _safe_read(token, upn, f"{qb_dir}/QB_AR_History.xlsx", missing, "QB AR history")
    ap_hist_sheets = _safe_read(token, upn, f"{qb_dir}/QB_AP_History.xlsx", missing, "QB AP history")
    samsara_sheets = _safe_read(token, upn, samsara_path, missing, "Samsara Master")

    html = build_report(alvys_sheets, pnl_sheets, ar_sheets, ar_hist_sheets, ap_hist_sheets, samsara_sheets, missing,
                        alvys_pipeline_sheets=alvys_pipeline_sheets)
    subject = f"XFreight Executive Brief — {datetime.now():%b %d, %Y}"
    send_email(token, from_upn, to_emails, subject, html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
