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
    SCORECARD_SAMBASAFETY_PATH default "SambaSafety/SambaSafety_Master.xlsx" (optional, page 9)
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
TARGET_RPM = 2.92
TARGET_DEADHEAD = 0.06
TARGET_OR = 0.95
COACH_EVENT_THRESHOLD = 2  # drivers with >= this many safety events in window need coaching

# --- X-Trux rate-per-mile goal -----------------------------------------
# The goal re-costs the operation every run instead of trusting a stale number.
# It is scoped to X-Trux (the asset trucking company that runs the owner-ops);
# X-Linx (brokerage) is priced per load, not per mile, so it is excluded from
# the rate but its office overhead is still absorbed (see RPM_GOAL_OVERHEAD_COMPANIES).
# All four inputs are overridable from the environment for CI / tuning:
#   RPM_GOAL_TARGET_OR          operating ratio the goal targets. 0.95 = 5% net
#                               margin (the chosen default — bakes profit on top
#                               of the fully-loaded cost); 0.92 = 8%, 1.0 = break-even.
#   RPM_GOAL_OVERHEAD_COMPANIES comma-separated QuickBooks company names whose
#                               Total Expenses make up the shared office overhead
#                               pool that the X-Trux miles must absorb.
#   RPM_GOAL_PAY_WINDOW_DAYS    trailing window for the driver-pay-per-mile read,
#                               so the goal tracks the *current* weekly O/O rate.
#                               Short (10d default) because the rate changes weekly;
#                               the pay read is restricted to settled loads so the
#                               recent not-yet-settled loads don't drag it down.
#   RPM_GOAL_WORKSHEET_OVERHEAD the latest office-cost-per-mile from the manually
#                               kept "Goals and Trends.xlsx" (Jeff's Number tab),
#                               shown alongside the QB figure as a sanity check.
#   RPM_GOAL_OVERHEAD_ALLOC     fraction of the combined office-overhead pool that
#                               the X-Trux miles absorb (1.0 = all of it, the
#                               default; 0.85 would push 15% onto brokerage).
RPM_GOAL_TARGET_OR = 0.95
RPM_GOAL_OVERHEAD_COMPANIES = ("X-Trux Inc", "X-Linx Inc")
RPM_GOAL_PAY_WINDOW_DAYS = 10
RPM_GOAL_WORKSHEET_OVERHEAD = 0.88
RPM_GOAL_OVERHEAD_ALLOC = 1.0
# Fail-soft guards: if the short pay window is too thin to trust, widen it; if the
# resulting cost lands outside a sane band, flag it on the email's data-check banner.
RPM_GOAL_MIN_SETTLED_LOADS = 5      # need at least this many settled X-Trux loads…
RPM_GOAL_MIN_WINDOW_MILES = 5000    # …and this many miles, else widen the window
RPM_GOAL_FALLBACK_WINDOWS = (30, 60, 90)   # widen to these (days) in order
RPM_GOAL_PLAUSIBLE_BAND = (1.50, 5.00)     # cost/mi outside this is flagged

# SambaSafety driver-compliance thresholds (page 9).
LICENSE_EXPIRY_WARN_DAYS = 30     # flag licenses expiring within this many days
SAMBA_HIGH_RISK_SCORE = 70        # fallback high-risk cutoff when no risk category column
VIOLATION_WINDOW_DAYS = 30        # "recent" window for new violations / MVR alerts

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
    # Power BI's XFreight Report sums the workbook's "Total Dispatch Mileage"
    # column (= Loaded + Empty) as its "Dispatch Mileage" measure. Both
    # Dead Head % and Rev per Mile use that as the denominator. Mirror that
    # here so the scorecard tiles tie to the Power BI table row-for-row.
    #
    # History: we briefly switched to dividing by Loaded only after a May 28
    # diagnostic suggested Power BI was using Loaded (165,717 was close to
    # the workbook's Loaded sum 165,508 at that time). A May 30 diagnostic
    # showed Power BI's denominator was 175,182 — exactly the workbook's
    # Total Dispatch Mileage sum. So the right basis is Total. The May 28
    # numbers were a coincidental near-match on a transitional day.
    revenue = _col_any(sub, ["Customer Revenue", "Revenue"]).sum()
    loaded = _col_any(sub, ["Loaded Mileage", "Loaded Dispatch Mileage", "Loaded Miles"]).sum()
    empty = _col_any(sub, ["Empty Mileage", "Empty Dispatch Mileage", "Empty Miles"]).sum()
    total_col = _col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage",
                               "Total Miles", "Total Mileage"])
    total = total_col.sum() if total_col.notna().any() else (loaded + empty)
    # Margin = Customer Revenue - Driver Rate, matching Power BI. Carrier Rate is
    # NOT added: the Driver Rate column is the full payout per load already.
    cost = float(_col(sub, "Driver Rate").fillna(0).sum())
    margin = revenue - cost
    return {
        "loads": len(sub),
        "revenue": revenue if revenue else None,
        "miles": total if total else None,           # Power BI "Dispatch Mileage"
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


# --- AR aging detail (page 4, 31+ only) --------------------------------
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


def compute_margin_projection(sheets: dict[str, pd.DataFrame] | None, days: int = 90) -> dict:
    """Estimate full-month settled margin per entity.

    Formula per entity:
        projected_revenue = (booked MTD revenue) * (days_in_month / day_of_month)
        projected_margin  = projected_revenue * trailing_{days}_margin_pct

    Booked MTD revenue = all non-cancelled loads with Scheduled Pickup in the
    current month — includes loads that haven't yet had driver pay entered, so
    the forward estimate captures activity the settled-only MTD tile excludes.

    Trailing margin % = settled loads only (Driver Rate > 0), non-cancelled,
    Scheduled Pickup within the last ``days`` days. Combined = X-Trux + X-Linx,
    using the combined trailing revenue/cost (revenue-weighted blend), not a
    simple average of the per-entity rates.
    """
    if not sheets:
        return {}
    loads = sheets.get("Loads")
    if loads is None or loads.empty:
        return {}
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if not office_col:
        return {}

    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    groups_all = loads[office_col].map(_entity_group)
    not_cancelled = (loads["Load Status"].astype(str).str.lower() != "cancelled"
                     if "Load Status" in loads.columns else pd.Series(True, index=loads.index))

    now = pd.Timestamp.now()
    dim, dom = now.days_in_month, now.day
    factor = (dim / dom) if dom else None

    mtd_mask = (dates >= _windows()["mtd"]) & not_cancelled
    trail_start = now - pd.Timedelta(days=days)
    trail_mask = (dates >= trail_start) & (dates < now) & not_cancelled
    if "Driver Rate" in loads.columns:
        trail_mask = trail_mask & (_col(loads, "Driver Rate").fillna(0) > 0)

    out: dict = {"days_in_month": dim, "day_of_month": dom, "trailing_days": days}
    combined_booked = combined_t_rev = combined_t_cost = 0.0

    for ent in ENTITY_ORDER:
        ent_mask = groups_all == ent
        booked = float(_col_any(loads[mtd_mask & ent_mask], ["Customer Revenue", "Revenue"]).sum())
        t_rev = float(_col_any(loads[trail_mask & ent_mask], ["Customer Revenue", "Revenue"]).sum())
        t_cost = float(_col(loads[trail_mask & ent_mask], "Driver Rate").fillna(0).sum())
        m_pct = ((t_rev - t_cost) / t_rev) if t_rev else None
        proj_rev = (booked * factor) if (booked and factor) else None
        proj_margin = (proj_rev * m_pct) if (proj_rev and m_pct is not None) else None
        out[ent] = {
            "booked_mtd": booked or None,
            "trailing_margin_pct": m_pct,
            "projected_revenue": proj_rev,
            "projected_margin": proj_margin,
        }
        combined_booked += booked
        combined_t_rev += t_rev
        combined_t_cost += t_cost

    c_pct = ((combined_t_rev - combined_t_cost) / combined_t_rev) if combined_t_rev else None
    c_proj_rev = (combined_booked * factor) if (combined_booked and factor) else None
    c_proj_margin = (c_proj_rev * c_pct) if (c_proj_rev and c_pct is not None) else None
    out["combined"] = {
        "booked_mtd": combined_booked or None,
        "trailing_margin_pct": c_pct,
        "projected_revenue": c_proj_rev,
        "projected_margin": c_proj_margin,
    }
    return out


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back to `default` when unset/blank/bad."""
    v = os.environ.get(name)
    if v in (None, ""):
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        log.warning("Ignoring non-numeric %s=%r; using %s", name, v, default)
        return default


def compute_rpm_goal(alvys_sheets: dict[str, pd.DataFrame] | None, qb_pnl: dict | None, *,
                     target_or: float | None = None, overhead_companies: list[str] | None = None,
                     pay_window_days: int | None = None,
                     worksheet_overhead: float | None = None) -> dict | None:
    """X-Trux rate-per-mile goal = fully-loaded cost per mile / target operating ratio.

    Cost per mile is rebuilt from live data each run so the goal self-corrects:
      * driver/owner-op pay per mile = SUM(Driver Rate) / SUM(Total Dispatch Mileage)
        for the X-Trux asset fleet over the trailing `pay_window_days` (settled
        loads only). A short recent window (not fiscal-YTD) means the goal tracks
        the *current* weekly O/O rate and blends in accessorials + deadhead
        automatically, instead of hardcoding the $/mi contract number; restricting
        to settled loads keeps not-yet-settled recent loads from deflating it.
      * office/overhead per mile = combined Total Expenses of `overhead_companies`
        (X-Trux + X-Linx share one back office) from the QuickBooks P&L, divided by
        fiscal-YTD X-Trux miles. The QB P&L is a "This Fiscal Year" report, so YTD
        miles keep numerator and denominator on the same period. The trucking miles
        absorb the whole office overhead — that is what makes the rate "fully loaded".

    Profit is layered on top via the operating ratio: goal = cost / OR. The default
    OR = 0.95 bakes in a 5% net margin on the fully-loaded cost; OR = 0.92 is 8%
    and OR = 1.0 is break-even. Returns None only when the Alvys Loads tab is unusable;
    otherwise it returns every component it can compute and leaves the rest None so
    the brief can render partial results (fail-soft, like the other KPIs).
    """
    if not alvys_sheets:
        return None
    loads = alvys_sheets.get("Loads")
    if loads is None or loads.empty:
        return None
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if not office_col:
        return None

    target_or = target_or if target_or is not None else _env_float("RPM_GOAL_TARGET_OR", RPM_GOAL_TARGET_OR)
    pay_window_days = int(pay_window_days if pay_window_days is not None
                          else _env_float("RPM_GOAL_PAY_WINDOW_DAYS", RPM_GOAL_PAY_WINDOW_DAYS))
    worksheet_overhead = (worksheet_overhead if worksheet_overhead is not None
                          else _env_float("RPM_GOAL_WORKSHEET_OVERHEAD", RPM_GOAL_WORKSHEET_OVERHEAD))
    if overhead_companies is None:
        env_co = os.environ.get("RPM_GOAL_OVERHEAD_COMPANIES")
        overhead_companies = ([c.strip() for c in env_co.split(",") if c.strip()]
                              if env_co else list(RPM_GOAL_OVERHEAD_COMPANIES))

    # X-Trux asset fleet only (fold XFreight in, drop X-Linx brokerage and cancellations).
    sub = loads.copy()
    if "Load Status" in sub.columns:
        sub = sub[sub["Load Status"].astype(str).str.lower() != "cancelled"]
    sub = sub[sub[office_col].map(_entity_group) == "X-Trux"]
    if sub.empty:
        return None
    dates = _dates(sub, ALVYS_DATE_CANDIDATES)
    pay = _col(sub, "Driver Rate").fillna(0)
    miles = _col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage", "Total Miles", "Total Mileage"]).fillna(0)
    rev = _col_any(sub, ["Customer Revenue", "Revenue"]).fillna(0)

    now = pd.Timestamp.now()
    # Recent, settled loads only. The owner-op rate changes weekly, so a short
    # trailing window tracks the current rate — but the freshest loads carry miles
    # whose driver pay hasn't settled yet ($0), and including them would drag the
    # per-mile rate down. Restrict the pay/revenue reads to settled loads
    # (Driver Rate > 0), matching the P&L convention used elsewhere.
    #
    # Fail-soft: a 10-day window can be too thin on a light/holiday week to trust.
    # Try the configured window first, then widen through the fallback windows until
    # there are enough settled loads + miles; if none qualify, use the widest as a
    # best-effort read and flag it (pay_window_fallback) so the brief can warn.
    def _window_mask(days):
        return (dates >= (now.normalize() - pd.Timedelta(days=days))) & (pay > 0)
    candidate_windows = [pay_window_days] + [w for w in RPM_GOAL_FALLBACK_WINDOWS if w > pay_window_days]
    pay_window_used, recent, pay_window_fallback = pay_window_days, _window_mask(pay_window_days), False
    for w in candidate_windows:
        m = _window_mask(w)
        if int(m.sum()) >= RPM_GOAL_MIN_SETTLED_LOADS and float(miles[m].sum()) >= RPM_GOAL_MIN_WINDOW_MILES:
            pay_window_used, recent = w, m
            pay_window_fallback = (w != pay_window_days)
            break
    else:
        # Nothing met the threshold — widen to the largest window we tried.
        pay_window_used = candidate_windows[-1]
        recent = _window_mask(pay_window_used)
        pay_window_fallback = True
    pay_loads = int(recent.sum())
    pay_miles = float(miles[recent].sum())
    pay_per_mile = (float(pay[recent].sum()) / pay_miles) if pay_miles else None
    actual_rpm = (float(rev[recent].sum()) / pay_miles) if pay_miles else None

    # Fiscal-YTD X-Trux miles, to match QuickBooks' "This Fiscal Year" P&L window.
    ytd = dates >= now.normalize().replace(month=1, day=1)
    ytd_miles = float(miles[ytd].sum())

    # Shared office overhead from QuickBooks (X-Trux + X-Linx Total Expenses).
    # The allocation factor is the fraction of that combined pool the X-Trux miles
    # absorb (default 1.0 = all of it). The X-Trux-only figure is kept too, so the
    # brief can show "combined vs X-Trux-only" side by side.
    alloc = _env_float("RPM_GOAL_OVERHEAD_ALLOC", RPM_GOAL_OVERHEAD_ALLOC)
    overhead_combined, overhead_used, overhead_xtrux = None, [], None
    if qb_pnl:
        by_norm = {_norm_name(k): k for k in qb_pnl}
        total = 0.0
        for want in overhead_companies:
            key = by_norm.get(_norm_name(want))
            if key and _isnum(qb_pnl[key].get("opex")):
                val = abs(float(qb_pnl[key]["opex"]))
                total += val
                overhead_used.append(key)
                if _norm_name(want).startswith("x trux"):
                    overhead_xtrux = val
        overhead_combined = total if overhead_used else None
    overhead_total = (overhead_combined * alloc) if overhead_combined is not None else None
    overhead_per_mile = (overhead_total / ytd_miles) if (overhead_total and ytd_miles) else None
    overhead_per_mile_xtrux = (overhead_xtrux / ytd_miles) if (overhead_xtrux and ytd_miles) else None

    cost_per_mile = ((pay_per_mile + overhead_per_mile)
                     if (pay_per_mile is not None and overhead_per_mile is not None) else None)
    goal_rpm = (cost_per_mile / target_or) if (cost_per_mile is not None and target_or) else None
    profit_per_mile = (goal_rpm - cost_per_mile) if (goal_rpm is not None and cost_per_mile is not None) else None
    gap = (goal_rpm - actual_rpm) if (goal_rpm is not None and actual_rpm is not None) else None
    ws_cost_per_mile = ((pay_per_mile + worksheet_overhead)
                        if (pay_per_mile is not None and worksheet_overhead) else None)

    # Plausibility: a sane fully-loaded X-Trux mile sits in a known band. Outside it
    # usually means a bad QB pull or a near-empty Loads window — flag, don't trust.
    lo, hi = RPM_GOAL_PLAUSIBLE_BAND
    cost_plausible = (lo <= cost_per_mile <= hi) if cost_per_mile is not None else None

    return {
        "pay_per_mile": pay_per_mile,
        "overhead_per_mile": overhead_per_mile,
        "overhead_per_mile_xtrux_only": overhead_per_mile_xtrux,
        "cost_per_mile": cost_per_mile,
        "goal_rpm": goal_rpm,
        "profit_per_mile": profit_per_mile,
        "target_or": target_or,
        "target_margin": (1 - target_or) if target_or else None,
        "actual_rpm": actual_rpm,
        "gap": gap,
        "overhead_total": overhead_total,
        "overhead_combined": overhead_combined,
        "overhead_alloc": alloc,
        "overhead_companies": overhead_used,
        "ytd_miles": ytd_miles or None,
        "pay_window_days": pay_window_days,
        "pay_window_used": pay_window_used,
        "pay_window_fallback": pay_window_fallback,
        "pay_loads": pay_loads,
        "pay_miles": pay_miles or None,
        "worksheet_overhead": worksheet_overhead,
        "worksheet_cost_per_mile": ws_cost_per_mile,
        "cost_plausible": cost_plausible,
    }


def _rpm_goal_health(goal: dict | None) -> list[str]:
    """Warnings about the rate-per-mile goal for the email's data-check banner."""
    if not goal:
        return []
    out: list[str] = []
    if goal.get("pay_window_fallback"):
        out.append(
            f"Rate-per-mile: only {goal.get('pay_loads', 0)} settled X-Trux load(s) in the "
            f"last {goal.get('pay_window_days')}d &mdash; widened the pay window to "
            f"{goal.get('pay_window_used')}d for a stable read.")
    if goal.get("cost_plausible") is False:
        lo, hi = RPM_GOAL_PLAUSIBLE_BAND
        out.append(
            f"Rate-per-mile cost {rpm(goal.get('cost_per_mile'))}/mi is outside the expected "
            f"{rpm(lo)}&ndash;{rpm(hi)} band &mdash; check the QuickBooks P&amp;L and Loads window.")
    return out


def compute_rpm_goal_trend(alvys_sheets: dict[str, pd.DataFrame] | None, goal: dict | None) -> dict:
    """Six-month trend of X-Trux cost / goal / actual revenue per mile.

    Pairs with ``compute_rpm_goal``: the office overhead is YTD-only (the QB P&L is
    a single fiscal-year report, so monthly overhead can't be reconstructed), so it
    is **held flat at the current YTD rate** for every month while the volatile
    driver-pay-per-mile leg varies by month — which is where the movement comes from
    anyway (the O/O rate changes weekly). Each month, over settled X-Trux asset loads:
        cost/mi   = SUM(Driver Rate)/SUM(miles) + overhead/mi (flat)
        goal/mi   = cost/mi / target operating ratio
        actual/mi = SUM(Customer Revenue)/SUM(miles)
    Returns ``{"labels", "cost", "goal", "actual"}`` ready for ``_bar_chart`` (current
    month's label gets a trailing ``*`` to mark MTD). ``cost``/``goal`` come back empty
    when overhead is unavailable (no QB P&L); ``actual`` is always available.
    """
    empty = {"labels": [], "cost": [], "goal": [], "actual": []}
    if not alvys_sheets or not goal:
        return empty
    loads = alvys_sheets.get("Loads")
    if loads is None or loads.empty:
        return empty
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if not office_col:
        return empty
    overhead = goal.get("overhead_per_mile")
    target_or = goal.get("target_or") or 1.0

    sub = loads.copy()
    if "Load Status" in sub.columns:
        sub = sub[sub["Load Status"].astype(str).str.lower() != "cancelled"]
    sub = sub[sub[office_col].map(_entity_group) == "X-Trux"]
    if sub.empty:
        return empty
    dates = _dates(sub, ALVYS_DATE_CANDIDATES)
    pay = _col(sub, "Driver Rate").fillna(0)
    miles = _col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage", "Total Miles", "Total Mileage"]).fillna(0)
    rev = _col_any(sub, ["Customer Revenue", "Revenue"]).fillna(0)
    settled = pay > 0

    labels, cost_s, goal_s, actual_s = [], [], [], []
    months = _last_6_months()
    for i, (yy, mm) in enumerate(months):
        m = settled & (dates.dt.year == yy) & (dates.dt.month == mm)
        mi = float(miles[m].sum())
        lab = pd.Timestamp(year=yy, month=mm, day=1).strftime("%b")
        if i == len(months) - 1:
            lab += "*"
        labels.append(lab)
        actual_s.append((float(rev[m].sum()) / mi) if mi else 0.0)
        if mi and overhead is not None:
            cpm = float(pay[m].sum()) / mi + overhead
            cost_s.append(cpm)
            goal_s.append(cpm / target_or if target_or else cpm)
        else:
            cost_s.append(0.0)
            goal_s.append(0.0)
    if overhead is None:
        cost_s, goal_s = [], []          # signal "pending" to the chart helper
    return {"labels": labels, "cost": cost_s, "goal": goal_s, "actual": actual_s}


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
    # Average distinct drivers running per week across the displayed window —
    # for the "avg drivers/wk" reference next to the per-driver miles avg.
    drivers_per_week = [sum(1 for r in rows if r["weeks"][k] > 0) for k in range(SETTLEMENT_WEEKS)]
    avg_drivers_per_week = (sum(drivers_per_week) / SETTLEMENT_WEEKS) if SETTLEMENT_WEEKS else None
    return {
        "labels": [_wk_label(s) for s in starts],
        "rows": rows,
        "week_totals": week_totals,
        "grand_total": sum(week_totals),
        "drivers_this_week": drivers_cur,
        "miles_this_week": week_totals[cur_idx],
        "miles_last_week": week_totals[cur_idx - 1] if SETTLEMENT_WEEKS >= 2 else None,
        "avg_per_driver": (week_totals[cur_idx] / drivers_cur) if drivers_cur else None,
        "avg_drivers_per_week": avg_drivers_per_week,
    }


def _wk_label(start: pd.Timestamp) -> str:
    end = start + pd.Timedelta(weeks=1) - pd.Timedelta(days=1)  # Wed -> Tue span
    if start.month == end.month:
        return f"{start:%b} {start.day}&ndash;{end.day}"
    return f"{start:%b} {start.day}&ndash;{end:%b} {end.day}"


# ----------------------------------------------------------------------
# SambaSafety driver compliance (license status, MVR violations, risk score).
# Tolerant reader: the real export column names aren't finalized, so columns
# are matched fuzzily. Expects a "Drivers" sheet and a "Violations" sheet.
# ----------------------------------------------------------------------
_LICENSE_OK = {"valid", "active", "clear", "ok", "current", "good"}


def _mask_license(lic: str) -> str:
    s = "".join(ch for ch in str(lic) if ch.isalnum())
    if len(s) >= 4:
        return "&bull;&bull;&bull;" + s[-4:]
    return s or "&mdash;"


def compute_sambasafety(sheets, now: pd.Timestamp | None = None) -> dict | None:
    if not sheets:
        return None
    now = now or pd.Timestamp.now()
    drivers_df = viol_df = None
    for name, df in sheets.items():
        if df is None or df.empty:
            continue
        ln = str(name).lower()
        if viol_df is None and any(k in ln for k in ("violation", "mvr", "alert", "conviction")):
            viol_df = df
        elif drivers_df is None and any(k in ln for k in ("driver", "license", "monitor", "roster", "risk")):
            drivers_df = df
    if drivers_df is None:
        drivers_df = next((df for df in sheets.values() if df is not None and not df.empty), None)
    if drivers_df is None or drivers_df.empty:
        return None

    name_c = _find_col(drivers_df, ["driver name", "driver", "employee", "name"])
    status_c = _find_col(drivers_df, ["license status", "licensestatus", "cdl status", "status"])
    exp_c = _find_col(drivers_df, ["license expiration", "expiration", "expire", "expiry", "valid through"])
    state_c = _find_col(drivers_df, ["license state", "issuing state", "dl state", "state"])
    lic_c = _find_col(drivers_df, ["license number", "license #", "license no", "dl number", "cdl number", "dl #"])
    score_c = _find_col(drivers_df, ["risk score", "score"])
    cat_c = _find_col(drivers_df, ["risk category", "risk level", "risk tier", "category"])

    drivers, scores = [], []
    for _, r in drivers_df.iterrows():
        name = str(r[name_c]).strip() if name_c else ""
        if not name or name.lower() == "nan":
            continue
        status = (str(r[status_c]).strip() if status_c and pd.notna(r[status_c]) else "")
        exp = pd.to_datetime(r[exp_c], errors="coerce") if exp_c else pd.NaT
        state = (str(r[state_c]).strip() if state_c and pd.notna(r[state_c]) else "")
        lic = (str(r[lic_c]).strip() if lic_c and pd.notna(r[lic_c]) else "")
        score = pd.to_numeric(r[score_c], errors="coerce") if score_c else float("nan")
        cat = (str(r[cat_c]).strip() if cat_c and pd.notna(r[cat_c]) else "")
        ok = status.lower() in _LICENSE_OK
        days_to_exp = int((exp.normalize() - now.normalize()).days) if pd.notna(exp) else None
        expiring = days_to_exp is not None and 0 <= days_to_exp <= LICENSE_EXPIRY_WARN_DAYS
        expired_by_date = days_to_exp is not None and days_to_exp < 0
        high = ("high" in cat.lower()) or (not cat and pd.notna(score) and score >= SAMBA_HIGH_RISK_SCORE)
        if pd.notna(score):
            scores.append(float(score))
        drivers.append({
            "name": name, "status": status or "Unknown", "state": state,
            "license": lic, "exp": exp, "days_to_exp": days_to_exp,
            "score": float(score) if pd.notna(score) else None, "category": cat,
            "ok": ok, "expiring": expiring, "expired": (not ok) or expired_by_date, "high": high,
        })

    license_issues = [d for d in drivers if (not d["ok"]) or d["expiring"]]
    license_issues.sort(key=lambda d: (d["ok"], d["days_to_exp"] if d["days_to_exp"] is not None else 9999))
    high_risk = [d for d in drivers if d["high"]]
    ranked = sorted([d for d in drivers if d["score"] is not None], key=lambda d: d["score"], reverse=True)

    violations = []
    if viol_df is not None and not viol_df.empty:
        vname_c = _find_col(viol_df, ["driver name", "driver", "name"])
        vdate_c = _find_col(viol_df, ["violation date", "conviction date", "offense date", "date", "reported"])
        vtype_c = _find_col(viol_df, ["violation type", "violation", "description", "offense", "type"])
        vpts_c = _find_col(viol_df, ["points", "point"])
        vstate_c = _find_col(viol_df, ["state", "jurisdiction"])
        vsev_c = _find_col(viol_df, ["severity", "seriousness", "level"])
        window = now - pd.Timedelta(days=VIOLATION_WINDOW_DAYS)
        for _, r in viol_df.iterrows():
            d = pd.to_datetime(r[vdate_c], errors="coerce") if vdate_c else pd.NaT
            if pd.isna(d) or d < window:
                continue
            violations.append({
                "name": (str(r[vname_c]).strip() if vname_c and pd.notna(r[vname_c]) else "&mdash;"),
                "date": d,
                "type": (str(r[vtype_c]).strip() if vtype_c and pd.notna(r[vtype_c]) else "&mdash;"),
                "points": (pd.to_numeric(r[vpts_c], errors="coerce") if vpts_c else float("nan")),
                "state": (str(r[vstate_c]).strip() if vstate_c and pd.notna(r[vstate_c]) else ""),
                "severity": (str(r[vsev_c]).strip() if vsev_c and pd.notna(r[vsev_c]) else ""),
            })
        violations.sort(key=lambda v: v["date"], reverse=True)

    return {
        "now": now,
        "monitored": len(drivers),
        "drivers": drivers,
        "license_issues": license_issues,
        "high_risk": high_risk,
        "ranked": ranked,
        "avg_score": (sum(scores) / len(scores)) if scores else None,
        "has_scores": bool(scores),
        "violations": violations,
        "window_days": VIOLATION_WINDOW_DAYS,
    }


# ----------------------------------------------------------------------
# HTML design system
# ----------------------------------------------------------------------
NAVY = "#102a43"; INK = "#1a202c"; MUTE = "#64748b"; LINE = "#e2e8f0"; TILEBG = "#f8fafc"
GOOD = "#15803d"; GOODBG = "#dcfce7"; WARN = "#b45309"; WARNBG = "#fef3c7"
PAGE_COUNT = 9
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
# Bottom-line lead phrase for the page-1 summary blurb.
#
# Honest net-P&L basis: revenue - fully-loaded cost (driver pay + office
# overhead allocation), not the contribution-margin shortcut used by the
# in-page MTD tiles. The fully-loaded cost comes from compute_rpm_goal's
# cost_per_mile output, which combines:
#   - driver/owner-op pay/mi from settled X-Trux/XFreight loads
#   - X-Trux + X-Linx combined office overhead/mi from QB P&L (YTD)
#
# When the rpm_goal pieces aren't available (early run, missing QB data),
# fall back to Revenue - Driver Rate (the prior contribution-margin
# definition) and tag the lead with an asterisk so a reader can spot it.
# ----------------------------------------------------------------------
def _lead_phrase(wmtd: dict | None, rpm_goal: dict | None = None) -> str:
    revenue = (wmtd or {}).get("revenue")
    miles = (wmtd or {}).get("miles")
    contribution = (wmtd or {}).get("margin")
    cpm = (rpm_goal or {}).get("cost_per_mile") if rpm_goal else None
    net = None
    if _isnum(revenue) and _isnum(miles) and _isnum(cpm):
        net = float(revenue) - (float(cpm) * float(miles))
    if net is not None:
        if net > 0:
            return f"Net-profitable MTD &mdash; {money(net)} above fully-loaded cost."
        if net == 0:
            return "Break-even MTD on fully-loaded cost."
        return f"Net-unprofitable MTD &mdash; {money(abs(net))} below fully-loaded cost."
    # Fully-loaded basis unavailable — fall back to contribution margin.
    if not _isnum(contribution):
        return "Latest refresh:"
    if contribution > 0:
        return f"Contribution-positive MTD &mdash; {money(contribution)} over driver pay.*"
    if contribution == 0:
        return "Break-even MTD on driver pay.*"
    return f"Driver-pay-underwater MTD &mdash; {money(abs(contribution))} negative.*"


# ----------------------------------------------------------------------
# Drag attribution: pick the worst-performing operational metric and name
# the specific customer / truck driving the deviation, so the BOTTOM LINE
# blurb says "who", not just "what".
#
# Ranks RPM / deadhead / AR 31+ by approximate dollar impact:
#   RPM:      (goal - actual) * fleet_miles_7d        (revenue short of goal)
#   Deadhead: (actual - goal) * fleet_miles_7d * RPM  (empty miles re-priced)
#   AR 31+:   total31 ($)                              (already a dollar amount)
# The winner gets attributed to its top contributor.
# ----------------------------------------------------------------------
def _seven_day_asset_loads(alvys_sheets: dict | None, now: pd.Timestamp | None = None):
    """Return the 7-day, non-cancelled, X-Trux asset Loads slice — the same
    slice that feeds w7a's RPM/deadhead. Returns None if unavailable."""
    if not alvys_sheets:
        return None
    loads = alvys_sheets.get("Loads")
    if loads is None or loads.empty:
        return None
    now = now or pd.Timestamp.now()
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    if "Load Status" in loads.columns:
        keep = loads["Load Status"].astype(str).str.lower() != "cancelled"
    else:
        keep = pd.Series(True, index=loads.index)
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if not office_col:
        return None
    is_asset = loads[office_col].map(_entity_group) == "X-Trux"
    cutoff = now - pd.Timedelta(days=7)
    mask = keep & is_asset & (dates >= cutoff)
    sub = loads[mask]
    return sub if not sub.empty else None


def _attribute_rpm_drag(sub, goal_rpm) -> str | None:
    """Among the 7d asset loads, find the customer whose removal would lift
    fleet RPM the most."""
    cust_col = _find_col(sub, ["customer", "shipper", "billto"])
    if not cust_col:
        return None
    rev = _col_any(sub, ["Customer Revenue", "Revenue"]).fillna(0).astype(float)
    miles = _col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage", "Total Mileage"]).fillna(0).astype(float)
    fleet_rev = float(rev.sum())
    fleet_miles = float(miles.sum())
    if fleet_miles <= 0:
        return None
    fleet_rpm = fleet_rev / fleet_miles

    by_cust: dict[str, dict] = {}
    for c, r, m in zip(sub[cust_col].fillna("").astype(str).str.strip(), rev, miles):
        key = c if c and c.lower() != "nan" else "(unknown customer)"
        d = by_cust.setdefault(key, {"n": 0, "rev": 0.0, "miles": 0.0})
        d["n"] += 1
        d["rev"] += float(r)
        d["miles"] += float(m)

    best = None
    for c, d in by_cust.items():
        miles_w = fleet_miles - d["miles"]
        rev_w = fleet_rev - d["rev"]
        if miles_w <= 0:
            continue
        rpm_w = rev_w / miles_w
        lift = rpm_w - fleet_rpm
        if lift <= 0:
            continue
        cust_rpm = (d["rev"] / d["miles"]) if d["miles"] > 0 else 0.0
        if best is None or lift > best["lift"]:
            best = {"customer": c, "n": d["n"], "rpm": cust_rpm,
                    "rpm_without": rpm_w, "lift": lift}

    if not best:
        return None
    plural = "" if best["n"] == 1 else "s"
    text = (f"Biggest RPM drag: {best['n']} load{plural} from {best['customer']} "
            f"averaging {rpm(best['rpm'])} (vs fleet {rpm(fleet_rpm)}). "
            f"Excluding them lifts fleet RPM to {rpm(best['rpm_without'])}")
    if _isnum(goal_rpm) and best["rpm_without"] >= goal_rpm:
        text += f" &mdash; clears the {rpm(goal_rpm)} goal."
    else:
        text += "."
    return text


def _attribute_deadhead_drag(sub, min_truck_miles: float = 100.0) -> str | None:
    """Among the 7d asset loads, list the top trucks running above the goal."""
    truck_col = _find_col(sub, ["truck"])
    if not truck_col:
        return None
    total = _col_any(sub, ["Total Dispatch Mileage", "Dispatch Mileage", "Total Mileage"]).fillna(0).astype(float)
    empty = _col_any(sub, ["Empty Dispatch Mileage", "Empty Mileage"]).fillna(0).astype(float)

    by_truck: dict[str, dict] = {}
    for t, tot, em in zip(sub[truck_col].fillna("").astype(str).str.strip(), total, empty):
        key = t if t and t.lower() != "nan" else "(no truck)"
        d = by_truck.setdefault(key, {"tot": 0.0, "em": 0.0})
        d["tot"] += float(tot)
        d["em"] += float(em)

    ranked = []
    for t, d in by_truck.items():
        if d["tot"] < min_truck_miles:
            continue
        dh = d["em"] / d["tot"] if d["tot"] > 0 else 0.0
        if dh > TARGET_DEADHEAD:
            ranked.append({"truck": t, "dh": dh})
    if not ranked:
        return None
    ranked.sort(key=lambda x: x["dh"], reverse=True)
    top = ranked[:3]
    parts = [f"{t['truck']} ({pct(t['dh'])})" for t in top]
    label = "truck" if len(parts) == 1 else "trucks"
    if len(parts) == 1:
        joined = parts[0]
    elif len(parts) == 2:
        joined = f"{parts[0]} and {parts[1]}"
    else:
        joined = f"{parts[0]}, {parts[1]}, and {parts[2]}"
    return (f"Biggest deadhead drag: {label} {joined} this week "
            f"(goal &le;{pct(TARGET_DEADHEAD)}).")


def _attribute_ar_drag(qb_ar: dict | None) -> str | None:
    """Find the customer with the largest 31+ aged AR concentration."""
    rows = (qb_ar or {}).get("rows") or []
    total31 = (qb_ar or {}).get("total31") or 0
    if not rows or total31 <= 0:
        return None
    by_cust: dict[str, float] = {}
    for r in rows:
        c = (r.get("customer") or "").strip() or "(unknown customer)"
        by_cust[c] = by_cust.get(c, 0.0) + float(r.get("amount", 0) or 0)
    if not by_cust:
        return None
    top_cust, top_amt = max(by_cust.items(), key=lambda x: x[1])
    if top_amt <= 0:
        return None
    share = top_amt / total31 if total31 > 0 else 0
    return (f"Biggest AR drag: {top_cust} owes {money(top_amt)} of the "
            f"{money(total31)} 31+ balance ({pct(share)}).")


def compute_drag_attribution(
    alvys_sheets: dict | None,
    qb_ar: dict | None,
    w7a: dict | None,
    rpm_goal: dict | None,
    samsara: dict | None,
    now: pd.Timestamp | None = None,
) -> dict | None:
    """One-sentence "biggest drag" attribution for the BOTTOM LINE blurb.

    Priority: safety events in 24h short-circuit (life-safety first). Otherwise
    score RPM / deadhead / AR 31+ by approximate dollar impact and attribute
    the winner. If everything is at or better than goal, returns a "clean"
    note instead.

    Returns {"text": "...", "metric": "safety|rpm|deadhead|ar|clean",
             "kind": "bad|warn|good"} or None when there isn't enough data.
    """
    sf = (samsara or {}).get("windows", {}) or {}
    ev24 = int(((sf.get("events") or {}).get("24h") or 0))
    hos24 = int(((sf.get("hosv") or {}).get("24h") or 0))
    if ev24 + hos24 > 0:
        bits = []
        if ev24:
            bits.append(f"{ev24} safety event{'s' if ev24 != 1 else ''}")
        if hos24:
            bits.append(f"{hos24} HOS violation{'s' if hos24 != 1 else ''}")
        return {
            "text": f"Biggest drag is safety: {' and '.join(bits)} in last 24h &mdash; review page 3.",
            "metric": "safety", "kind": "bad",
        }

    actual_rpm = (w7a or {}).get("rpm")
    actual_dh = (w7a or {}).get("deadhead")
    miles = (w7a or {}).get("miles")
    goal_rpm = (rpm_goal or {}).get("goal_rpm")
    total31 = (qb_ar or {}).get("total31") or 0

    rpm_impact = 0.0
    if _isnum(actual_rpm) and _isnum(goal_rpm) and _isnum(miles) and goal_rpm > 0:
        rpm_impact = max(0.0, float(goal_rpm) - float(actual_rpm)) * float(miles)
    dh_impact = 0.0
    if _isnum(actual_dh) and _isnum(miles) and _isnum(actual_rpm):
        excess = max(0.0, float(actual_dh) - TARGET_DEADHEAD)
        dh_impact = excess * float(miles) * float(actual_rpm)
    ar_impact = float(total31) if _isnum(total31) else 0.0

    scored = [("rpm", rpm_impact), ("deadhead", dh_impact), ("ar", ar_impact)]
    worst, score = max(scored, key=lambda x: x[1])
    if score < 1.0:
        return {
            "text": "All operational metrics within goal this week &mdash; no drag detected.",
            "metric": "clean", "kind": "good",
        }

    sub = _seven_day_asset_loads(alvys_sheets, now=now) if worst in ("rpm", "deadhead") else None
    text = None
    if worst == "rpm" and sub is not None:
        text = _attribute_rpm_drag(sub, goal_rpm)
    elif worst == "deadhead" and sub is not None:
        text = _attribute_deadhead_drag(sub)
    elif worst == "ar":
        text = _attribute_ar_drag(qb_ar)
    if not text:
        return None
    return {"text": text, "metric": worst, "kind": "bad"}


# ----------------------------------------------------------------------
# Page builders
# ----------------------------------------------------------------------
def build_page1(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, date_str,
                alvys_ar=None, warnings=None, data_asof=None, rpm_trend=None, rpm_goal=None,
                rpm_goal_trend=None, drag=None, margin_projection=None) -> str:
    co = qb_company_totals(qb_pnl) if qb_pnl else {}
    w7 = (alvys or {}).get("7d", {})
    wmtd = (alvys or {}).get("mtd", {})
    w7a = ((alvys or {}).get("asset") or {}).get("7d", w7)  # X-Trux/XFreight 7d
    # X-Trux/XFreight MTD — same Power BI-aligned basis (revenue / Loaded
    # miles) that feeds the Revenue/Mile and Dead head % tiles. The bottom-
    # line blurb uses this so its RPM/DH numbers tie to the Power BI report
    # row-for-row instead of drifting on a 7d-rolling window readers can't
    # cross-check.
    wmtda = ((alvys or {}).get("asset") or {}).get("mtd", wmtd)

    fleet = (alvys or {}).get("fleet", {})
    empty_td = "<td width='25%' style='padding:6px;'></td>"
    recv_left = ("<td width='25%' valign='top' style='padding:6px;'>"
                 + _tile_div("Total receivables &middot; AR", money(qb_ar.get("total_ar") if qb_ar else None), _pill("X-Trux + X-Linx", "mute"))
                 + _tile_div("AR 31+ overdue", money(qb_ar.get("total31") if qb_ar else None), _pill("see pg 4", "bad"))
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
    # Revenue/mile MUST come from _alvys_metrics so numerator and denominator
    # share the same load filter (all non-cancelled X-Trux/XFreight MTD) —
    # matching Power BI's "Rev per Mile" measure. If we instead compute
    # _xt_rev / _xt_miles, the numerator is compute_alvys_entities's
    # settled-only revenue but the denominator is _alvys_metrics's
    # all-non-cancelled Loaded mileage, which inflates the ratio while
    # loads are still settling mid-month.
    _xt_rev = _xt.get("revenue")
    _xt_loads, _xt_miles = _xt.get("loads"), fleet.get("miles")
    _xt_rpm = ((alvys or {}).get("asset") or {}).get("mtd", {}).get("rpm")
    _xt_rpl = (_xt_rev / _xt_loads) if (_isnum(_xt_rev) and _isnum(_xt_loads) and _xt_loads) else None
    # Tile order pairs mileage with rev/mile (slots 1 & 2) and loads with
    # rev/load (slots 3 & 4) so each $/X ratio sits next to its denominator.
    xtrux_r1 = (_tile("X-Trux Mileage &middot; MTD", num(_xt_miles), _pill("X-Trux + XFreight", "mute"))
                + _tile("Revenue / mile &middot; MTD", rpm(_xt_rpm), _pill("X-Trux", "mute"))
                + _tile("X-Trux Loads &middot; MTD", num(_xt_loads), _pill("X-Trux + XFreight", "mute"))
                + _tile("Revenue / load &middot; MTD", money(_xt_rpl), _pill("X-Trux", "mute")))
    _xt_asset = ((alvys or {}).get("asset") or {}).get("mtd", {})
    # Empty miles first (the raw number), Dead head % next (the ratio).
    xtrux_r2 = (_tile("Empty miles &middot; MTD", num(_xt_asset.get("empty")), _pill("X-Trux + XFreight", "mute"))
                + _tile("Dead head % &middot; MTD", pct(_xt_asset.get("deadhead")),
                        f"goal &le;{pct(TARGET_DEADHEAD)} " + _pill("DH", _flag_kind(_xt_asset.get("deadhead"), TARGET_DEADHEAD, True)))
                + _tile("Active trucks &middot; MTD", num(fleet.get("active_trucks")), _pill("X-Trux + XFreight", "mute"))
                + _tile("Avg miles / truck &middot; MTD", num(fleet.get("miles_per_truck")), _pill("X-Trux + XFreight", "mute")))
    margin_tile = _tile("XFreight Margin &middot; MTD", money(_co_margin or None), _pill("revenue &minus; cost", "mute"))
    t1 = (_tile("XFreight Revenue &middot; MTD", money(_co_rev or None), _pill("X-Trux + X-Linx", "mute"))
          + pay_tile
          + margin_tile
          + _tile("Gross margin &middot; MTD", pct(_co_mpct), ""))
    # Row 2: loads + estimated month-end margin per entity. The projection
    # equation comes from compute_margin_projection():
    #   projected_revenue = booked MTD revenue * (days_in_month / day_of_month)
    #   projected_margin  = projected_revenue * trailing-90 settled margin %
    # Pill shows the day ratio and trailing margin % so the basis is visible.
    _mp = margin_projection or {}
    _dim = _mp.get("days_in_month", 0)
    _de = _mp.get("day_of_month", 0)
    _td = _mp.get("trailing_days", 90)
    _month_lbl = pd.Timestamp.now().strftime("%B")
    def _proj_tile(ent_key, pill_text):
        ent = _mp.get(ent_key) or {}
        sub = (_pill(pill_text, "mute")
               + f" &middot; {_de}/{_dim}d &middot; t{_td} {pct(ent.get('trailing_margin_pct'))}")
        return _tile(f"Est. {_month_lbl} margin", money(ent.get("projected_margin")), sub)
    # Order: Combined projection in the leftmost slot (visually anchors the
    # row's lead number), per-entity projections in the middle, and the plain
    # Loads count on the right.
    t1b = (_proj_tile("combined", "X-Trux + X-Linx")
           + _proj_tile("X-Trux", "X-Trux")
           + _proj_tile("X-Linx", "X-Linx")
           + loads_tile)
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

    # X-Trux rate-per-mile goal: fully-loaded cost per mile (driver pay + shared
    # office overhead), then the profit-loaded goal rate, vs. what we actually run.
    g = rpm_goal or {}
    goal_tiles = goal_note = ""
    if g:
        _or = g.get("target_or")
        _margin = g.get("target_margin")
        _no_profit = (not _isnum(_margin)) or abs(_margin) < 1e-9
        # Goal tile pill: flag whether profit is baked in yet, and how the actual rate stacks up.
        if _no_profit:
            goal_pill = _pill("break-even &middot; set profit %", "warn")
        else:
            goal_pill = _pill(f"{pct(_margin)} net &middot; OR {_or:.2f}", "good")
        gap = g.get("gap")
        if _isnum(gap):
            gap_kind = "good" if gap <= 0 else "bad"  # actual >= goal is good
            gap_sub = _pill(("at/above goal" if gap <= 0 else "below goal"), gap_kind)
            gap_val = rpm(abs(gap))
        else:
            gap_kind, gap_sub, gap_val = "mute", _pill("need QB P&amp;L", "mute"), "n/a"
        # Cost-per-mile sub-pill spells out the time windows behind each
        # component so readers can audit the basis at a glance:
        #   driver pay = trailing N-day window (10d default, widens to
        #               30/60/90 on light weeks via RPM_GOAL_FALLBACK_WINDOWS)
        #   overhead   = fiscal-YTD (QB P&L is "This Fiscal Year")
        _pay_win = g.get("pay_window_used") or g.get("pay_window_days") or "?"
        goal_tiles = (
            _tile("Cost / mile &middot; X-Trux", rpm(g.get("cost_per_mile")),
                  _pill(f"{_pay_win}d pay + YTD overhead", "mute"))
            + _tile("Goal rate / mile", rpm(g.get("goal_rpm")), goal_pill)
            + _tile("Actual / mile &middot; recent", rpm(g.get("actual_rpm")),
                    _pill(f"Costing Based on Last {g.get('pay_window_used') or g.get('pay_window_days')} Days", "mute"))
            + _tile("Gap to goal / mile", gap_val, gap_sub))
        # Plain-language breakdown so the number is auditable from the email itself.
        _pp, _oh, _cpm = g.get("pay_per_mile"), g.get("overhead_per_mile"), g.get("cost_per_mile")
        _win = g.get("pay_window_used") or g.get("pay_window_days")
        parts = []
        if _isnum(_pp):
            parts.append(f"driver/owner-op pay {rpm(_pp)}/mi (last {_win}d)")
        if _isnum(_oh):
            cos = g.get("overhead_companies") or []
            _alloc = g.get("overhead_alloc")
            _xt_oh = g.get("overhead_per_mile_xtrux_only")
            oh_txt = f"office overhead {rpm(_oh)}/mi ({' + '.join(cos) or 'QB'} Total Expenses &divide; YTD miles"
            if _isnum(_alloc) and abs(_alloc - 1.0) > 1e-9:
                oh_txt += f" &times; {_alloc:.0%} allocation"
            if _isnum(_xt_oh):
                oh_txt += f"; X-Trux-only {rpm(_xt_oh)}/mi"
            oh_txt += ")"
            parts.append(oh_txt)
        breakdown = " + ".join(parts) if parts else "awaiting data"
        if _isnum(_cpm):
            msg = f"Fully-loaded cost to run an X-Trux mile is <b>{rpm(_cpm)}</b> = {breakdown}. "
            if _no_profit:
                msg += ("No profit is baked in yet, so the goal equals cost &mdash; tell me the target "
                        "margin and I&rsquo;ll set <code>RPM_GOAL_TARGET_OR</code> to layer it on "
                        f"(e.g. 10% net &rarr; goal {rpm((_cpm or 0)/0.90)}/mi).")
            else:
                msg += (f"Goal of <b>{rpm(g.get('goal_rpm'))}</b>/mi bakes in {pct(_margin)} net margin "
                        f"({rpm(g.get('profit_per_mile'))}/mi profit) on top of cost.")
            if _isnum(g.get("worksheet_cost_per_mile")):
                msg += (f" Sanity check: the manual Goals &amp; Trends model puts overhead near "
                        f"{rpm(g.get('worksheet_overhead'))}/mi (cost ~{rpm(g.get('worksheet_cost_per_mile'))}/mi).")
            goal_kind = "good" if (_isnum(gap) and gap <= 0) else "warn"
            goal_note = _brief(msg, goal_kind)
        else:
            goal_note = _brief("Rate-per-mile cost is pending the QuickBooks P&amp;L this run "
                               "(office overhead comes from X-Trux + X-Linx Total Expenses).", "mute")

    # X-Trux cost / goal / actual revenue per mile — 6-month trend. Cost and goal
    # only render when the QB overhead leg is available (held flat at the YTD rate);
    # actual rev/mile always renders. Lets the goal read as a living line.
    gt = rpm_goal_trend or {}
    goal_trend_row = ""
    if gt.get("labels") and (gt.get("cost") or gt.get("actual")):
        _gt_sub = "monthly &middot; X-Trux + XFreight &middot; *MTD"
        goal_trend_row = (
            _bar_chart("Cost / mile", gt["labels"], gt.get("cost") or [],
                       "overhead held at YTD rate &middot; *MTD", fmt=rpm)
            + _bar_chart("Goal / mile", gt["labels"], gt.get("goal") or [], _gt_sub, fmt=rpm)
            + _bar_chart("Actual / mile", gt["labels"], gt.get("actual") or [], _gt_sub, fmt=rpm)
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
    # Five buckets render across two rows so the 91+ split stays prominent
    # rather than being hidden inside a combined 61+ tile.
    aar = alvys_ar or {}
    alvys_ar_row = ""
    alvys_ar_row_b = ""
    if aar.get("total"):
        alvys_ar_row = (
            _tile("Alvys AR &middot; Current", money(aar.get("current")), _pill("not overdue", "mute"))
            + _tile("Alvys AR &middot; 1&ndash;30 days", money(aar.get("d1_30")), _pill("past due", "warn"))
            + _tile("Alvys AR &middot; 31&ndash;60 days", money(aar.get("d31_60")), _pill("escalate", "warn"))
            + _tile("Alvys AR &middot; 61&ndash;90 days", money(aar.get("d61_90")), _pill("escalate", "bad"))
        )
        alvys_ar_row_b = (
            _tile("Alvys AR &middot; 91+ days", money(aar.get("d91plus")), _pill("collections", "bad"))
            + empty_td + empty_td + empty_td
        )

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

    _goal_rpm = (rpm_goal or {}).get("goal_rpm")
    _goal_txt = f"goal {rpm(_goal_rpm)}" if _isnum(_goal_rpm) else "goal pending QB cost-out"
    # Every number gets an explicit scope/window so the blurb is comparable to
    # other views in the email and to Power BI (which uses different windows).
    bottom = (f"{_lead_phrase(wmtd, rpm_goal)} "
              f"For X-Trux/XFreight asset loads (MTD): "
              f"RPM {rpm(wmtda.get('rpm'))} ({_goal_txt}), "
              f"deadhead {pct(wmtda.get('deadhead'))} (goal &le;{pct(TARGET_DEADHEAD)}). "
              f"{money(qb_ar.get('total31') if qb_ar else None)} is 31+ days overdue per QuickBooks "
              f"(X-Trux + X-Linx snapshot &mdash; see pg 4). "
              f"Safety: {swv('events', '24h')} events &amp; {swv('hos', '24h')} HOS violations &middot; last 24h.")
    if drag and drag.get("text"):
        bottom += f" {drag['text']}"

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
            + (f"{_section('X-Trux Rate-per-Mile Goal &middot; cost-out')}<tr>{goal_tiles}</tr>{goal_note}"
               + (f"<tr>{goal_trend_row}</tr>" if goal_trend_row else "")
               if goal_tiles else "")
            + f"{_section('X-Linx Overview')}<tr>{xlinx_tiles}</tr>"
            f"{_section('Receivables &amp; payables &mdash; 6-month balance trend')}<tr>{recv_left}{ar_chart}{ap_chart}</tr>"
            f"{_brief(ar_insight, 'bad' if ar_rising else 'good')}"
            + (f"{_section('Alvys AR &mdash; aging by due date &middot; X-Trux + X-Linx open invoices')}<tr>{alvys_ar_row}</tr><tr>{alvys_ar_row_b}</tr>"
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

    return (f"{_header('Safety &amp; Compliance Detail &mdash; last 24h &middot; X-Trux / XFreight fleet', 3, date_str)}"
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
    return (f"{_header('Accounts Receivable &mdash; Overdue (31+ days)', 4, date_str)}"
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
             + _tile("Avg miles / driver", num(m.get("avg_per_driver")),
                     _pill("this week", "mute")
                     + " &middot; "
                     + _pill(f"avg {num(m.get('avg_drivers_per_week'))} drivers/wk", "mute")))

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
            + hcell("Total", "right") + hcell("Avg / wk", "right")
            + hcell("Start &rarr; End &middot; this week", "left") + "</tr>")

    body = ""
    for r in rows:
        wk_cells = "".join(
            mcell(num(r["weeks"][k]) if r["weeks"][k] else "&ndash;", "right", cur=(k == cur))
            for k in range(SETTLEMENT_WEEKS))
        avg_wk = (r["total"] / SETTLEMENT_WEEKS) if SETTLEMENT_WEEKS else 0
        body += ("<tr>"
                 + mcell(r["driver"], "left")
                 + mcell(r["trucks"] or "&ndash;", "left")
                 + wk_cells
                 + mcell(num(r["total"]), "right", bold=True)
                 + mcell(num(avg_wk), "right")
                 + mcell(r["start_end"] or "&ndash;", "left", small=True)
                 + "</tr>")
    if rows:
        def tcell(text, al="right", cur=False):
            bg = f"background:{ACCENTBG};" if cur else ""
            return (f"<td align='{al}' style='padding:9px 8px;font-size:12.5px;font-weight:800;color:{INK};"
                    f"border-top:2px solid {LINE};{bg}'>{text}</td>")
        # Total row's "Avg / wk" cell averages the column totals — same as
        # grand_total / SETTLEMENT_WEEKS, but spelled as the row average so
        # column math is verifiable.
        grand_avg = (m.get("grand_total") / SETTLEMENT_WEEKS) if SETTLEMENT_WEEKS else 0
        body += ("<tr>" + tcell("Total", "left") + tcell("", "left")
                 + "".join(tcell(num(week_totals[k]), "right", cur=(k == cur)) for k in range(SETTLEMENT_WEEKS))
                 + tcell(num(m.get("grand_total")), "right")
                 + tcell(num(grand_avg), "right")
                 + tcell("", "left") + "</tr>")
    else:
        body = (f"<tr><td colspan='9' style='padding:12px 8px;color:{MUTE};font-size:12.5px;'>"
                f"No delivered legs in the last {SETTLEMENT_WEEKS} settlement weeks.</td></tr>")

    table = (f"<tr><td colspan='4' style='padding:0 6px;'><table width='100%' cellpadding='0' cellspacing='0' "
             f"style='border:1px solid {LINE};border-radius:8px;border-collapse:separate;overflow:hidden;'>"
             f"{head}{body}</table></td></tr>")

    return (f"{_header('Driver Mileage by Settlement Week &mdash; X-Trux / XFreight fleet', 2, date_str)}"
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


def build_page9(samba, date_str) -> str:
    header = _header('Driver Compliance &mdash; SambaSafety', 9, date_str)
    footer = (f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;'>"
              f"License numbers masked to last 4. Violations show the last {VIOLATION_WINDOW_DAYS} days. "
              f"Source: SambaSafety driver monitoring.</div>")
    if not samba or not samba.get("monitored"):
        return (f"{header}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
                f"{_section('Driver compliance &middot; SambaSafety')}"
                f"<tr><td colspan='4' style='padding:14px 6px;color:{MUTE};font-size:12.5px;'>"
                f"SambaSafety data unavailable this run.</td></tr>{footer}")

    def _md(ts):
        return "&mdash;" if pd.isna(ts) else f"{ts.month}/{ts.day}/{ts.strftime('%y')}"

    issues = samba["license_issues"]
    viol = samba["violations"]
    n_issue = len(issues)
    n_viol = len(viol)
    n_high = len(samba["high_risk"])
    avg = samba["avg_score"]

    tiles = (_tile("Monitored drivers", num(samba["monitored"]), _pill("enrolled", "mute"))
             + _tile("License issues", num(n_issue),
                     _pill("suspended / expired / &le;30d", "bad" if n_issue else "good"))
             + _tile(f"New violations &middot; {samba['window_days']}d", num(n_viol),
                     _pill("MVR alerts", "warn" if n_viol else "good"))
             + _tile("High-risk drivers", num(n_high),
                     (f"avg score {avg:.0f} " if avg is not None else "")
                     + _pill("elevated", "bad" if n_high else "good")))

    if issues:
        lrows = ""
        for d in issues:
            exp_txt = _md(d["exp"])
            if d["days_to_exp"] is not None and d["ok"] and d["expiring"]:
                exp_txt += f" ({d['days_to_exp']}d)"
            lrows += _tr(
                [d["name"], d["state"] or "&mdash;", _mask_license(d["license"]), d["status"], exp_txt,
                 (f"{d['score']:.0f}" if d["score"] is not None else "&mdash;")],
                ["left", "left", "left", "left", "left", "right"],
                [None, None, None, ("bad" if not d["ok"] else "warn"),
                 ("bad" if not d["ok"] else "warn"), ("bad" if d["high"] else None)])
        license_block = _table(["Driver", "State", "License #", "Status", "Expires", "Risk"],
                               ["left", "left", "left", "left", "left", "right"], lrows)
    else:
        license_block = _brief("All monitored drivers have a valid, current license.", "good")

    if viol:
        vrows = ""
        for v in viol:
            sev = str(v["severity"]).lower()
            kind = "bad" if any(s in sev for s in ("major", "serious", "high", "disq")) else "warn"
            vrows += _tr(
                [v["name"], _md(v["date"]), v["type"],
                 (num(v["points"]) if _isnum(v["points"]) else "&mdash;"),
                 v["state"] or "&mdash;", v["severity"] or "&mdash;"],
                ["left", "left", "left", "right", "left", "left"],
                [None, None, None, None, None, kind])
        viol_block = _table(["Driver", "Date", "Violation", "Pts", "State", "Severity"],
                            ["left", "left", "left", "right", "left", "left"], vrows)
    else:
        viol_block = _brief(f"No new violations or MVR alerts in the last {samba['window_days']} days.", "good")

    if samba["has_scores"]:
        rrows = ""
        for d in samba["ranked"][:10]:
            cat = d["category"] or ("High" if d["high"] else "")
            rrows += _tr(
                [d["name"], f"{d['score']:.0f}", cat or "&mdash;", d["status"]],
                ["left", "right", "left", "left"],
                [None, ("bad" if d["high"] else None), ("bad" if d["high"] else None),
                 (None if d["ok"] else "bad")])
        risk_block = _table(["Driver", "Risk score", "Category", "License"],
                            ["left", "right", "left", "left"], rrows)
    else:
        risk_block = _brief("Risk scores not present in this export.", "mute")

    return (f"{header}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('License status &middot; action needed')}{license_block}"
            f"{_section('Recent violations &amp; MVR alerts &middot; last ' + str(samba['window_days']) + ' days')}{viol_block}"
            f"{_section('Risk leaderboard &middot; highest-scoring drivers')}{risk_block}"
            f"{footer}")


def build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing,
               alvys_ar=None, warnings=None, data_asof=None, mileage=None, uninvoiced=None,
               rpm_trend=None, rpm_goal=None, rpm_goal_trend=None, samba=None, drag=None,
               margin_projection=None) -> str:
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
            f"{wrap(note + build_page1(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, date_str, alvys_ar=alvys_ar, warnings=warnings, data_asof=data_asof, rpm_trend=rpm_trend, rpm_goal=rpm_goal, rpm_goal_trend=rpm_goal_trend, drag=drag, margin_projection=margin_projection))}{pb}"
            # Driver Mileage runs immediately after the Executive Brief (whose
            # last section is X-Linx Overview) so the per-driver weekly view
            # follows the entity-level summary. Safety and AR pages then come
            # behind it. Function names build_page<N> are kept for stability,
            # but the page-number arguments in _header reflect the actual
            # render order.
            f"{wrap(build_page4(mileage, date_str))}{pb}"
            f"{wrap(build_page2(samsara, date_str))}{pb}"
            f"{wrap(build_page3(qb_ar, date_str))}{pb}"
            f"{wrap(build_page5(uninvoiced, date_str))}{pb}"
            f"{wrap(build_page6(alvys_ar, date_str))}{pb}"
            f"{wrap(build_page7(qb_ar, alvys_ar, date_str))}{pb}"
            f"{wrap(build_page8(qb_ar, alvys_ar, date_str))}{pb}"
            f"{wrap(build_page9(samba, date_str))}"
            f"</body></html>")


# ----------------------------------------------------------------------
# Orchestration (testable without network)
# ----------------------------------------------------------------------
def build_report(alvys_sheets, pnl_sheets, ar_sheets, ar_hist_sheets, ap_hist_sheets, samsara_sheets, missing,
                 alvys_pipeline_sheets=None, data_asof=None, sambasafety_sheets=None) -> str:
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
    rpm_goal = compute_rpm_goal(alvys_sheets, qb_pnl) if alvys_sheets else None
    rpm_goal_trend = compute_rpm_goal_trend(alvys_sheets, rpm_goal) if alvys_sheets else None
    margin_projection = compute_margin_projection(alvys_sheets) if alvys_sheets else None
    warnings = _alvys_health(alvys_sheets) if alvys_sheets else []
    warnings += _rpm_goal_health(rpm_goal)
    for w in warnings:
        log.warning("Alvys data check: %s", w)
    samba = compute_sambasafety(sambasafety_sheets) if sambasafety_sheets else None
    w7a = ((alvys or {}).get("asset") or {}).get("7d") or (alvys or {}).get("7d")
    drag = compute_drag_attribution(alvys_sheets, qb_ar, w7a, rpm_goal, samsara)
    return build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing,
                      alvys_ar=alvys_ar, warnings=warnings, data_asof=data_asof, mileage=mileage,
                      uninvoiced=uninvoiced, rpm_trend=rpm_trend, rpm_goal=rpm_goal,
                      rpm_goal_trend=rpm_goal_trend, samba=samba, drag=drag,
                      margin_projection=margin_projection)


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
    # Rate-per-mile goal cost-out. No QuickBooks here (offline), so office overhead
    # is unavailable; this prints the driver-pay-per-mile leg and the goal math so
    # the per-mile inputs can be eyeballed. The live email adds the QB overhead leg.
    goal = compute_rpm_goal(sheets, qb_pnl=None)
    print("X-Trux rate-per-mile goal (driver-pay leg only; QuickBooks overhead added in the live run)")
    if goal:
        print(f"  driver/owner-op pay  {rpm(goal['pay_per_mile']):>8} / mile   (last {goal['pay_window_days']}d, {num(goal['pay_miles'])} mi)")
        print(f"  actual revenue       {rpm(goal['actual_rpm']):>8} / mile")
        print(f"  office overhead      {'n/a':>8} / mile   (needs QuickBooks P&L)")
        print(f"  worksheet overhead   {rpm(goal['worksheet_overhead']):>8} / mile   (Goals and Trends.xlsx reference)")
        print(f"  fiscal-YTD miles     {num(goal['ytd_miles']):>8}")
        print(f"  target operating ratio {goal['target_or']:.2f}  ({pct(goal['target_margin'])} net margin)\n")
    else:
        print("  (no X-Trux asset loads found)\n")
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
    samba_path = os.environ.get("SCORECARD_SAMBASAFETY_PATH", "SambaSafety/SambaSafety_Master.xlsx")

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
    # SambaSafety is optional — don't flag it as "missing" if the export isn't set up yet.
    samba_sheets = _safe_read(token, upn, samba_path, [], "SambaSafety Master")

    # Preflight summary — first thing readable in the Actions log. Tells you
    # immediately if a wrong path silently blanked a section.
    preflight = [
        ("Alvys Master 2026", alvys_path, alvys_sheets, True),
        ("Alvys Pipeline", alvys_pipeline_path, alvys_pipeline_sheets, True),
        ("QB P&L", f"{qb_dir}/QB_ProfitAndLoss.xlsx", pnl_sheets, True),
        ("QB AR aging", f"{qb_dir}/QB_AgedReceivableDetail.xlsx", ar_sheets, True),
        ("QB AR history", f"{qb_dir}/QB_AR_History.xlsx", ar_hist_sheets, True),
        ("QB AP history", f"{qb_dir}/QB_AP_History.xlsx", ap_hist_sheets, True),
        ("Samsara Master", samsara_path, samsara_sheets, True),
        ("SambaSafety Master", samba_path, samba_sheets, False),
    ]
    n_found = sum(1 for _l, _p, s, _r in preflight if s is not None)
    log.info("OneDrive preflight: %d of %d expected files found", n_found, len(preflight))
    for label, path, sheets, required in preflight:
        if sheets is not None:
            rows = sum(len(df) for df in sheets.values())
            log.info("  FOUND    %-22s %s  (%d sheet(s), %d rows)", label, path, len(sheets), rows)
        elif required:
            log.warning("  MISSING  %-22s %s  (required)", label, path)
        else:
            log.info("  absent   %-22s %s  (optional)", label, path)
    if missing:
        log.warning("Required files missing: %s — those sections will be blank.", ", ".join(missing))

    html = build_report(alvys_sheets, pnl_sheets, ar_sheets, ar_hist_sheets, ap_hist_sheets, samsara_sheets, missing,
                        alvys_pipeline_sheets=alvys_pipeline_sheets, data_asof=data_asof,
                        sambasafety_sheets=samba_sheets)
    subject = f"XFreight Executive Brief — {datetime.now():%b %d, %Y}"
    send_email(token, from_upn, to_emails, subject, html)
    # Archive the brief for the Karpathy-Wiki librarian to compile.
    try:
        from src.karpathy_writer import frontmatter, save
        body = frontmatter("Executive Brief", "scorecard",
                           subject=subject.replace(":", "—")) + html
        save("scorecard", "executive-brief", body)
    except Exception as exc:
        log.warning("Karpathy-Wiki archive skipped: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
