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

import ast
import io
import json
import logging
import numbers
import os
import re
import sys
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

from src.onedrive_upload import (
    download_file, download_shared_file, get_file_modified, get_shared_modified, get_token,
)

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

# Power BI's report groups by the "Office" slicer (subsidiary: XFreight / X-Linx /
# X-Trux), so prefer the Office column. Invoice As / Tender As are billing-entity
# fallbacks that can differ from Office for brokered loads invoiced under another
# subsidiary — grouping by those would misfile that revenue into the wrong entity.
OFFICE_COL_NEEDLES = ["office", "invoice as", "invoiced as", "tender as"]

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


def _cell(v) -> str:
    """Stringify a cell, mapping pandas nulls (which str() turns into 'nan') to ''."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


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


def _to_naive_dt(series: pd.Series) -> pd.Series:
    """Parse to datetime and drop any timezone (Samsara stamps are tz-aware 'Z',
    but the window boundaries from _windows() are tz-naive — comparing the two
    raises 'Cannot compare tz-naive and tz-aware'). utc=True normalizes mixed
    offsets to UTC; tz_localize(None) then makes it naive UTC."""
    d = pd.to_datetime(series, errors="coerce", utc=True)
    try:
        return d.dt.tz_localize(None)
    except (AttributeError, TypeError):
        return pd.to_datetime(series, errors="coerce")


def _dates(df: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for c in candidates:
        if c in df.columns:
            d = _to_naive_dt(df[c])
            if d.notna().sum() > 0:
                return d
    # fuzzy fallback: any column that looks like a date/time
    fuzzy = _find_col(df, ["date", "time", "reported"])
    if fuzzy:
        return _to_naive_dt(df[fuzzy])
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
    # Everything comes from the Loads tab. Power BI's report sums the Loads
    # columns directly — Driver Rate = SUM(Loads[Driver Rate]) and the mileage
    # measures = SUM(Loads[... Dispatch Mileage]) — and the Loads "Driver Rate"
    # column already holds each load's full settled pay (all its trips
    # aggregated), so no Trips summation is needed to match the report.
    revenue = _col_any(sub, ["Customer Revenue", "Revenue"]).sum()
    loaded = _col_any(sub, ["Loaded Dispatch Mileage", "Loaded Mileage", "Loaded Miles"]).sum()
    empty = _col_any(sub, ["Empty Dispatch Mileage", "Empty Mileage", "Empty Miles"]).sum()
    # Power BI's "Dispatch Mileage" basis = the Total Dispatch Mileage column (Rev/Mile & Dead Head %).
    total_col = _col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage", "Total Miles", "Total Mileage"])
    total = total_col.sum() if total_col.notna().any() else (loaded + empty)
    # Margin = Customer Revenue - Driver Rate, matching Power BI. Carrier Rate is
    # NOT added: the Driver Rate column is the full payout per load already.
    cost = float(_col(sub, "Driver Rate").fillna(0).sum())
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
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
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


def compute_alvys_entities(sheets: dict[str, pd.DataFrame] | None, window_key: str = "mtd",
                           start=None, end=None) -> dict:
    """Revenue / cost / margin by entity (X-Trux incl. XFreight, X-Linx).

    Defaults to the open-ended window starting at `window_key`. Pass explicit
    `start`/`end` (Timestamps) to bound a closed period — used by the parity
    check and tests to compare a single finished month against Power BI.
    """
    if not sheets:
        return {}
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        return {}
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if not office_col:
        return {}
    if start is None:
        start = _windows()[window_key]
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    mask = pd.Series(True, index=loads.index)
    if "Load Status" in loads.columns:
        mask &= loads["Load Status"].astype(str).str.lower() != "cancelled"
    mask &= dates >= start
    if end is not None:
        mask &= dates < end
    sub = loads[mask]
    groups = sub[office_col].map(_entity_group)

    out: dict[str, dict] = {}
    for ent in ENTITY_ORDER:
        rows = sub[groups == ent]
        if rows.empty:
            out[ent] = {"revenue": None, "cost": None, "margin": None, "margin_pct": None,
                        "loads": 0, "unsettled": 0}
            continue
        # Match Power BI: P&L tiles are computed on **settled** loads only (those
        # with Driver Rate > 0). Booked-but-not-yet-dispatched loads carry full
        # customer revenue and $0 driver pay, which inflates margin % during MTD
        # until driver pay lands; excluding them keeps the brief in sync with the
        # Power BI XFreight Report instead of running high mid-month.
        if "Driver Rate" in rows.columns:
            settled_mask = _col(rows, "Driver Rate").fillna(0) > 0
            settled = rows[settled_mask]
        else:
            settled = rows
        n_unsettled = len(rows) - len(settled)
        if settled.empty:
            out[ent] = {"revenue": None, "cost": None, "margin": None, "margin_pct": None,
                        "loads": 0, "unsettled": n_unsettled}
            continue
        revenue = _col_any(settled, ["Customer Revenue", "Revenue"]).sum()
        # Cost = SUM(Loads[Driver Rate]); margin = Customer Revenue - Driver Rate,
        # matching Power BI. The Loads "Driver Rate" column already holds each load's
        # full settled payout, so Carrier Rate is not added separately.
        cost = float(_col(settled, "Driver Rate").fillna(0).sum())
        margin = revenue - cost
        # n_loads matches Power BI's Load Count (non-cancelled, settled).
        n_loads = len(settled)
        out[ent] = {
            "revenue": revenue or None,
            "cost": cost or None,
            "margin": margin if revenue else None,
            "margin_pct": (margin / revenue) if revenue else None,
            "loads": n_loads,
            "unsettled": n_unsettled,
        }
    return out


def _alvys_health(sheets: dict[str, pd.DataFrame] | None) -> list[str]:
    """Structural sanity checks on the Alvys Loads tab.

    The KPI code fails soft — a missing/renamed column makes `_col` return 0,
    which would ship a wrong-but-plausible number (e.g. $0 driver cost → 100%
    margin) with no error. These checks turn that silent failure into a loud
    warning (logged and shown on the email). They are column-presence/emptiness
    checks only, so they don't false-alarm on normal month-to-date partials.
    """
    warns: list[str] = []
    loads = (sheets or {}).get("Loads")
    if loads is None or getattr(loads, "empty", True):
        return warns  # absence is already reported via the `missing` list
    cols = set(loads.columns)
    if not ({"Customer Revenue", "Revenue"} & cols):
        warns.append("Loads tab has no Customer Revenue column — revenue and margin will be blank.")
    if "Driver Rate" not in cols:
        warns.append("Loads tab has no 'Driver Rate' column — driver cost reads $0 and margin is overstated.")
    elif float(_col(loads, "Driver Rate").fillna(0).abs().sum()) == 0:
        warns.append("Loads 'Driver Rate' column is entirely empty — driver cost reads $0 and margin is overstated.")
    if not _find_col(loads, OFFICE_COL_NEEDLES):
        warns.append("Loads tab has no Office / Invoice As column — the X-Trux vs X-Linx split is unavailable.")
    if not (set(ALVYS_DATE_CANDIDATES) & cols):
        warns.append("Loads tab has no Scheduled Pickup date column — MTD windows may be wrong.")
    return warns


# ----------------------------------------------------------------------
# QuickBooks financial KPIs
# ----------------------------------------------------------------------
def compute_alvys_ar(sheets: dict[str, pd.DataFrame] | None) -> dict:
    """Compute AR aging from Alvys pipeline Loads: balance = Customer Revenue − Customer Payments.

    Requires the pipeline-generated file (not the hand-maintained master) because
    it carries the Customer Payments (TotalPaid.Amount) column.  Returns {} if
    required columns are absent or no outstanding balance exists.

    Mirrors QuickBooks' AR basis: only loads that carry an issued customer invoice
    (Invoiced Date present) are counted — un-invoiced loads are revenue, not yet a
    receivable in the books. Age buckets are days past the Customer Due Date
    (negative/zero = still current), falling back to Invoiced Date + 30d (net-30)
    for an invoiced load with no explicit due date.
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

    # Scope to X-Trux (incl. XFreight) + X-Linx so it reconciles with the QB AR,
    # which is limited to the X-Trux Inc / X-Linx Inc company files.
    office_col = _find_col(sub, OFFICE_COL_NEEDLES)
    if office_col:
        sub = sub[sub[office_col].map(_entity_group).isin(ENTITY_ORDER)]

    # Exclude the same customers dropped from the QB AR (e.g. JW Logistics) so the
    # two receivables figures reconcile like-for-like. Uses the exact "Customer"
    # (CustomerName) column, not a substring match — many columns contain "customer".
    cust_col = "Customer" if "Customer" in sub.columns else _find_col(sub, ["customer name"])
    if cust_col and _AR_DETAIL_EXCLUDE:
        sub = sub[~sub[cust_col].apply(_is_ar_excluded)]

    # Match QuickBooks' AR basis: count only loads with an issued customer invoice
    # (Invoiced Date present). Un-invoiced loads aren't a receivable in the books
    # yet, so QB never ages them — including them previously dumped large balances
    # into "Current" and overstated the Alvys figure vs QB.
    if inv_col and inv_col in sub.columns:
        sub = sub[pd.to_datetime(sub[inv_col], errors="coerce").notna()]

    if sub.empty:
        return {}

    rev     = pd.to_numeric(sub[rev_col],  errors="coerce").fillna(0)
    paid    = pd.to_numeric(sub[paid_col], errors="coerce").fillna(0)
    balance = (rev - paid).clip(lower=0)

    has_bal = balance > 0.01
    if not has_bal.any():
        return {}

    sub     = sub[has_bal].copy()
    balance = balance[has_bal]

    today = pd.Timestamp.now().normalize()
    due = (pd.to_datetime(sub[due_col], errors="coerce")
           if due_col and due_col in sub.columns
           else pd.Series(pd.NaT, index=sub.index))
    # QB ages by due date; for an invoiced load missing an explicit due date, fall
    # back to Invoiced Date + 30d (net-30) so it still ages instead of reading current.
    if inv_col and inv_col in sub.columns:
        due = due.fillna(pd.to_datetime(sub[inv_col], errors="coerce") + pd.Timedelta(days=30))

    age = (today - due).dt.days.fillna(0).clip(lower=0).astype(int)

    current = float(balance[age == 0].sum())
    d1_30   = float(balance[(age >= 1)  & (age <= 30)].sum())
    d31_60  = float(balance[(age >= 31) & (age <= 60)].sum())
    d61_90  = float(balance[(age >= 61) & (age <= 90)].sum())
    d91plus = float(balance[age >= 91].sum())
    total   = float(balance.sum())

    # 61+ balance detail (customer + amount + days) so the oldest open balances —
    # the ones most likely already paid in QB — can be spot-checked by name.
    loadno_col = "Load #" if "Load #" in sub.columns else _find_col(sub, ["load #", "load number"])
    mask61 = age >= 61
    rows61: list[dict] = []
    for idx in sub.index[mask61]:
        rows61.append({
            "customer": _cell(sub.at[idx, cust_col]) if cust_col else "",
            "load": _cell(sub.at[idx, loadno_col]) if loadno_col else "",
            "days": int(age.at[idx]),
            "amount": float(balance.at[idx]),
        })
    rows61.sort(key=lambda r: r["amount"], reverse=True)

    # 90+ days rolled up by customer (the worst aged receivables) for the customer page.
    mask91 = age >= 91
    cust91: dict[str, dict] = {}
    for idx in sub.index[mask91]:
        name = (_cell(sub.at[idx, cust_col]) if cust_col else "") or "(no customer name)"
        d = cust91.setdefault(name, {"customer": name, "loads": 0, "amount": 0.0, "oldest_days": 0})
        d["loads"] += 1
        d["amount"] += float(balance.at[idx])
        d["oldest_days"] = max(d["oldest_days"], int(age.at[idx]))
    rows91c = sorted(cust91.values(), key=lambda r: r["amount"], reverse=True)

    # Open AR rolled up by customer (for the QB-vs-Alvys reconciliation by customer).
    by_customer: dict[str, dict] = {}
    if cust_col:
        for idx in sub.index:
            nm = _cell(sub.at[idx, cust_col])
            d = by_customer.setdefault(_norm_name(nm), {"name": nm, "amount": 0.0})
            d["amount"] += float(balance.at[idx])

    # Per-invoice open balances (invoice #, customer, amount, days) for bill-by-bill
    # matching against QB. The Customer Invoice Number column appears once the Alvys
    # pull runs with that mapping; until then this list has blank invoice numbers.
    invno_col = _find_col(sub, ["customer invoice number", "invoice number"])
    open_invoices: list[dict] = []
    for idx in sub.index:
        open_invoices.append({
            "invoice": _cell(sub.at[idx, invno_col]) if invno_col else "",
            "customer": _cell(sub.at[idx, cust_col]) if cust_col else "",
            "load": _cell(sub.at[idx, loadno_col]) if loadno_col else "",
            "amount": float(balance.at[idx]),
            "days": int(age.at[idx]),
        })

    return {
        "total":   total,
        "current": current,
        "d1_30":   d1_30,
        "d31_60":  d31_60,
        "d61_90":  d61_90,
        "d91plus": d91plus,
        "overdue": d1_30 + d31_60 + d61_90 + d91plus,
        "d61plus_rows":  rows61[:12],
        "d61plus_n":     len(rows61),
        "d61plus_total": d61_90 + d91plus,
        "d91plus_customers": rows91c,
        "by_customer":   by_customer,
        "open_invoices": open_invoices,
    }


def compute_alvys_uninvoiced(sheets: dict[str, pd.DataFrame] | None, limit: int = 30) -> dict:
    """Delivered Alvys loads (X-Trux + X-Linx) with no issued customer invoice yet.

    The complement of compute_alvys_ar: earned revenue QuickBooks can't see because
    no invoice exists. These are the loads behind most of the QB-vs-Alvys AR gap —
    the billing backlog to chase. Sorted oldest-delivered first.
    """
    if not sheets:
        return {}
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        return {}

    status_col = "Load Status" if "Load Status" in loads.columns else _find_col(loads, ["load status", "status"])
    inv_col = _find_col(loads, ["invoiced date", "invoice date"])
    if not status_col or not inv_col:
        return {}
    rev_col = _find_col(loads, ["customer revenue", "revenue"])

    sub = loads.copy()
    sub = sub[sub[status_col].astype(str).str.strip().str.lower() == "delivered"]
    sub = sub[pd.to_datetime(sub[inv_col], errors="coerce").isna()]   # not yet invoiced

    office_col = _find_col(sub, OFFICE_COL_NEEDLES)
    if office_col:
        sub = sub[sub[office_col].map(_entity_group).isin(ENTITY_ORDER)]

    cust_col = "Customer" if "Customer" in sub.columns else _find_col(sub, ["customer name"])
    if cust_col and _AR_DETAIL_EXCLUDE:
        sub = sub[~sub[cust_col].apply(_is_ar_excluded)]

    if sub.empty:
        return {"count": 0, "total_revenue": 0.0, "oldest_days": None, "rows": [], "shown": 0}

    rev = pd.to_numeric(sub[rev_col], errors="coerce").fillna(0) if rev_col else pd.Series(0.0, index=sub.index)
    today = pd.Timestamp.now().normalize()
    # Prefer actual last-stop arrival; fall back per-row to Scheduled Delivery when
    # an arrival timestamp is missing (or the column isn't in the file yet).
    act_col = _find_col(sub, ["actual delivery", "arrived"])
    sched_col = _find_col(sub, ["scheduled delivery", "delivery date"])
    delivered = pd.to_datetime(sub[act_col], errors="coerce") if act_col else pd.Series(pd.NaT, index=sub.index)
    if sched_col:
        delivered = delivered.fillna(pd.to_datetime(sub[sched_col], errors="coerce"))
    days = (today - delivered).dt.days
    loadno_col = "Load #" if "Load #" in sub.columns else _find_col(sub, ["load #", "load number", "load id"])

    rows: list[dict] = []
    for idx in sub.index:
        d = days.get(idx)
        dv = delivered.get(idx)
        rows.append({
            "load": _cell(sub.at[idx, loadno_col]) if loadno_col else "",
            "customer": _cell(sub.at[idx, cust_col]) if cust_col else "",
            "entity": (_entity_group(sub.at[idx, office_col]) or "") if office_col else "",
            "delivered": dv.strftime("%m/%d/%Y") if pd.notna(dv) else "",
            "days": int(d) if pd.notna(d) else None,
            "revenue": float(rev.get(idx, 0)),
        })
    rows.sort(key=lambda r: ((r["days"] if r["days"] is not None else -1), r["revenue"]), reverse=True)
    valid_days = [r["days"] for r in rows if r["days"] is not None]
    return {
        "count": len(rows),
        "total_revenue": float(rev.sum()),
        "oldest_days": max(valid_days) if valid_days else None,
        "rows": rows[:limit],
        "shown": min(len(rows), limit),
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

# QuickBooks company files that have an Alvys (TMS) counterpart. All AR reporting
# and the QB-vs-Alvys reconciliation are scoped to these two so the two systems
# compare like-for-like; the other QB companies (Truk-Way Leasing, N&J Trailers,
# N&J Properties) have no Alvys equivalent. Matched case-insensitively on the
# "Company" column. The Alvys side folds the XFreight office into X-Trux.
_AR_COMPANIES: frozenset[str] = frozenset({"x-trux inc", "x-linx inc"})

# XFreight's direct-shipper customers (case-insensitive prefix match on the
# Alvys "Customer" column). When a load is recorded as "SHIPPER / BROKER" the
# underlying shipper wins — "BERRY PLASTICS / CH ROBINSON" still rolls up under
# direct (Berry is in the list); a plain "CH ROBINSON" with no direct shipper
# in the name stays broker.
DIRECT_CUSTOMERS: frozenset[str] = frozenset({
    "abbiamo pasta", "billion", "amcor", "berry", "viaflex", "kozy heat",
    "enertec", "rainbow", "kraft tool", "dakota pottery", "lewis drug",
    "traco", "bandag", "design tanks", "top lot processors",
    "johnson brothers", "innovative",
})


def _is_direct_customer(name) -> bool:
    """True if any "/"-segment of the customer name starts with a DIRECT_CUSTOMERS
    keyword. Handles broker pass-throughs ("SHIPPER / BROKER") by counting the
    load as direct freight whenever the shipper is in the allow-list; broker-only
    names like "CH ROBINSON" with no direct shipper are rejected."""
    n = str(name).strip().lower()
    if not n or n == "nan":
        return False
    segments = [s.strip() for s in n.split("/")]
    return any(seg.startswith(kw) for seg in segments for kw in DIRECT_CUSTOMERS)


def compute_rpm_trend(sheets: dict[str, pd.DataFrame] | None) -> dict:
    """Monthly average Revenue / Mile by direct vs broker freight, last 6 months.

    Each month's average RPM = SUM(Customer Revenue) / SUM(Total Dispatch Mileage)
    over loads in that month (Scheduled Pickup), split into direct customers (per
    DIRECT_CUSTOMERS) and broker freight (everything else). Returns
    ``{"direct": (labels, values), "broker": (labels, values)}`` ready for
    ``_bar_chart``; the current month's label gets a trailing ``*`` to mark MTD.
    Returns empty tuples when the required Loads columns aren't present.
    """
    empty = {"direct": ([], []), "broker": ([], []), "combined": ([], [])}
    if not sheets:
        return empty
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        return empty
    cust_col = "Customer" if "Customer" in loads.columns else _find_col(loads, ["customer name", "customer"])
    rev_col = _find_col(loads, ["customer revenue", "revenue"])
    miles_col = _find_col(loads, ["total dispatch mileage", "dispatch mileage", "loaded dispatch mileage", "mileage"])
    date_col = _find_col(loads, ["scheduled pickup", "pickup date"])
    if not all([cust_col, rev_col, miles_col, date_col]):
        return empty

    sub = loads.copy()
    if "Load Status" in sub.columns:
        sub = sub[sub["Load Status"].astype(str).str.lower() != "cancelled"]
    # Scope to the X-Trux + XFreight asset fleet (matches the X-Trux Overview
    # section where these charts now live; X-Linx brokerage is excluded).
    office_col = _find_col(sub, OFFICE_COL_NEEDLES)
    if office_col:
        sub = sub[sub[office_col].map(_entity_group) == "X-Trux"]
    dates = _to_naive_dt(sub[date_col])
    keep = dates.notna()
    sub = sub.loc[keep]
    dates = dates.loc[keep]
    if sub.empty:
        return empty

    is_direct = sub[cust_col].apply(_is_direct_customer)
    rev = pd.to_numeric(sub[rev_col], errors="coerce").fillna(0)
    miles = pd.to_numeric(sub[miles_col], errors="coerce").fillna(0)

    months = _last_6_months()
    d_labels, d_values = [], []
    b_labels, b_values = [], []
    c_labels, c_values = [], []
    for i, (yy, mm) in enumerate(months):
        in_month = (dates.dt.year == yy) & (dates.dt.month == mm)
        d_mask = in_month & is_direct
        b_mask = in_month & ~is_direct
        d_miles = float(miles[d_mask].sum())
        b_miles = float(miles[b_mask].sum())
        c_miles = float(miles[in_month].sum())
        d_rpm = float(rev[d_mask].sum()) / d_miles if d_miles else 0.0
        b_rpm = float(rev[b_mask].sum()) / b_miles if b_miles else 0.0
        c_rpm = float(rev[in_month].sum()) / c_miles if c_miles else 0.0
        lab = pd.Timestamp(year=yy, month=mm, day=1).strftime("%b")
        if i == len(months) - 1:
            lab += "*"
        d_labels.append(lab); d_values.append(d_rpm)
        b_labels.append(lab); b_values.append(b_rpm)
        c_labels.append(lab); c_values.append(c_rpm)

    return {"direct": (d_labels, d_values), "broker": (b_labels, b_values),
            "combined": (c_labels, c_values)}


def _norm_name(s) -> str:
    """Normalize a customer name for matching: drop periods (so 'J.W.' -> 'jw'),
    turn other punctuation/separators (hyphens, commas, slashes) into spaces, and
    collapse whitespace. 'J.W. Logistics', 'JW-Logistics', 'JW Logistics, LLC'
    all normalize to a string starting 'jw logistics'."""
    s = str(s).lower().replace(".", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def _is_ar_excluded(name) -> bool:
    """True if a customer name matches any _AR_DETAIL_EXCLUDE prefix once normalized.
    Shared by the QB and Alvys AR so both systems drop the same customers."""
    n = _norm_name(name)
    return any(n.startswith(e) for e in _AR_DETAIL_EXCLUDE)


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
    company_col = _find_col(df, ["company"])

    # Scope to the X-Trux Inc / X-Linx Inc company files (drop Truk-Way, N&J).
    if company_col and company_col in data.columns:
        data = data[data[company_col].astype(str).str.strip().str.lower().isin(_AR_COMPANIES)]

    # Build a boolean mask excluding customers in _AR_DETAIL_EXCLUDE.
    if cust_col and cust_col in data.columns and _AR_DETAIL_EXCLUDE:
        data = data[~data[cust_col].apply(_is_ar_excluded)]

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

    # Open AR rolled up by customer across ALL buckets (for the QB-vs-Alvys reconciliation).
    by_customer: dict[str, dict] = {}
    open_invoices: list[dict] = []
    if cust_col and cust_col in data.columns:
        amts = pd.to_numeric(data[amt_col], errors="coerce").fillna(0)
        for _, r in data.iterrows():
            name = str(r.get(cust_col, "")).strip()
            amt = pd.to_numeric(pd.Series([r.get(amt_col)]), errors="coerce").iloc[0]
            if not _isnum(amt):
                continue
            by_customer.setdefault(_norm_name(name), {"name": name, "amount": 0.0})["amount"] += float(amt)
            if abs(float(amt)) >= 0.01:
                open_invoices.append({"invoice": str(r.get(num_col, "")) if num_col else "",
                                      "customer": name, "amount": float(amt)})

    return {"rows": rows, "totals": totals, "total31": sum(totals.values()),
            "total_ar": float(total_ar) if _isnum(total_ar) else None,
            "by_customer": by_customer, "open_invoices": open_invoices}


def compute_ar_reconciliation(qb_ar: dict | None, alvys_ar: dict | None) -> dict:
    """Compare total open AR for X-Trux + X-Linx between QuickBooks (system of
    record) and Alvys (operational TMS). A persistent gap flags a fixable sync
    issue — invoices/payments booked in one system but not yet the other.

    Returns {} unless both totals are available.
    """
    qb = qb_ar.get("total_ar") if qb_ar else None
    alvys = alvys_ar.get("total") if alvys_ar else None
    if not _isnum(qb) or not _isnum(alvys):
        return {}
    delta = qb - alvys
    base = max(abs(qb), abs(alvys), 1.0)
    pct_var = abs(delta) / base
    kind = "good" if pct_var <= 0.01 else "warn" if pct_var <= 0.05 else "bad"
    return {"qb": qb, "alvys": alvys, "delta": delta, "pct": pct_var, "kind": kind}


def compute_ar_customer_reconciliation(qb_ar: dict | None, alvys_ar: dict | None) -> dict:
    """Per-customer QB-vs-Alvys open-AR reconciliation. Joins the two by normalized
    customer name and returns one row per customer with QB AR, Alvys AR, and the
    delta (QB − Alvys). Rows sum exactly to the headline variance; a one-sided row
    (only QB or only Alvys) usually means the customer is spelled differently in the
    two systems. Sorted by largest absolute delta first."""
    qb_by = (qb_ar or {}).get("by_customer") or {}
    al_by = (alvys_ar or {}).get("by_customer") or {}
    if not qb_by and not al_by:
        return {}
    rows: list[dict] = []
    for key in set(qb_by) | set(al_by):
        qb_amt = float(qb_by.get(key, {}).get("amount", 0.0))
        al_amt = float(al_by.get(key, {}).get("amount", 0.0))
        if abs(qb_amt) < 0.01 and abs(al_amt) < 0.01:
            continue
        name = (al_by.get(key) or qb_by.get(key) or {}).get("name") or "(no customer name)"
        rows.append({"customer": name, "qb": qb_amt, "alvys": al_amt, "delta": qb_amt - al_amt})
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return {"rows": rows,
            "qb_total": sum(r["qb"] for r in rows),
            "alvys_total": sum(r["alvys"] for r in rows),
            "delta_total": sum(r["delta"] for r in rows)}


def _norm_inv(s) -> str:
    """Normalize an invoice number for matching: alphanumeric only, then drop a
    leading alpha prefix so QuickBooks' 'T1006199' matches the Alvys load '1006199'
    (and 'INV1001' matches '1001')."""
    s = re.sub(r"[^a-z0-9]", "", str(s).lower()) if s is not None else ""
    return re.sub(r"^[a-z]+", "", s)


def compute_bill_reconciliation(qb_ar: dict | None, alvys_ar: dict | None) -> dict:
    """Bill-by-bill QB-vs-Alvys match. Tries the Alvys invoice number first, then the
    Alvys Load #, and uses whichever actually overlaps QuickBooks' invoice "Num" — so
    it still works if Alvys carries no customer invoice number (Load # is always
    present). Returns invoices open in Alvys but not QB (the gap), open in QB but not
    Alvys, and same-bill amount mismatches.

    available=False only when there's nothing to compare; no_match=True (with sample
    IDs from each side) when neither key overlaps QB, so the formats can be eyeballed."""
    al_inv = (alvys_ar or {}).get("open_invoices") or []
    qb_inv = (qb_ar or {}).get("open_invoices") or []

    qb_by: dict[str, dict] = {}
    for r in qb_inv:
        k = _norm_inv(r.get("invoice"))
        if not k:
            continue
        d = qb_by.setdefault(k, {"invoice": r.get("invoice", ""), "customer": r.get("customer", ""), "amount": 0.0})
        d["amount"] += float(r.get("amount") or 0)
    if not al_inv or not qb_by:
        return {"available": False}

    # Pick the Alvys identifier (invoice # or Load #) that best overlaps QB's Num.
    def _overlap(field):
        return sum(1 for r in al_inv if _norm_inv(r.get(field)) in qb_by)
    inv_ov, load_ov = _overlap("invoice"), _overlap("load")
    key_field = "invoice" if inv_ov >= load_ov else "load"
    best_ov = max(inv_ov, load_ov)

    if best_ov == 0:
        # Couldn't match on either key — surface sample IDs so the formats are visible.
        return {"available": True, "no_match": True, "matched": 0,
                "alvys_sample": [(_cell(r.get("invoice")) or _cell(r.get("load")) or "?") for r in al_inv[:8]],
                "qb_sample": [str(r.get("invoice", "")) for r in qb_inv[:8]],
                "alvys_n": len(al_inv), "qb_n": len(qb_by)}

    al_by: dict[str, dict] = {}
    for r in al_inv:
        k = _norm_inv(r.get(key_field))
        if not k:
            continue
        label = _cell(r.get("invoice")) or _cell(r.get("load"))
        d = al_by.setdefault(k, {"invoice": label, "customer": r.get("customer", ""),
                                 "load": r.get("load", ""), "amount": 0.0, "days": 0})
        d["amount"] += float(r.get("amount") or 0)
        d["days"] = max(d["days"], int(r.get("days") or 0))

    alvys_only, qb_only, mismatch = [], [], []
    for k, a in al_by.items():
        q = qb_by.get(k)
        if q is None:
            alvys_only.append(a)
        elif abs(a["amount"] - q["amount"]) > 1.0:
            mismatch.append({**a, "qb_amount": q["amount"], "diff": a["amount"] - q["amount"]})
    for k, q in qb_by.items():
        if k not in al_by:
            qb_only.append(q)
    alvys_only.sort(key=lambda r: r["amount"], reverse=True)
    qb_only.sort(key=lambda r: r["amount"], reverse=True)
    mismatch.sort(key=lambda r: abs(r["diff"]), reverse=True)
    matched = sum(1 for k in al_by if k in qb_by)
    return {
        "available": True, "no_match": False, "key_used": key_field,
        "alvys_only": alvys_only, "qb_only": qb_only, "mismatch": mismatch,
        "alvys_only_total": sum(r["amount"] for r in alvys_only),
        "qb_only_total": sum(r["amount"] for r in qb_only),
        "mismatch_total": sum(r["diff"] for r in mismatch),
        "matched": matched, "alvys_n": len(al_by), "qb_n": len(qb_by),
    }


def compute_balance_history(df: pd.DataFrame | None, value_col: str = "Total_AR",
                            companies: frozenset[str] | None = None) -> tuple[list[str], list[float]]:
    if df is None or df.empty or "AsOf" not in df.columns or value_col not in df.columns:
        return [], []
    if companies is not None and "Company" in df.columns:
        df = df[df["Company"].astype(str).str.strip().str.lower().isin(companies)]
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
# Driver mileage by settlement week (Page 4)
# ----------------------------------------------------------------------
# Settlement week runs Wed 3:00 PM -> following Wed 2:59 PM, America/Chicago.
CHI_TZ = "America/Chicago"
SETTLEMENT_WEEKS = 4
SETTLEMENT_DOW = 2   # Wednesday (Mon=0)
SETTLEMENT_HOUR = 15  # 3:00 PM


def _parse_alvys_dt(series: pd.Series) -> pd.Series:
    """Parse Alvys timestamps to tz-aware America/Chicago.

    Handles the manual workbook's local 'MM-DD-YYYY @ HH:MM' (naive Central) and
    any ISO tz-aware values (e.g. '...Z'), which are converted from their zone.
    """
    raw = series.astype(str).str.strip()
    cleaned = raw.str.replace(" @ ", " ", regex=False).str.replace("@", " ", regex=False).str.strip()
    dt = pd.to_datetime(cleaned, format="%m-%d-%Y %H:%M", errors="coerce")
    dt = dt.dt.tz_localize(CHI_TZ, ambiguous=False, nonexistent="shift_forward")
    bad = dt.isna() & raw.notna() & (raw.str.lower() != "nan") & (raw != "")
    if bad.any():
        iso = pd.to_datetime(raw[bad], errors="coerce", utc=True).dt.tz_convert(CHI_TZ)
        dt.loc[bad] = iso
    return dt


def _settlement_starts(now: pd.Timestamp, n: int = SETTLEMENT_WEEKS) -> list[pd.Timestamp]:
    """The n week-start boundaries (Wed 3pm Chicago), oldest first, ending with
    the week that currently contains `now`."""
    days_since = (now.weekday() - SETTLEMENT_DOW) % 7
    cur = (now - pd.Timedelta(days=days_since)).normalize() + pd.Timedelta(hours=SETTLEMENT_HOUR)
    if cur > now:
        cur -= pd.Timedelta(weeks=1)
    return [cur - pd.Timedelta(weeks=k) for k in range(n)][::-1]


def _city(city, state) -> str:
    c = "" if city is None or pd.isna(city) else str(city).strip()
    s = "" if state is None or pd.isna(state) else str(state).strip()
    return f"{c}, {s}".strip(", ") if (c or s) else ""


def _ci_get(d, key):
    """Case-insensitive dict lookup (Alvys stop dicts use PascalCase keys)."""
    if not isinstance(d, dict):
        return None
    for k, v in d.items():
        if str(k).lower() == key.lower():
            return v
    return None


def _parse_stops(cell):
    """From a Trips `Stops` JSON cell, pull the leg's first/last stop times and
    locations. The pipeline writes `Stops` as a JSON array of stop dicts; the
    manual workbook stores a plain count (e.g. '1 / 2') which yields None here."""
    if not isinstance(cell, str):
        return None
    s = cell.strip()
    if not s.startswith("["):
        return None
    try:
        stops = json.loads(s)
    except Exception:
        try:
            stops = ast.literal_eval(s)
        except Exception:
            return None
    if not isinstance(stops, list) or not stops:
        return None
    first, last = stops[0], stops[-1]
    def addr(stop):
        a = _ci_get(stop, "Address") or {}
        return _city(_ci_get(a, "City"), _ci_get(a, "State"))
    return {
        "pick_dt": _ci_get(first, "DepartedAt") or _ci_get(first, "ArrivedAt"),
        "drop_dt": _ci_get(last, "ArrivedAt") or _ci_get(last, "DepartedAt"),
        "pick_loc": addr(first),
        "drop_loc": addr(last),
    }


def compute_driver_mileage(sheets: dict[str, pd.DataFrame] | None, now: pd.Timestamp | None = None) -> dict:
    """Per-driver miles by settlement week, at Trips (per-leg) grain.

    Reads the Alvys *pipeline* Trips sheet (API-sourced), where each leg carries
    its own `Stops` JSON. Each leg is credited to its Driver 1 / Truck / Total
    Miles and bucketed by its own actual delivery time (last stop's ArrivedAt,
    falling back to DepartedAt). Start/End uses the leg's first-stop departure and
    last-stop arrival. Cancelled and not-yet-delivered legs are excluded. Asset
    fleet only (X-Trux / XFreight) — brokerage (X-Linx) is carrier-paid.
    """
    if not sheets:
        return {}
    trips = sheets.get("Trips")
    if trips is None or trips.empty or "Stops" not in trips.columns:
        return {}

    now = now or pd.Timestamp.now(tz=CHI_TZ)
    if now.tzinfo is None:
        now = now.tz_localize(CHI_TZ)
    starts = _settlement_starts(now)
    end = starts[-1] + pd.Timedelta(weeks=1)

    parsed = trips["Stops"].map(_parse_stops)
    if not parsed.notna().any():
        return {}  # no JSON stops (e.g. handed the manual workbook by mistake)
    t = trips.copy()
    t["deliv"] = _parse_alvys_dt(parsed.map(lambda p: (p and p.get("drop_dt")) or ""))
    t["pick"] = _parse_alvys_dt(parsed.map(lambda p: (p and p.get("pick_dt")) or ""))
    t["pick_loc"] = parsed.map(lambda p: (p and p.get("pick_loc")) or "")
    t["drop_loc"] = parsed.map(lambda p: (p and p.get("drop_loc")) or "")

    drv = t.get("Driver 1", pd.Series("", index=t.index)).astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    status = t.get("Trip Status", pd.Series("", index=t.index)).astype(str).str.lower()
    office = t.get("Office", pd.Series("", index=t.index)).astype(str).str.upper()
    is_asset = office.str.contains("TRUX") | office.str.contains("FREIGHT")
    valid = (
        (status != "cancelled") & t["deliv"].notna()
        & (t["deliv"] >= starts[0]) & (t["deliv"] < end)
        & (drv != "") & (drv.str.lower() != "nan") & is_asset
    )
    t = t[valid].copy()
    t["drv"] = drv[valid]
    t["miles"] = pd.to_numeric(t.get("Total Miles"), errors="coerce").fillna(0.0)
    t["wk"] = ((t["deliv"] - starts[0]) // pd.Timedelta(weeks=1)).astype(int)

    rows = []
    for name, g in t.groupby("drv"):
        week_miles = [float(g.loc[g["wk"] == k, "miles"].sum()) for k in range(SETTLEMENT_WEEKS)]
        trucks = sorted({str(x).strip() for x in g.get("Truck", pd.Series(dtype=object)).dropna().tolist()
                         if str(x).strip() and str(x).strip().lower() != "nan"})
        cur = g[g["wk"] == SETTLEMENT_WEEKS - 1]
        start_end = ""
        if len(cur):
            s_leg = cur.loc[cur["pick"].idxmin()] if cur["pick"].notna().any() else None
            e_leg = cur.loc[cur["deliv"].idxmax()]
            start_txt = (f"{s_leg['pick_loc']} {s_leg['pick']:%-m/%-d %H:%M}".strip()
                         if s_leg is not None and pd.notna(s_leg["pick"]) else "")
            end_txt = f"{e_leg['drop_loc']} {e_leg['deliv']:%-m/%-d %H:%M}".strip()
            start_end = f"{start_txt} &rarr; {end_txt}" if start_txt else end_txt
        rows.append({
            "driver": name, "trucks": ", ".join(trucks),
            "weeks": week_miles, "total": sum(week_miles), "start_end": start_end,
        })
    rows.sort(key=lambda r: r["total"], reverse=True)

    week_totals = [sum(r["weeks"][k] for r in rows) for k in range(SETTLEMENT_WEEKS)]
    cur_idx = SETTLEMENT_WEEKS - 1
    drivers_cur = sum(1 for r in rows if r["weeks"][cur_idx] > 0)
    return {
        "labels": [_wk_label(s) for s in starts],
        "rows": rows,
        "week_totals": week_totals,
        "grand_total": sum(week_totals),
        "drivers_this_week": drivers_cur,
        "miles_this_week": week_totals[cur_idx],
        "miles_last_week": week_totals[cur_idx - 1] if SETTLEMENT_WEEKS >= 2 else None,
        "avg_per_driver": (week_totals[cur_idx] / drivers_cur) if drivers_cur else None,
    }


def _wk_label(start: pd.Timestamp) -> str:
    end = start + pd.Timedelta(weeks=1) - pd.Timedelta(days=1)  # Wed -> Tue span
    if start.month == end.month:
        return f"{start:%b} {start.day}&ndash;{end.day}"
    return f"{start:%b} {start.day}&ndash;{end:%b} {end.day}"


# ----------------------------------------------------------------------
# HTML design system
# ----------------------------------------------------------------------
NAVY = "#102a43"; INK = "#1a202c"; MUTE = "#64748b"; LINE = "#e2e8f0"; TILEBG = "#f8fafc"
GOOD = "#15803d"; GOODBG = "#dcfce7"; WARN = "#b45309"; WARNBG = "#fef3c7"
PAGE_COUNT = 8
ACCENTBG = "#fff3e8"  # light orange tint for the current settlement week column
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
            f"<span style='color:#637b94;font-size:11px;'>Page {pg} of {PAGE_COUNT}</span></td></tr></table>")


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
def build_page1(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, date_str,
                alvys_ar=None, warnings=None, data_asof=None, rpm_trend=None) -> str:
    co = qb_company_totals(qb_pnl) if qb_pnl else {}
    w7 = (alvys or {}).get("7d", {})
    wmtd = (alvys or {}).get("mtd", {})
    w7a = ((alvys or {}).get("asset") or {}).get("7d", w7)  # X-Trux/XFreight only

    fleet = (alvys or {}).get("fleet", {})
    empty_td = "<td width='25%' style='padding:6px;'></td>"
    recv_left = ("<td width='25%' valign='top' style='padding:6px;'>"
                 + _tile_div("Total receivables &middot; AR", money(qb_ar.get("total_ar") if qb_ar else None), _pill("X-Trux + X-Linx", "mute"))
                 + _tile_div("AR 31+ overdue", money(qb_ar.get("total31") if qb_ar else None), _pill("see pg 3", "bad"))
                 + "</td>")
    _xt, _xl = (alvys_entities or {}).get("X-Trux", {}), (alvys_entities or {}).get("X-Linx", {})
    # Top-line tiles = whole company (X-Trux + X-Linx), matching the entity table's Total row.
    _co_rev = (_xt.get("revenue") or 0) + (_xl.get("revenue") or 0)
    _co_cost = (_xt.get("cost") or 0) + (_xl.get("cost") or 0)
    _co_margin = (_xt.get("margin") or 0) + (_xl.get("margin") or 0)
    _co_mpct = (_co_margin / _co_rev) if _co_rev else None
    _xf_loads = (_xt.get("loads") or 0) + (_xl.get("loads") or 0)
    pay_tile = _tile("XFreight Cost &middot; MTD", money(_co_cost or None),
                     _pill("X-Trux + X-Linx", "mute"))
    loads_tile = _tile("XFreight Loads &middot; MTD", num(_xf_loads or None),
                       _pill("X-Trux + X-Linx", "mute"))
    # X-Linx (brokerage) overview tiles: revenue, cost (driver rate), margin, margin %.
    _xl_rev, _xl_cost = _xl.get("revenue"), _xl.get("cost")
    _xl_loads = _xl.get("loads")
    _xl_margin = (_xl_rev - _xl_cost) if (_isnum(_xl_rev) and _isnum(_xl_cost)) else _xl.get("margin")
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
    margin_tile = _tile("XFreight Margin &middot; MTD", money(_co_margin or None), _pill("revenue &minus; cost", "mute"))
    t1 = (_tile("XFreight Revenue &middot; MTD", money(_co_rev or None), _pill("X-Trux + X-Linx", "mute"))
          + pay_tile
          + margin_tile
          + _tile("Gross margin &middot; MTD", pct(_co_mpct), ""))
    t1b = loads_tile + empty_td + empty_td + empty_td
    # X-Trux Overview row 3: 6-month avg rev / mile trend — overall (X-Trux +
    # XFreight asset fleet) plus a direct-customers vs broker-freight split.
    _rpm_d_labels, _rpm_d_values = ((rpm_trend or {}).get("direct") or ([], []))
    _rpm_b_labels, _rpm_b_values = ((rpm_trend or {}).get("broker") or ([], []))
    _rpm_c_labels, _rpm_c_values = ((rpm_trend or {}).get("combined") or ([], []))
    _rpm_sub = "monthly avg &middot; X-Trux + XFreight &middot; *MTD"
    xtrux_r3 = (_bar_chart("Overall &middot; rev / mile", _rpm_c_labels, _rpm_c_values, _rpm_sub, fmt=rpm)
                + _bar_chart("Direct customers &middot; rev / mile", _rpm_d_labels, _rpm_d_values, _rpm_sub, fmt=rpm)
                + _bar_chart("Broker freight &middot; rev / mile", _rpm_b_labels, _rpm_b_values, _rpm_sub, fmt=rpm)
                + empty_td)

    # AR & AP 6-month balance trend
    ar_labels, ar_vals = ar_hist if ar_hist else ([], [])
    ap_labels, ap_vals = ap_hist if ap_hist else ([], [])
    ar_chart = _bar_chart("AR &mdash; receivable balance", ar_labels, ar_vals,
                          "open AR by month-end &middot; X-Trux + X-Linx &middot; *as-of", fmt=money_m)
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

    # AR reconciliation — QuickBooks (system of record) vs Alvys (TMS), X-Trux + X-Linx.
    recon = compute_ar_reconciliation(qb_ar, alvys_ar)
    recon_row = recon_note = ""
    if recon:
        _d = recon["delta"]
        recon_row = (
            _tile("QuickBooks AR", money(recon["qb"]), _pill("system of record", "mute"))
            + _tile("Alvys AR", money(recon["alvys"]), _pill("operational / TMS", "mute"))
            + _tile("Variance &middot; QB &minus; Alvys", money(abs(_d)),
                    _pill(pct(recon["pct"]) + " of AR", recon["kind"]))
            + empty_td)
        if recon["kind"] == "good":
            recon_note = ("QuickBooks and Alvys agree on open AR within 1% "
                          f"({money(abs(_d))} apart) &mdash; receivables are in sync.")
        elif _d < 0:
            recon_note = (f"QuickBooks shows {money(abs(_d))} less open AR than Alvys "
                          f"({pct(recon['pct'])} of the balance). The likely cause is customer "
                          "payments applied in QuickBooks that haven&rsquo;t synced back to Alvys &mdash; "
                          "paid invoices drop out of QB&rsquo;s AR but still read open in the TMS, "
                          "piling into the older buckets. Spot-check the oldest Alvys balances against QB.")
        else:
            recon_note = (f"QuickBooks shows {money(abs(_d))} more open AR than Alvys "
                          f"({pct(recon['pct'])} of the balance) &mdash; likely invoices posted to "
                          "QuickBooks that Alvys hasn&rsquo;t billed or recorded yet. "
                          "Reconcile X-Trux + X-Linx to clear it.")

    # Alvys 61+ balance detail — the oldest open balances to spot-check against QB.
    rows61 = (alvys_ar or {}).get("d61plus_rows") or []
    recon_detail = ""
    if rows61:
        body61 = ""
        for r in rows61:
            cust = r["customer"] or "&mdash; (no customer name)"
            body61 += _tr([cust, r["load"], str(r["days"]), money(r["amount"])],
                          ["left", "left", "right", "right"], [None, None, "bad", None])
        n61 = (alvys_ar or {}).get("d61plus_n", len(rows61))
        if n61 > len(rows61):
            body61 += (f"<tr><td colspan='4' style='padding:8px;color:{MUTE};font-size:11px;'>"
                       f"Showing the {len(rows61)} largest of {n61} balances "
                       f"({money((alvys_ar or {}).get('d61plus_total'))} total).</td></tr>")
        recon_detail = (f"{_section('Alvys 61+ balances &mdash; spot-check against QuickBooks')}"
                        f"{_table(['Customer', 'Load #', 'Days', 'Amount'], ['left', 'left', 'right', 'right'], body61)}")

    bottom = (f"Profitable picture from the latest refresh. RPM {rpm(w7a.get('rpm'))} (goal $2.33), "
              f"deadhead {pct(w7a.get('deadhead'))} (goal &le;7.5%, X-Trux/XFreight). "
              f"{money(qb_ar.get('total31') if qb_ar else None)} is 31+ days overdue (see pg 3). "
              f"Safety: {swv('events', '24h')} events &amp; {swv('hos', '24h')} HOS violations in last 24h.")

    # Data-check banner: surface any structural problems with the source workbook.
    warn_row = (_brief("Data check &mdash; " + "; ".join(warnings), "bad") if warnings else "")
    # MTD P&L tiles include only settled loads (Driver Rate > 0) to match the
    # Power BI XFreight Report. Surface the count of booked-but-not-yet-settled
    # loads so the deferred work isn't invisible.
    _unsettled = sum((alvys_entities or {}).get(ent, {}).get("unsettled", 0) for ent in ENTITY_ORDER)
    _mtd_msg = ("MTD revenue / cost / margin tiles include only settled loads "
                "(driver pay entered), matching the Power BI report.")
    if _unsettled:
        _mtd_msg += f" {_unsettled} additional load{'s' if _unsettled != 1 else ''} booked this month are awaiting driver pay and will appear once settled."
    mtd_note = _brief(_mtd_msg, "mute")
    asof = ""
    if data_asof is not None:
        try:
            t = pd.Timestamp(data_asof).tz_convert("America/Chicago")
        except Exception:
            t = pd.Timestamp(data_asof)
        asof = f"Alvys data as of {t:%b %d, %Y %I:%M %p %Z}. "

    return (f"{_header('Morning Executive Brief', 1, date_str)}"
            f"<div style='padding:18px 24px 4px;'><div style='background:#0f2742;border-radius:10px;padding:14px 18px;"
            f"color:#e6eef7;font-size:14px;line-height:1.5;'><span style='color:{ACCENT};font-weight:800;"
            f"text-transform:uppercase;font-size:11px;letter-spacing:.6px;'>Bottom line</span><br>{bottom}</div></div>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"{warn_row}"
            f"{_section('XFreight Overview')}"
            f"<tr>{t1}</tr><tr>{t1b}</tr>"
            f"{_section('Revenue / cost / margin by entity &middot; MTD')}"
            f"{_table(['Entity', 'Revenue', 'Cost', 'Margin', 'Margin %'], ['left', 'right', 'right', 'right', 'right'], entity_rows + entity_total)}"
            f"{mtd_note}"
            f"{_section('X-Trux Overview')}<tr>{xtrux_r1}</tr><tr>{xtrux_r2}</tr><tr>{xtrux_r3}</tr>"
            f"{_section('X-Linx Overview')}<tr>{xlinx_tiles}</tr>"
            f"{_section('Receivables &amp; payables &mdash; 6-month balance trend')}<tr>{recv_left}{ar_chart}{ap_chart}</tr>"
            f"{_brief(ar_insight, 'bad' if ar_rising else 'good')}"
            + (f"{_section('Alvys AR &mdash; aging by due date &middot; X-Trux + X-Linx open invoices')}<tr>{alvys_ar_row}</tr>"
               if alvys_ar_row else "")
            + (f"{_section('AR reconciliation &mdash; QuickBooks vs Alvys &middot; X-Trux + X-Linx')}<tr>{recon_row}</tr>"
               f"{_brief(recon_note, recon['kind'])}"
               if recon_row else "")
            + recon_detail
            + f"{_section('Safety &amp; compliance &mdash; 24h / 7d / MTD &middot; X-Trux / XFreight fleet')}<tr>{safety_tiles}</tr>"
            + f"{_section('Safety &amp; compliance &mdash; 6-month trend (MTD)')}<tr>{safety_charts}</tr>"
            + f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            + f"{asof}Orange bar = current month (MTD, partial). Sources: Alvys Master 2026, QuickBooks, Samsara.</div>")


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
            f"{_section('Overdue invoices (31+ days) by customer &middot; X-Trux + X-Linx &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'Invoice', 'Inv date', 'Due date', 'Amount', 'Bucket'], ['left', 'left', 'left', 'left', 'right', 'left'], rows + total_row)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Current and 1&ndash;30 day balances omitted by request. X-Trux Inc + X-Linx Inc only. "
            f"Source: QuickBooks A/R Aging Detail.</div>")


def build_page4(mileage, date_str) -> str:
    m = mileage or {}
    labels = (m.get("labels") or ["", "", "", ""])
    rows = m.get("rows") or []
    week_totals = m.get("week_totals") or [0] * SETTLEMENT_WEEKS
    cur = SETTLEMENT_WEEKS - 1

    tiles = (_tile("Drivers &middot; this week", num(m.get("drivers_this_week")), _pill("settled legs", "mute"))
             + _tile("Miles &middot; this week", num(m.get("miles_this_week")), _pill(labels[cur] or "current", "mute"))
             + _tile("Miles &middot; last week", num(m.get("miles_last_week")), _pill(labels[cur - 1] or "prior", "mute"))
             + _tile("Avg miles / driver", num(m.get("avg_per_driver")), _pill("this week", "mute")))

    def mcell(text, al="right", cur=False, bold=False, small=False):
        bg = f"background:{ACCENTBG};" if cur else ""
        fs = "11px" if small else "12.5px"
        return (f"<td align='{al}' style='padding:8px 8px;font-size:{fs};color:{INK};"
                f"font-weight:{'700' if bold else '400'};border-bottom:1px solid {LINE};{bg}'>{text}</td>")

    def hcell(text, al="right", cur=False):
        bg = ACCENTBG if cur else TILEBG
        fg = ACCENT if cur else MUTE
        return (f"<td align='{al}' style='padding:8px 8px;font-size:10px;text-transform:uppercase;"
                f"letter-spacing:.4px;color:{fg};font-weight:700;background:{bg};border-bottom:1px solid {LINE};'>{text}</td>")

    head = ("<tr>" + hcell("Driver", "left") + hcell("Trucks", "left")
            + "".join(hcell(labels[k], "right", cur=(k == cur)) for k in range(SETTLEMENT_WEEKS))
            + hcell("Total", "right") + hcell("Start &rarr; End &middot; this week", "left") + "</tr>")

    body = ""
    for r in rows:
        wk_cells = "".join(
            mcell(num(r["weeks"][k]) if r["weeks"][k] else "&ndash;", "right", cur=(k == cur))
            for k in range(SETTLEMENT_WEEKS))
        body += ("<tr>"
                 + mcell(r["driver"], "left")
                 + mcell(r["trucks"] or "&ndash;", "left")
                 + wk_cells
                 + mcell(num(r["total"]), "right", bold=True)
                 + mcell(r["start_end"] or "&ndash;", "left", small=True)
                 + "</tr>")
    if rows:
        def tcell(text, al="right", cur=False):
            bg = f"background:{ACCENTBG};" if cur else ""
            return (f"<td align='{al}' style='padding:9px 8px;font-size:12.5px;font-weight:800;color:{INK};"
                    f"border-top:2px solid {LINE};{bg}'>{text}</td>")
        body += ("<tr>" + tcell("Total", "left") + tcell("", "left")
                 + "".join(tcell(num(week_totals[k]), "right", cur=(k == cur)) for k in range(SETTLEMENT_WEEKS))
                 + tcell(num(m.get("grand_total")), "right") + tcell("", "left") + "</tr>")
    else:
        body = (f"<tr><td colspan='8' style='padding:12px 8px;color:{MUTE};font-size:12.5px;'>"
                f"No delivered legs in the last {SETTLEMENT_WEEKS} settlement weeks.</td></tr>")

    table = (f"<tr><td colspan='4' style='padding:0 6px;'><table width='100%' cellpadding='0' cellspacing='0' "
             f"style='border:1px solid {LINE};border-radius:8px;border-collapse:separate;overflow:hidden;'>"
             f"{head}{body}</table></td></tr>")

    return (f"{_header('Driver Mileage by Settlement Week &mdash; X-Trux / XFreight fleet', 4, date_str)}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Driver miles by settlement week &middot; last ' + str(SETTLEMENT_WEEKS) + ' weeks')}"
            f"{table}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Settlement weeks run Wed 3:00 PM &rarr; the following Wed 2:59 PM (America/Chicago); the current "
            f"week is tinted. Each trip leg is credited to its Driver 1 / Truck / miles and bucketed by its own "
            f"actual delivery (last stop arrival). Cancelled and not-yet-delivered legs are excluded; asset fleet "
            f"only. Source: Alvys API (Trips, via the pipeline file).</div>")


def build_page5(uninv, date_str) -> str:
    u = uninv or {}
    rows_data = u.get("rows", [])
    od = u.get("oldest_days")
    tiles = (_tile("Loads delivered, not invoiced", num(u.get("count")), _pill("X-Trux + X-Linx", "mute"))
             + _tile("Un-invoiced revenue", money(u.get("total_revenue")), _pill("to bill", "warn"))
             + _tile("Oldest delivered", (num(od) + " days" if _isnum(od) else "n/a"), _pill("since delivery", "bad"))
             + "<td width='25%' style='padding:6px;'></td>")
    body = ""
    for r in rows_data:
        dd = r["days"] or 0
        k = "bad" if dd >= 14 else ("warn" if dd >= 7 else None)
        days_txt = str(r["days"]) if r["days"] is not None else "&ndash;"
        cust = r["customer"] or "&mdash; (no customer name)"
        body += _tr([r["load"], cust, r["entity"], r["delivered"], days_txt, money(r["revenue"])],
                    ["left", "left", "left", "left", "right", "right"],
                    [None, None, None, None, k, None])
    shown, count = u.get("shown", len(rows_data)), u.get("count", 0)
    more = (f"<tr><td colspan='6' style='padding:8px;color:{MUTE};font-size:11px;'>"
            f"Showing the {shown} oldest of {count} loads.</td></tr>") if count > shown else ""
    return (f"{_header('Alvys &mdash; Delivered, Not Yet Invoiced', 5, date_str)}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Delivered loads awaiting invoice &middot; oldest first &middot; as of ' + date_str)}"
            f"{_table(['Load #', 'Customer', 'Entity', 'Delivered', 'Days', 'Revenue'], ['left', 'left', 'left', 'left', 'right', 'right'], body + more)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Delivered loads with no Invoiced Date &mdash; the un-billed revenue behind most of the "
            f"QuickBooks-vs-Alvys AR gap. X-Trux Inc + X-Linx Inc (JW Logistics excluded); &lsquo;Delivered&rsquo; "
            f"is the actual last-stop arrival (Scheduled Delivery if arrival is missing). "
            f"Source: Alvys API (Loads, via the pipeline file).</div>")


def build_page6(alvys_ar, date_str) -> str:
    a = alvys_ar or {}
    custs = a.get("d91plus_customers") or []
    n_loads = sum(c["loads"] for c in custs)
    tiles = (_tile("90+ days AR", money(a.get("d91plus")), _pill("X-Trux + X-Linx", "bad"))
             + _tile("Customers 90+", num(len(custs)), _pill("over 90 days", "bad"))
             + _tile("Loads 90+", num(n_loads), _pill("open invoices", "mute"))
             + "<td width='25%' style='padding:6px;'></td>")
    body = ""
    for c in custs:
        body += _tr([c["customer"] or "&mdash; (no customer name)", str(c["loads"]),
                     str(c["oldest_days"]), money(c["amount"])],
                    ["left", "right", "right", "right"], [None, None, "bad", "bad"])
    return (f"{_header('Alvys AR &mdash; Customers Aging 90+ Days', 6, date_str)}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Customers with open balances over 90 days &middot; by total &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'Loads', 'Oldest (days)', 'Amount'], ['left', 'right', 'right', 'right'], body)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Open invoiced balances aged &gt;90 days past the Customer Due Date (Invoiced Date + 30d if none). "
            f"X-Trux Inc + X-Linx Inc, JW Logistics excluded. Many may already be paid in QuickBooks &mdash; "
            f"see the page-1 AR reconciliation note. Source: Alvys API (Loads, via the pipeline file).</div>")


def build_page7(qb_ar, alvys_ar, date_str) -> str:
    rec = compute_ar_customer_reconciliation(qb_ar, alvys_ar) or {}
    rows = rec.get("rows", [])
    LIMIT = 30
    shown = rows[:LIMIT]
    n_gap = sum(1 for r in rows if abs(r["delta"]) >= 1.0)

    def _signed(d):
        return ("&minus;" + money(abs(d))) if d < 0 else money(d)

    tiles = (_tile("Net variance &middot; QB &minus; Alvys", _signed(rec.get("delta_total") or 0), _pill("all customers", "bad"))
             + _tile("Customers with a gap", num(n_gap), _pill("QB &ne; Alvys", "warn"))
             + _tile("Largest gap", _signed(shown[0]["delta"]) if shown else "n/a",
                     _pill((shown[0]["customer"][:20] if shown else ""), "mute"))
             + "<td width='25%' style='padding:6px;'></td>")

    body = ""
    for r in shown:
        d = r["delta"]
        qb_txt = money(r["qb"]) if abs(r["qb"]) >= 0.01 else "&mdash;"
        al_txt = money(r["alvys"]) if abs(r["alvys"]) >= 0.01 else "&mdash;"
        k = "bad" if d < 0 else "warn"
        body += _tr([r["customer"] or "&mdash; (no customer name)", qb_txt, al_txt, _signed(d)],
                    ["left", "right", "right", "right"], [None, None, None, k])
    body += (f"<tr><td style='padding:9px 8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>Total</td>"
             f"<td align='right' style='padding:9px 8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>{money(rec.get('qb_total'))}</td>"
             f"<td align='right' style='padding:9px 8px;font-weight:800;color:{INK};border-top:2px solid {LINE};'>{money(rec.get('alvys_total'))}</td>"
             f"<td align='right' style='padding:9px 8px;font-weight:800;color:{BAD};border-top:2px solid {LINE};'>{_signed(rec.get('delta_total') or 0)}</td></tr>")
    if len(rows) > LIMIT:
        body += (f"<tr><td colspan='4' style='padding:8px;color:{MUTE};font-size:11px;'>"
                 f"Showing the {LIMIT} largest gaps of {len(rows)} customers.</td></tr>")

    return (f"{_header('AR Reconciliation by Customer &mdash; QuickBooks vs Alvys', 7, date_str)}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Where the QB&ndash;Alvys gap sits &middot; by customer &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'QuickBooks', 'Alvys', 'Variance'], ['left', 'right', 'right', 'right'], body)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Open AR per customer, QuickBooks vs Alvys (X-Trux + X-Linx, JW excluded). Variance = QB &minus; Alvys; "
            f"a negative (red) value means Alvys shows more open AR &mdash; most often invoices already paid in QB but "
            f"not synced back. Rows sum to the page-1 variance. Customers joined by name; a one-sided row can be the "
            f"same customer spelled differently in the two systems. True bill-by-bill matching needs a shared invoice "
            f"number (not in the Alvys feed today). Sources: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")


def build_page8(qb_ar, alvys_ar, date_str) -> str:
    b = compute_bill_reconciliation(qb_ar, alvys_ar) or {}
    head = _header("AR Reconciliation by Invoice &mdash; QuickBooks vs Alvys", 8, date_str)
    if not b.get("available"):
        msg = ("No open invoices to match this run &mdash; the QuickBooks A/R detail has no invoice "
               "numbers, or there is no open AR. See page 7 for the customer-level reconciliation.")
        return (f"{head}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
                f"{_brief(msg, 'warn')}</table>"
                f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
                f"Source: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")

    if b.get("no_match"):
        # Neither invoice # nor Load # overlapped QB's Num — show samples to compare formats.
        msg = ("Couldn&rsquo;t match bills: neither the Alvys invoice number nor the Alvys Load # overlaps the "
               "QuickBooks invoice &lsquo;Num&rsquo;. Sample identifiers below &mdash; the two systems appear to "
               "number invoices differently. Use page 7 (by customer) meanwhile.")
        srows = ""
        al_s, qb_s = b.get("alvys_sample", []), b.get("qb_sample", [])
        for i in range(max(len(al_s), len(qb_s))):
            srows += _tr([al_s[i] if i < len(al_s) else "", qb_s[i] if i < len(qb_s) else ""],
                         ["left", "left"], [None, None])
        return (f"{head}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
                f"{_brief(msg, 'warn')}"
                f"{_section('Sample identifiers &middot; Alvys vs QuickBooks')}"
                f"{_table(['Alvys invoice # / Load #', 'QuickBooks Num'], ['left', 'left'], srows)}</table>"
                f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
                f"Source: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")

    ao, qo, mm = b["alvys_only"], b["qb_only"], b["mismatch"]
    LIM = 20
    match_pct = (b["matched"] / b["alvys_n"]) if b["alvys_n"] else None
    key_label = "Load #" if b.get("key_used") == "load" else "invoice #"
    tiles = (_tile("Open in Alvys, not QB", money(b["alvys_only_total"]), _pill(f"{len(ao)} bills", "bad"))
             + _tile("Open in QB, not Alvys", money(b["qb_only_total"]), _pill(f"{len(qo)} bills", "warn"))
             + _tile("Match rate", pct(match_pct), _pill(f"on {key_label} &middot; {b['matched']}/{b['alvys_n']}", "mute"))
             + "<td width='25%' style='padding:6px;'></td>")

    def _tbl(title, rows, cols, mk):
        if not rows:
            return ""
        body = "".join(mk(r) for r in rows[:LIM])
        if len(rows) > LIM:
            body += (f"<tr><td colspan='{len(cols)}' style='padding:8px;color:{MUTE};font-size:11px;'>"
                     f"Showing the {LIM} largest of {len(rows)}.</td></tr>")
        return f"{_section(title)}{_table(cols, ['left', 'left', 'right', 'right'], body)}"

    ao_tbl = _tbl("Open in Alvys, not in QuickBooks &middot; the gap to chase", ao,
                  ["Invoice / Load", "Customer", "Days", "Amount"],
                  lambda r: _tr([r["invoice"] or r["load"], r["customer"] or "&mdash;", str(r["days"]), money(r["amount"])],
                                ["left", "left", "right", "right"], [None, None, "bad", None]))
    mm_tbl = _tbl("Same bill, different open balance", mm,
                  ["Invoice / Load", "Customer", "Alvys / QB", "Diff"],
                  lambda r: _tr([r["invoice"], r["customer"] or "&mdash;", f"{money(r['amount'])} / {money(r['qb_amount'])}", money(r["diff"])],
                                ["left", "left", "right", "right"], [None, None, None, "warn"]))
    qo_tbl = _tbl("Open in QuickBooks, not in Alvys", qo,
                  ["Invoice", "Customer", "", "Amount"],
                  lambda r: _tr([r["invoice"], r["customer"] or "&mdash;", "", money(r["amount"])],
                                ["left", "left", "right", "right"], [None, None, None, "warn"]))

    return (f"{head}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>{ao_tbl}{mm_tbl}{qo_tbl}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
            f"Matched on Alvys {key_label} vs QuickBooks invoice &lsquo;Num&rsquo; (X-Trux + X-Linx, JW excluded). "
            f"&lsquo;Open in Alvys, not in QuickBooks&rsquo; are the bills driving the gap &mdash; most are likely "
            f"paid in QB but not synced back to Alvys. If the match rate is low, the two systems number bills "
            f"differently and this view is partial &mdash; use page 7. Sources: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")


def build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing,
               alvys_ar=None, warnings=None, data_asof=None, mileage=None, uninvoiced=None,
               rpm_trend=None) -> str:
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
            f"{wrap(note + build_page1(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, date_str, alvys_ar=alvys_ar, warnings=warnings, data_asof=data_asof, rpm_trend=rpm_trend))}{pb}"
            f"{wrap(build_page2(samsara, date_str))}{pb}"
            f"{wrap(build_page3(qb_ar, date_str))}{pb}"
            f"{wrap(build_page4(mileage, date_str))}{pb}"
            f"{wrap(build_page5(uninvoiced, date_str))}{pb}"
            f"{wrap(build_page6(alvys_ar, date_str))}{pb}"
            f"{wrap(build_page7(qb_ar, alvys_ar, date_str))}{pb}"
            f"{wrap(build_page8(qb_ar, alvys_ar, date_str))}"
            f"</body></html>")


# ----------------------------------------------------------------------
# Orchestration (testable without network)
# ----------------------------------------------------------------------
def build_report(alvys_sheets, pnl_sheets, ar_sheets, ar_hist_sheets, ap_hist_sheets, samsara_sheets, missing,
                 alvys_pipeline_sheets=None, data_asof=None) -> str:
    alvys = compute_alvys(alvys_sheets) if alvys_sheets else None
    alvys_entities = compute_alvys_entities(alvys_sheets) if alvys_sheets else {}
    qb_pnl = compute_qb_pnl(next(iter(pnl_sheets.values()))) if pnl_sheets else {}
    qb_ar = compute_qb_ar_detail(next(iter(ar_sheets.values()))) if ar_sheets else {}
    ar_hist = compute_balance_history(next(iter(ar_hist_sheets.values())), "Total_AR", _AR_COMPANIES) if ar_hist_sheets else ([], [])
    ap_hist = compute_balance_history(next(iter(ap_hist_sheets.values())), "Total_AP") if ap_hist_sheets else ([], [])
    samsara = compute_samsara(samsara_sheets) if samsara_sheets else None
    alvys_ar = compute_alvys_ar(alvys_pipeline_sheets) if alvys_pipeline_sheets else {}
    mileage = compute_driver_mileage(alvys_pipeline_sheets) if alvys_pipeline_sheets else {}
    uninvoiced = compute_alvys_uninvoiced(alvys_pipeline_sheets) if alvys_pipeline_sheets else {}
    rpm_trend = compute_rpm_trend(alvys_sheets) if alvys_sheets else None
    warnings = _alvys_health(alvys_sheets) if alvys_sheets else []
    for w in warnings:
        log.warning("Alvys data check: %s", w)
    return build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing,
                      alvys_ar=alvys_ar, warnings=warnings, data_asof=data_asof, mileage=mileage,
                      uninvoiced=uninvoiced, rpm_trend=rpm_trend)


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


def run_check(path: str) -> int:
    """Offline parity check: print closed-month Alvys KPIs from a local workbook so
    they can be eyeballed against the Power BI XFreight Report. No network or
    credentials needed: `python -m src.scorecard_email --check "Alvys Master 2026.xlsx"`.
    """
    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except Exception as exc:
        print(f"Could not open {path}: {exc}")
        return 1
    print(f"Alvys KPI parity check — {path}")
    print("Compare each closed month against the report's XFreight+X-Trux and X-Linx rows.\n")
    hdr = f"  {'entity':20s}{'revenue':>13}{'driver rate':>14}{'margin':>13}{'margin %':>10}{'loads':>7}"
    this_month = pd.Timestamp.now().normalize().replace(day=1)
    for i in range(1, 5):  # last 4 closed months
        start = this_month - pd.offsets.MonthBegin(i)
        end = start + pd.offsets.MonthBegin(1)
        ent = compute_alvys_entities(sheets, start=start, end=end)
        print(f"{start:%Y-%m} (closed)")
        print(hdr)
        for e in ENTITY_ORDER:
            d = ent.get(e, {})
            r, c, m, mp, l = (d.get("revenue"), d.get("cost"), d.get("margin"),
                              d.get("margin_pct"), d.get("loads"))
            print(f"  {e:20s}{money(r):>13}{money(c):>14}{money(m):>13}{pct(mp):>10}{num(l):>7}")
        print()
    warns = _alvys_health(sheets)
    if warns:
        print("Data checks:")
        for w in warns:
            print("  WARNING:", w)
    else:
        print("Data checks: all required Loads columns present.")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()

    if "--check" in sys.argv:
        i = sys.argv.index("--check")
        path = sys.argv[i + 1] if i + 1 < len(sys.argv) else os.environ.get(
            "SCORECARD_ALVYS_PATH", "Alvys Master 2026.xlsx")
        return run_check(path)

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not all([tenant, client, secret, upn]):
        sys.exit("ERROR: AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET and ONEDRIVE_USER_UPN are required")

    from_upn = os.environ.get("SCORECARD_FROM_UPN", upn)
    to_emails = [e.strip() for e in os.environ.get("SCORECARD_TO_EMAILS", "jeff@xfreight.net").split(",") if e.strip()]

    alvys_path = os.environ.get("SCORECARD_ALVYS_PATH", "Alvys Master 2026.xlsx")
    # If set, read the Alvys workbook from this exact OneDrive sharing URL instead of
    # by name — avoids reading the wrong file when a duplicate of the same name exists.
    alvys_share = os.environ.get("SCORECARD_ALVYS_SHARE_URL", "").strip()
    alvys_pipeline_path = os.environ.get("SCORECARD_ALVYS_PIPELINE_PATH", "Alvys Pipeline.xlsx")
    qb_dir = os.environ.get("SCORECARD_QB_DIR", "QuickBooks").strip("/")
    samsara_path = os.environ.get("SCORECARD_SAMSARA_PATH", "Samsara/Samsara Master.xlsx")

    token = get_token(tenant, client, secret)
    missing: list[str] = []

    alvys_sheets = data_asof = None
    if alvys_share:
        try:
            alvys_sheets = pd.read_excel(io.BytesIO(download_shared_file(token, alvys_share)), sheet_name=None)
            data_asof = get_shared_modified(token, alvys_share)
            log.info("Read Alvys workbook via share URL")
        except Exception as exc:
            log.warning("Could not read Alvys via share URL (%s); falling back to path", exc)
    if alvys_sheets is None:
        alvys_sheets = _safe_read(token, upn, alvys_path, missing, "Alvys Master 2026")
        data_asof = get_file_modified(token, upn, alvys_path)
    alvys_pipeline_sheets = _safe_read(token, upn, alvys_pipeline_path, missing, "Alvys Pipeline")
    pnl_sheets = _safe_read(token, upn, f"{qb_dir}/QB_ProfitAndLoss.xlsx", missing, "QB P&L")
    ar_sheets = _safe_read(token, upn, f"{qb_dir}/QB_AgedReceivableDetail.xlsx", missing, "QB AR aging")
    ar_hist_sheets = _safe_read(token, upn, f"{qb_dir}/QB_AR_History.xlsx", missing, "QB AR history")
    ap_hist_sheets = _safe_read(token, upn, f"{qb_dir}/QB_AP_History.xlsx", missing, "QB AP history")
    samsara_sheets = _safe_read(token, upn, samsara_path, missing, "Samsara Master")

    html = build_report(alvys_sheets, pnl_sheets, ar_sheets, ar_hist_sheets, ap_hist_sheets, samsara_sheets, missing,
                        alvys_pipeline_sheets=alvys_pipeline_sheets, data_asof=data_asof)
    subject = f"XFreight Executive Brief — {datetime.now():%b %d, %Y}"
    send_email(token, from_upn, to_emails, subject, html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
