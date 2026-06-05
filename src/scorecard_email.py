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
    SCORECARD_SAMBASAFETY_PATH default "SambaSafety/SambaSafety_Master.xlsx" (optional, page 2)
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
import datetime as _dt
from datetime import datetime

import pandas as pd
import requests
from dotenv import load_dotenv

from pathlib import Path
from src.onedrive_upload import (
    download_file, download_shared_file, ensure_folder, get_file_modified,
    get_shared_modified, get_token, upload_file,
)

log = logging.getLogger("scorecard_email")


def _today_chicago_key() -> str:
    """Today's date in America/Chicago time, as 'YYYY-MM-DD'. Used to key
    the 'sent today' idempotency marker — the brief is a Chicago-morning
    artifact, so the marker should roll at Chicago midnight, not UTC."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


_SENT_MARKER_FOLDER = "Scorecard"
GRAPH = "https://graph.microsoft.com/v1.0"

# Targets pulled from your Goals workbooks
TARGET_RPM = 2.92
TARGET_DEADHEAD = 0.06
TARGET_OR = 0.95
COACH_EVENT_THRESHOLD = 2  # drivers with >= this many safety events in window need coaching
DRIVER_TARGET_MILES = 2750  # weekly miles target for the mileage page below-target tile

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
# Liability insurance was tracked as a separate $0.07/mi line while the office-
# overhead calc lagged behind the rate hike. With overhead now pinned at $0.92/mi
# (RPM_GOAL_OVERHEAD_PIN) which already absorbs the insurance increase, this
# surcharge is zeroed so it doesn't double-count.  Re-enable if you ever
# decouple insurance from overhead again.
RPM_GOAL_INSURANCE_SURCHARGE = 0.0
# Office overhead per mile is pinned to a hand-set value while the costing
# algorithm is being validated against the books. Set to None (or empty the
# RPM_GOAL_OVERHEAD_PIN env var) to let the live QB-derived calculation flow
# through unmodified. The live value is still computed and stashed for the
# data-check banner so we can watch the two converge.
# $0.98 = baseline office overhead + the liability-insurance increase folded
# in (the separate $0.07/mi surcharge line was removed when this was bumped
# from $0.92 to $0.98, so insurance is no longer double-counted).
RPM_GOAL_OVERHEAD_PIN = 0.98
# Fail-soft guards: if the short pay window is too thin to trust, widen it; if the
# resulting cost lands outside a sane band, flag it on the email's data-check banner.
RPM_GOAL_MIN_SETTLED_LOADS = 5      # need at least this many settled X-Trux loads…
RPM_GOAL_MIN_WINDOW_MILES = 5000    # …and this many miles, else widen the window
RPM_GOAL_FALLBACK_WINDOWS = (30, 60, 90)   # widen to these (days) in order
RPM_GOAL_PLAUSIBLE_BAND = (1.50, 5.00)     # cost/mi outside this is flagged

# SambaSafety driver-compliance thresholds (page 2).
LICENSE_EXPIRY_WARN_DAYS = 30     # flag licenses expiring within this many days
SAMBA_HIGH_RISK_SCORE = 70        # fallback high-risk cutoff when no risk category column
VIOLATION_WINDOW_DAYS = 90        # MVR violations: surface the last 90d so the tile/page reflect recent risk, not the full year of historical record
                                  # alerts — a year matches how SambaSafety surfaces them

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
    return f"${x:.3f}" if _isnum(x) else "n/a"


def rpm2(x) -> str:
    """Two-decimal $/mi for tight trend-chart labels where the 3-decimal
    rpm format ("$2.687") is wider than the column. Tiles + narratives keep
    using rpm()."""
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


def _rollover_state(mtd_revenue_loads: int) -> tuple[bool, pd.Timestamp | None,
                                                     pd.Timestamp | None, str]:
    """Detect the month-rollover edge case where MTD has just turned over and
    every MTD tile would otherwise read 'n/a'. Active when we're on day 1-3
    of a month AND not a single load with non-zero revenue has landed for
    the new month yet — i.e., there is literally nothing to show. As soon
    as the FIRST revenue-bearing load lands (or the 4th of the month rolls
    in), rollover flips off and the brief reverts to live MTD actuals.

    Returns `(active, last_month_start, last_month_end, mtd_label)`. The
    label is 'MTD' when inactive and e.g. 'May 2026' when active — caller
    surfaces it on tile labels and a banner."""
    now = pd.Timestamp.now()
    if now.day > 3 or mtd_revenue_loads >= 1:
        return False, None, None, "MTD"
    mtd_start = now.normalize().replace(day=1)
    lm_end = mtd_start - pd.Timedelta(seconds=1)
    lm_start = lm_end.normalize().replace(day=1)
    return True, lm_start, lm_end, lm_start.strftime("%b %Y")


# ----------------------------------------------------------------------
# Alvys operational KPIs (from the manual Alvys Master 2026 file)
# ----------------------------------------------------------------------
def _alvys_metrics(sub: pd.DataFrame) -> dict:
    # Power BI's DAX measure uses "Empty Dispatch Mileage / Total Dispatch
    # Mileage", but PBI sources those columns via a Trips→Loads join that
    # de-dupes when one Load has multiple Trips. Our scorecard reads the
    # Master 2026 Loads sheet directly, where "Loaded Dispatch Mileage" can
    # double-count for in-progress loads (one row per trip). The workbook's
    # "Loaded Miles" / "Empty Miles" columns are billed values per Load with
    # NO trip duplication, which is why those match PBI's monthly totals.
    # So we pick the billed columns first and only fall back to dispatch.
    revenue = _col_any(sub, ["Customer Revenue", "Revenue"]).sum()
    loaded = _col_any(sub, ["Loaded Miles", "Loaded Mileage", "Loaded Dispatch Mileage"]).sum()
    empty = _col_any(sub, ["Empty Miles", "Empty Mileage", "Empty Dispatch Mileage"]).sum()
    total = loaded + empty
    # Margin = Customer Revenue - Driver Rate, matching Power BI. Carrier Rate is
    # NOT added: the Driver Rate column is the full payout per load already.
    cost = float(_col(sub, "Driver Rate").fillna(0).sum())
    margin = revenue - cost
    return {
        "loads": len(sub),
        "revenue": revenue if revenue else None,
        "loaded": loaded if loaded else None,        # Loaded Dispatch Mileage
        "miles": total if total else None,           # Power BI "Dispatch Mileage" (loaded+empty)
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
    # Power BI excludes Cancelled loads from all metrics. Diagnostic (2026-06-02)
    # confirmed 15 Cancelled loads added +206 loaded / -85 empty miles vs PBI;
    # excluding them brings all mileage/DH%/RPM metrics into exact alignment.
    _status_col_name = _find_col(loads, ["load status", "status"])
    if _status_col_name:
        _n_before = len(loads)
        loads = loads[loads[_status_col_name].astype(str).str.strip().str.lower() != "cancelled"]
        _n_excl = _n_before - len(loads)
        if _n_excl:
            log.info("Excluded %d Cancelled loads to match Power BI view", _n_excl)
    # Power BI's monthly table only sums loads with Driver Rate > 0 (settled).
    # Pre-booked / unsettled loads carry Loaded Miles but no Empty Miles and no
    # Driver Rate, which is why our June trend showed 55 loads / 43,475 loaded
    # while PBI shows 36 / 22,596. Filter to settled here so all asset metrics
    # (tile + trend + entity P&L) operate on the same set as PBI.
    if "Driver Rate" in loads.columns:
        _n_before = len(loads)
        loads = loads[_col(loads, "Driver Rate").fillna(0) > 0]
        _n_excl = _n_before - len(loads)
        if _n_excl:
            log.info("Excluded %d unsettled loads (Driver Rate = 0) — matches Power BI view",
                     _n_excl)
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    _date_col_used = next(
        (c for c in ALVYS_DATE_CANDIDATES
         if c in loads.columns and _to_naive_dt(loads[c]).notna().sum() > 0),
        None
    )
    log.info("DIAG: Loads date column selected = %r", _date_col_used)
    _mi_cols = [c for c in loads.columns
                if any(t in c.lower() for t in ("mile", "mileage", "dispatch", "distance", "dh", "dead"))]
    log.info("DIAG: Loads mileage-related columns: %s", ", ".join(_mi_cols) or "(none)")
    _used_loaded = next((n for n in ["Loaded Mileage", "Loaded Dispatch Mileage", "Loaded Miles"]
                         if n in loads.columns), None)
    _used_empty  = next((n for n in ["Empty Mileage", "Empty Dispatch Mileage", "Empty Miles"]
                         if n in loads.columns), None)
    _used_total  = next((n for n in ["Total Dispatch Mileage", "Dispatch Mileage", "Total Miles", "Total Mileage"]
                         if n in loads.columns), None)
    log.info("DIAG: Mileage columns in use → loaded=%r  empty=%r  total=%r",
             _used_loaded, _used_empty, _used_total)
    w = _windows()
    # 24h/7d/30d remain bounded at `now` (rolling time windows). MTD matches
    # Power BI's calendar-month bucket: include EVERY load scheduled in this
    # month, even ones with future Scheduled Pickup dates. PBI's monthly
    # table does this — the previous `dates <= now` cap hid ~8 future-booked
    # June loads, making June dead-head read 3.7% vs PBI's 5.5%.
    now = w["now"]
    mtd_end = (w["mtd"] + pd.offsets.MonthEnd(1)).replace(hour=23, minute=59, second=59)
    prior_7d_start = w["7d"] - pd.Timedelta(days=7)
    capped_specs = (("24h", w["24h"]), ("7d", w["7d"]), ("30d", w["30d"]))
    out = {key: _alvys_metrics(loads[(dates >= start) & (dates <= now)])
           for key, start in capped_specs}
    out["mtd"] = _alvys_metrics(loads[(dates >= w["mtd"]) & (dates <= mtd_end)])
    # Prior 7-day window (14d-7d) for week-over-week change arrows.
    out["prior_7d"] = _alvys_metrics(loads[(dates >= prior_7d_start) & (dates < w["7d"])])

    # Month-rollover resilience: on day 1-3 of a month with NO revenue-bearing
    # loads yet, the tiles would all read 'n/a'. Swap MTD for the previous
    # completed month until the first revenue load lands (or day 4 rolls in).
    _mtd_rev = _col_any(loads[(dates >= w["mtd"]) & (dates <= now)],
                        ["Customer Revenue", "Revenue"]).fillna(0)
    mtd_revenue_loads = int((_mtd_rev > 0).sum())
    rollover, lm_start, lm_end, mtd_label = _rollover_state(mtd_revenue_loads)
    out["rollover"] = rollover
    out["mtd_label"] = mtd_label
    if rollover:
        out["rollover_start"] = lm_start
        out["rollover_end"] = lm_end
        lm_mask = (dates >= lm_start) & (dates <= lm_end)
        out["mtd"] = _alvys_metrics(loads[lm_mask])

    # RPM and deadhead are asset-carrier metrics — compute an X-Trux/XFreight-only
    # variant (exclude X-Linx brokerage) for those tiles.
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if office_col:
        is_asset = loads[office_col].map(_entity_group) == "X-Trux"
        a_loads, a_dates = loads[is_asset], dates[is_asset]
        out["asset"] = {key: _alvys_metrics(a_loads[(a_dates >= start) & (a_dates <= now)])
                        for key, start in capped_specs}
        # MTD: full calendar month including future-scheduled (matches PBI).
        out["asset"]["mtd"] = _alvys_metrics(
            a_loads[(a_dates >= w["mtd"]) & (a_dates <= mtd_end)])
        out["asset"]["prior_7d"] = _alvys_metrics(
            a_loads[(a_dates >= prior_7d_start) & (a_dates < w["7d"])])
        # Fleet metrics (X-Trux/XFreight, MTD): active trucks + miles per truck.
        if rollover:
            a_mtd_mask = (a_dates >= lm_start) & (a_dates <= lm_end)
            out["asset"]["mtd"] = _alvys_metrics(a_loads[a_mtd_mask])
            a_mtd = a_loads[a_mtd_mask]
        else:
            a_mtd = a_loads[(a_dates >= w["mtd"]) & (a_dates <= mtd_end)]
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
        # Structured verification log — compare these against Power BI's June row
        # (XFreight + X-Trux filter, current month). Key fields: Dispatch Mileage,
        # Empty Mileage, Dead Head %, Rev per Mile. Log every run so CI output
        # can be spot-checked when the email and PBI diverge.
        _vm = out["asset"]["mtd"]
        log.info("=" * 60)
        log.info("SCORECARD METRIC VERIFICATION (X-Trux+XFreight MTD)")
        log.info("  Loads           : %d", _vm.get("loads") or 0)
        log.info("  Revenue         : $%.2f", _vm.get("revenue") or 0)
        log.info("  Loaded miles    : %.0f  ← PBI 'Loaded Dispatch Mileage'", _vm.get("loaded") or 0)
        log.info("  Empty miles     : %.0f  ← PBI 'Empty Mileage'", _vm.get("empty") or 0)
        log.info("  Dispatch miles  : %.0f  ← PBI 'Dispatch Mileage' (loaded+empty)", _vm.get("miles") or 0)
        log.info("  Dead Head %%     : %.3f%%  ← PBI 'Dead Head %%'",
                 (_vm.get("deadhead") or 0) * 100)
        log.info("  Rev / Mile      : $%.4f  ← PBI 'Rev per Mile'", _vm.get("rpm") or 0)
        log.info("=" * 60)
        # Diagnostic: identify which loads are included vs Power BI's 23
        _status_col = _find_col(a_mtd, ["load status", "status"])
        if _status_col:
            log.info("DIAG X-Trux MTD status breakdown (%d loads):", len(a_mtd))
            for _sv, _sn in a_mtd[_status_col].value_counts().items():
                log.info("  %5d  %r", _sn, _sv)
        else:
            log.info("DIAG: No status column found; %d MTD loads", len(a_mtd))
        _lc = _find_col(a_mtd, ["loaded miles", "loaded mileage", "loaded dispatch"])
        _ec = _find_col(a_mtd, ["empty miles", "empty mileage", "empty dispatch"])
        _nc = _find_col(a_mtd, ["load number", "load #", "load num", "load id"])
        if _date_col_used and _date_col_used in a_mtd.columns:
            log.info("DIAG: X-Trux MTD sample rows (load, %s, status, loaded, empty):",
                     _date_col_used)
            for _, _r in a_mtd.head(15).iterrows():
                try:
                    _ld = float(_r[_lc]) if _lc and _r[_lc] == _r[_lc] else 0
                    _em = float(_r[_ec]) if _ec and _r[_ec] == _r[_ec] else 0
                except (TypeError, ValueError):
                    _ld, _em = 0, 0
                log.info("  load=%-10s  date=%s  status=%-22s  loaded=%.0f  empty=%.0f",
                         str(_r[_nc])[:10] if _nc else "?",
                         str(_r[_date_col_used])[:10],
                         str(_r[_status_col])[:22] if _status_col else "?",
                         _ld, _em)
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
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    mask = pd.Series(True, index=loads.index)
    if "Load Status" in loads.columns:
        mask &= loads["Load Status"].astype(str).str.lower() != "cancelled"
    # Default-path month-rollover resilience: when no explicit start/end was
    # passed and we're using MTD on day 1-3 of a new month, fall back to the
    # previous completed month UNTIL the first revenue-bearing load lands.
    if start is None and window_key == "mtd":
        mtd_start = _windows()["mtd"]
        _rev_mtd = _col_any(loads[dates >= mtd_start], ["Customer Revenue", "Revenue"]).fillna(0)
        rollover, lm_start, lm_end, _ = _rollover_state(int((_rev_mtd > 0).sum()))
        if rollover:
            start, end = lm_start, lm_end
    if start is None:
        start = _windows()[window_key]
    mask &= dates >= start
    if end is not None:
        mask &= dates < end if end < _windows()["now"] else dates <= end
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
        # Margin % matches the Power BI XFreight Report exactly:
        # Margin ÷ Revenue = (Revenue − Driver Rate) ÷ Revenue. Both
        # entities use this formula so the scorecard table and Power BI
        # tile read identically.
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


def compute_avg_fuel_price(alvys_pipeline_sheets: dict | None) -> float | None:
    """Average discounted price-per-gallon from the Alvys Fuel sheet (last 60 days)."""
    if not alvys_pipeline_sheets:
        return None
    fuel = alvys_pipeline_sheets.get("Fuel")
    if fuel is None or fuel.empty:
        return None
    date_col = _find_col(fuel, ["transaction date", "date"])
    ppu_col  = _find_col(fuel, ["discount ppu", "discountppu", "ppu", "price per unit"])
    if not ppu_col:
        return None
    prices = pd.to_numeric(fuel[ppu_col], errors="coerce")
    if date_col:
        try:
            cutoff = pd.Timestamp.now() - pd.Timedelta(days=60)
            dates = _to_naive_dt(fuel[date_col])
            prices = prices[dates >= cutoff]
        except Exception:
            pass
    prices = prices[(prices > 0.5) & (prices < 10.0)]  # sanity: $0.50–$10/gal
    return float(prices.mean()) if len(prices) else None


def compute_dh_trend(alvys_sheets: dict | None) -> dict:
    """Monthly dead-head % for last 6 months from Alvys Master 2026 Loads.

    Matches Power BI's DAX measure exactly (and the page-1 dead-head tile):
      Dead Head % = SUM(Empty Dispatch Mileage) / SUM(Total Dispatch Mileage)
    Scope: X-Trux asset side (X-Trux + XFreight; X-Linx excluded), Cancelled
    loads excluded, every load with Scheduled Pickup in the month is included
    (no MTD-cap on the current month — PBI's monthly table does the same).
    """
    empty = {"labels": [], "values": []}
    if not alvys_sheets:
        return empty
    loads = alvys_sheets.get("Loads")
    if loads is None or loads.empty:
        return empty
    _status_col = _find_col(loads, ["load status", "status"])
    if _status_col:
        loads = loads[loads[_status_col].astype(str).str.strip().str.lower() != "cancelled"]
    # Match PBI's monthly view: settled loads only (Driver Rate > 0). Same
    # filter as compute_alvys / compute_alvys_entities. See compute_alvys.
    if "Driver Rate" in loads.columns:
        loads = loads[_col(loads, "Driver Rate").fillna(0) > 0]
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if office_col:
        loads = loads[loads[office_col].map(_entity_group) == "X-Trux"]
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    # Use the billed Loads-sheet columns (same as _alvys_metrics) because the
    # workbook's "Loaded Dispatch Mileage" is one-row-per-trip and double-counts
    # for in-progress loads. Billed columns are one-row-per-load and match
    # what PBI's monthly table shows (which joins Trips de-duped to Loads).
    loaded_mi = _col_any(loads, ["Loaded Miles", "Loaded Mileage", "Loaded Dispatch Mileage"]).fillna(0)
    empty_mi  = _col_any(loads, ["Empty Miles", "Empty Mileage", "Empty Dispatch Mileage"]).fillna(0)
    total_mi  = loaded_mi + empty_mi
    _em_col = next((c for c in ["Empty Miles", "Empty Mileage", "Empty Dispatch Mileage"]
                    if c in loads.columns), None)
    _lo_col = next((c for c in ["Loaded Miles", "Loaded Mileage", "Loaded Dispatch Mileage"]
                    if c in loads.columns), None)
    log.info("dh_trend (Alvys Master 2026, X-Trux only): empty_col=%r loaded_col=%r "
             "rows_after_filter=%d", _em_col, _lo_col, len(loads))
    labels, values = [], []
    for i, (yy, mm) in enumerate(_last_6_months()):
        mask = (dates.dt.year == yy) & (dates.dt.month == mm)
        em = float(empty_mi[mask].sum())
        tot = float(total_mi[mask].sum())
        lab = pd.Timestamp(year=yy, month=mm, day=1).strftime("%b")
        if i == 5:
            lab += "*"
        labels.append(lab)
        values.append(round(em / tot * 100, 1) if tot > 0 else 0.0)
        if i == 5:
            log.info("dh_trend current month: %s empty=%.0f total=%.0f → %.2f%% "
                     "(loads in month=%d)",
                     lab, em, tot, (em / tot * 100) if tot > 0 else 0, int(mask.sum()))
    return {"labels": labels, "values": values}


def compute_ontime(alvys_pipeline_sheets: dict | None) -> dict:
    """On-time delivery rate from Alvys pipeline Loads (Scheduled vs Actual delivery)."""
    empty = {"rate": None, "on_time": 0, "total": 0, "available": False}
    if not alvys_pipeline_sheets:
        return empty
    loads = alvys_pipeline_sheets.get("Loads")
    if loads is None or loads.empty:
        return empty
    sched_col = _find_col(loads, ["scheduled delivery"])
    actual_col = _find_col(loads, ["actual delivery"])
    if not sched_col or not actual_col:
        return empty
    if "Load Status" in loads.columns:
        loads = loads[loads["Load Status"].astype(str).str.lower() != "cancelled"]
    # Scope to X-Trux + X-Linx to match the rest of the report
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if office_col:
        loads = loads[loads[office_col].map(_entity_group).isin(ENTITY_ORDER)]
    sched = _to_naive_dt(loads[sched_col])
    actual = _to_naive_dt(loads[actual_col])
    has_both = sched.notna() & actual.notna()
    if not has_both.any():
        return empty
    sub_sched = sched[has_both]
    sub_actual = actual[has_both]
    on_time = int((sub_actual <= sub_sched).sum())
    total = int(has_both.sum())
    # MTD window
    mtd_start = pd.Timestamp.now().normalize().replace(day=1)
    mtd_mask = has_both & (actual >= mtd_start)
    on_time_mtd = int((actual[mtd_mask] <= sched[mtd_mask]).sum())
    total_mtd = int(mtd_mask.sum())
    return {
        "rate": round(on_time / total * 100, 1) if total else None,
        "rate_mtd": round(on_time_mtd / total_mtd * 100, 1) if total_mtd else None,
        "on_time": on_time,
        "total": total,
        "on_time_mtd": on_time_mtd,
        "total_mtd": total_mtd,
        "available": True,
    }


def compute_customer_rpm(alvys_pipeline_sheets: dict | None, top_n: int = 15) -> list[dict]:
    """Revenue per mile by customer (MTD, X-Trux + X-Linx, sorted by RPM desc)."""
    if not alvys_pipeline_sheets:
        return []
    loads = alvys_pipeline_sheets.get("Loads")
    if loads is None or loads.empty:
        return []
    if "Load Status" in loads.columns:
        loads = loads[loads["Load Status"].astype(str).str.lower() != "cancelled"]
    office_col = _find_col(loads, OFFICE_COL_NEEDLES)
    if office_col:
        loads = loads[loads[office_col].map(_entity_group).isin(ENTITY_ORDER)]
    # MTD filter
    dates = _dates(loads, ALVYS_DATE_CANDIDATES)
    mtd_start = pd.Timestamp.now().normalize().replace(day=1)
    loads = loads[dates >= mtd_start]
    if loads.empty:
        return []
    cust_col = "Customer" if "Customer" in loads.columns else _find_col(loads, ["customer name", "customer"])
    if not cust_col:
        return []
    rev = _col_any(loads, ["Customer Revenue", "Revenue"]).fillna(0)
    miles = _col_any(loads, ["Total Dispatch Mileage", "Dispatch Mileage",
                              "Total Miles", "Total Mileage"]).fillna(0)
    customers = loads[cust_col].fillna("(unknown)").astype(str)
    rows: dict[str, dict] = {}
    for i, cust in enumerate(customers):
        if _is_ar_excluded(cust):
            continue
        d = rows.setdefault(cust, {"customer": cust, "revenue": 0.0, "miles": 0.0, "loads": 0})
        d["revenue"] += float(rev.iloc[i])
        d["miles"]   += float(miles.iloc[i])
        d["loads"]   += 1
    result = []
    for d in rows.values():
        if d["miles"] > 0 and d["revenue"] > 0:
            d["rpm"] = round(d["revenue"] / d["miles"], 3)
        else:
            d["rpm"] = None
        result.append(d)
    result.sort(key=lambda r: -(r["rpm"] or 0))
    return result[:top_n]


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

# Samsara driver records that are placeholders / test accounts, not real
# drivers. Normalized via _norm_name so punctuation/case variations match.
_DRIVER_EXCLUDE: frozenset[str] = frozenset({"tempd"})

# Trucks removed from the fleet. Idle / MPG / driver tables drop them so
# decommissioned units don't keep appearing in the brief after they're sold
# or returned. Match against the truck label produced by _truck_label
# (numeric strings, no ".0" suffix).
_TRUCK_EXCLUDE: frozenset[str] = frozenset({"44204"})


def _is_excluded_truck(unit) -> bool:
    if unit is None:
        return False
    return _truck_label(str(unit).strip()) in _TRUCK_EXCLUDE


def _is_excluded_driver(name) -> bool:
    """True if a Samsara driver name is a placeholder / test record that
    should be dropped from the brief (safety scores, mileage rankings, etc.)."""
    if name is None:
        return False
    n = _norm_name(name)
    return any(n == e or n.startswith(e + " ") for e in _DRIVER_EXCLUDE)

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
        days_remaining    = days_in_month - day_of_month
        daily_run_rate    = trailing_{days}_revenue / {days}
        projected_revenue = booked MTD revenue + daily_run_rate * days_remaining
        projected_margin  = projected_revenue * trailing_{days}_margin_pct

    The projection is "actuals booked so far + the recent daily pace applied to
    the rest of the month", which replaces the older naive month-pace
    extrapolation (booked * days_in_month / day_of_month). That naive form
    multiplied a single day's bookings by ~30 on day 1 and swung wildly early
    in the month; the run-rate form is anchored to the trailing daily revenue,
    so early-month estimates track reality. On the last day days_remaining is 0
    (and under month-rollover dom is forced to dim), so it collapses to pure
    actuals — the settled-margin floor below still applies. It is exactly the
    elapsed-fraction blend of month-pace and trailing run-rate.

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
    # Month-rollover resilience: on day 1-3 with no revenue-bearing loads yet,
    # the "EST. MARGIN" tile is meaningless (nothing to project from). Pivot
    # to last completed month until the first revenue load lands.
    _mtd_rev = _col_any(loads[mtd_mask], ["Customer Revenue", "Revenue"]).fillna(0)
    mtd_revenue_loads = int((_mtd_rev > 0).sum())
    rollover, lm_start, lm_end, mtd_label = _rollover_state(mtd_revenue_loads)
    if rollover:
        mtd_mask = (dates >= lm_start) & (dates <= lm_end) & not_cancelled
        dim = (lm_end.day)   # last completed month had this many days
        dom = dim            # treat it as "complete" so days_remaining = 0
        factor = 1.0
    # Days left in the (current or rolled-over) month — the run-rate projection
    # fills these remaining days at the recent daily pace. Under rollover dom
    # was forced to dim, so this is 0 and the projection equals booked actuals.
    days_remaining = max(dim - dom, 0)
    # Settled MTD mask: this month (or last month under rollover), non-cancelled,
    # with driver rate entered. Used to floor the projection at actual settled
    # margin — at month-end (or any time this month's actual margin% exceeds
    # the t90 blend) the estimate should never read below what we've actually
    # earned.
    settled_mtd_mask = mtd_mask.copy()
    if "Driver Rate" in loads.columns:
        settled_mtd_mask = settled_mtd_mask & (_col(loads, "Driver Rate").fillna(0) > 0)
    trail_start = now - pd.Timedelta(days=days)
    trail_mask = (dates >= trail_start) & (dates < now) & not_cancelled
    if "Driver Rate" in loads.columns:
        trail_mask = trail_mask & (_col(loads, "Driver Rate").fillna(0) > 0)

    out: dict = {"days_in_month": dim, "day_of_month": dom, "trailing_days": days}
    combined_booked = combined_t_rev = combined_t_cost = 0.0
    combined_settled_margin = 0.0

    for ent in ENTITY_ORDER:
        ent_mask = groups_all == ent
        booked = float(_col_any(loads[mtd_mask & ent_mask], ["Customer Revenue", "Revenue"]).sum())
        t_rev = float(_col_any(loads[trail_mask & ent_mask], ["Customer Revenue", "Revenue"]).sum())
        t_cost = float(_col(loads[trail_mask & ent_mask], "Driver Rate").fillna(0).sum())
        # Actual settled MTD margin for this entity — used as a floor on the
        # forward estimate so it never reports below what's already earned.
        s_rev = float(_col_any(loads[settled_mtd_mask & ent_mask], ["Customer Revenue", "Revenue"]).sum())
        s_cost = float(_col(loads[settled_mtd_mask & ent_mask], "Driver Rate").fillna(0).sum())
        settled_margin = s_rev - s_cost
        m_pct = ((t_rev - t_cost) / t_rev) if t_rev else None
        daily_run_rate = (t_rev / days) if days else 0.0
        proj_rev = booked + daily_run_rate * days_remaining
        proj_rev = proj_rev if proj_rev > 0 else None
        t90_margin = (proj_rev * m_pct) if (proj_rev and m_pct is not None) else None
        # Floor at actual settled — handles the end-of-month case (factor=1.0)
        # where t90 underestimates a hot-running month, and is also correct
        # mid-month since you can't project less than you've already booked.
        if t90_margin is not None and settled_margin > t90_margin:
            proj_margin = settled_margin
        else:
            proj_margin = t90_margin
        out[ent] = {
            "booked_mtd": booked or None,
            "settled_mtd_margin": settled_margin or None,
            "trailing_margin_pct": m_pct,
            "projected_revenue": proj_rev,
            "projected_margin": proj_margin,
        }
        combined_booked += booked
        combined_t_rev += t_rev
        combined_t_cost += t_cost
        combined_settled_margin += settled_margin

    c_pct = ((combined_t_rev - combined_t_cost) / combined_t_rev) if combined_t_rev else None
    c_daily_run_rate = (combined_t_rev / days) if days else 0.0
    c_proj_rev = combined_booked + c_daily_run_rate * days_remaining
    c_proj_rev = c_proj_rev if c_proj_rev > 0 else None
    _c_t90 = (c_proj_rev * c_pct) if (c_proj_rev and c_pct is not None) else None
    c_proj_margin = (_c_t90 if (_c_t90 is not None and combined_settled_margin <= _c_t90)
                     else (combined_settled_margin or _c_t90))
    out["combined"] = {
        "booked_mtd": combined_booked or None,
        "settled_mtd_margin": combined_settled_margin or None,
        "trailing_margin_pct": c_pct,
        "projected_revenue": c_proj_rev,
        "projected_margin": c_proj_margin,
    }
    out["rollover"] = rollover
    out["mtd_label"] = mtd_label
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
    overhead_per_mile_live = (overhead_total / ytd_miles) if (overhead_total and ytd_miles) else None
    overhead_per_mile_xtrux = (overhead_xtrux / ytd_miles) if (overhead_xtrux and ytd_miles) else None
    # Pin the office overhead/mi to a hand-set value while the costing algorithm
    # is being validated. RPM_GOAL_OVERHEAD_PIN=0 (empty env var) unpins it and
    # lets the live computed value flow through.
    overhead_pin = _env_float("RPM_GOAL_OVERHEAD_PIN", RPM_GOAL_OVERHEAD_PIN)
    overhead_per_mile = overhead_pin if overhead_pin else overhead_per_mile_live

    insurance_surcharge = _env_float("RPM_GOAL_INSURANCE_SURCHARGE", RPM_GOAL_INSURANCE_SURCHARGE)
    cost_per_mile = ((pay_per_mile + overhead_per_mile + insurance_surcharge)
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
        "overhead_per_mile_live": overhead_per_mile_live,
        "overhead_pin": overhead_pin or None,
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
        "insurance_surcharge": insurance_surcharge,
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
    # Past-due = everything not in Current. Tile shows this so the headline AR
    # number captures the full overdue book, not just 31+. Page 5's detailed
    # table still scopes to 31+ for actionable focus.
    past_due_total = 0.0
    for _, r in data.iterrows():
        if "current" in str(r.get("Section", "")).lower():
            continue
        a = pd.to_numeric(pd.Series([r.get(amt_col)]), errors="coerce").iloc[0]
        if _isnum(a):
            past_due_total += float(a)

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
            "total_past_due": past_due_total,
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


def compute_dso_history(dso_hist_sheets: dict | None,
                        companies: frozenset[str] | None = None,
                        ) -> tuple[list[str], list[float], float | None]:
    """Parse QB_DSO_History.xlsx into (labels, avg_days_per_month, overall_avg).

    Filters to `companies` when provided (same frozenset used for AR history).
    Returns ([], [], None) if data is unavailable.
    """
    if not dso_hist_sheets:
        return [], [], None
    df = next(iter(dso_hist_sheets.values()), None)
    if df is None or df.empty:
        return [], [], None
    if "AsOf" not in df.columns or "AvgDays" not in df.columns:
        return [], [], None
    if companies is not None and "Company" in df.columns:
        df = df[df["Company"].astype(str).str.strip().str.lower().isin(companies)]
    if df.empty:
        return [], [], None

    # Weighted avg per month (weighted by InvoiceCount when available).
    if "InvoiceCount" in df.columns:
        df = df.copy()
        df["_w"] = pd.to_numeric(df["InvoiceCount"], errors="coerce").fillna(1)
        df["_wd"] = pd.to_numeric(df["AvgDays"], errors="coerce").fillna(0) * df["_w"]
        g = df.groupby("AsOf").apply(lambda s: s["_wd"].sum() / s["_w"].sum() if s["_w"].sum() else None)
    else:
        g = df.groupby("AsOf")["AvgDays"].apply(
            lambda s: pd.to_numeric(s, errors="coerce").mean()
        )
    g = g.sort_index().dropna().tail(6)
    if g.empty:
        return [], [], None

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
        values.append(round(float(v), 1))

    overall = round(sum(values) / len(values), 1) if values else None
    return labels, values, overall


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


def _truck_label(v) -> str:
    """Strip the trailing '.0' pandas adds when a numeric truck number flows
    through the workbook as float. '45209.0' -> '45209'; non-numeric strings
    (e.g. 'TRK-007') pass through unchanged."""
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].lstrip("-").isdigit():
        return s[:-2]
    return s


def _normalize_id(v) -> str:
    """Normalize a Samsara id (vehicleId / driverId) to its canonical
    decimal-integer string. Handles pandas' float coercion of large ints:
    int -> '281474985134847', float -> '281474985134847.0' / '2.8e+14' →
    all converge to '281474985134847'. Non-numeric strings pass through."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return s
    if f != f:  # NaN check
        return ""
    if float(int(f)) == f:
        return str(int(f))
    return s


def compute_samsara(sheets: dict[str, pd.DataFrame] | None) -> dict | None:
    if not sheets:
        return None
    events = sheets.get("SafetyEvents")
    hosv = sheets.get("HOS_Violations")
    defects = sheets.get("DVIR_Defects")
    w = _windows()
    out: dict = {"windows": {}, "trend": {}, "detail": {}, "coaching": {"24h": 0, "7d": 0, "mtd": 0},
                 "fleet": {"mpg": [], "idle": [], "speeders": [], "scores_top": [],
                            "scores_bottom": [], "fleet_mpg": None, "fleet_score": None}}

    # Safety events
    if events is not None and not events.empty:
        ed = _dates(events, SAFETY_DATE)
        out["windows"]["events"] = _count_windows(ed)
        out["trend"]["events"] = _monthly_counts(ed)
        dcol = _find_col(events, ["driver name", "driver"])
        out["coaching"] = _coaching_by_window(events, dcol, ed)
        # Widened from 24h to 7d so the "Safety events — last 7d" table on
        # page 1 reads useful data instead of "None in this window."
        out["detail"]["events"] = _detail_rows(
            events[ed >= w["7d"]], ed[ed >= w["7d"]],
            [("driver name", "driver"), ("unit", "vehicle"), ("event type",),
             ("severity",), ("status", "reviewed", "coaching")],
        )
        # "Coaching needs assigned" list — per-driver aggregation over the
        # last 30 days. Drivers stay on the list until they sign their
        # coaching session, then carry over for 3 more days as a closeout
        # window before dropping off (visibility rule applied at render
        # time in _safety_detail_tables using out["coaching_acks"]).
        _7d = events[ed >= w["30d"]]
        _7d_dates = ed[ed >= w["30d"]]
        if not _7d.empty and dcol:
            et_col = _find_col(_7d, ["event type"])
            sev_col = _find_col(_7d, ["severity"])
            unit_col = _find_col(_7d, ["unit", "vehicle"])
            agg: dict = {}
            for idx in _7d.index:
                r = _7d.loc[idx]
                driver = str(r.get(dcol, "") or "").strip() or "(unknown)"
                if _is_excluded_driver(driver):
                    continue
                slot = agg.setdefault(driver, {
                    "driver": driver, "events": 0,
                    "types": set(), "severities": set(),
                    "units": set(), "last_ts": None,
                })
                slot["events"] += 1
                if et_col:
                    et = str(r.get(et_col, "") or "").strip()
                    if et:
                        slot["types"].add(et)
                if sev_col:
                    sv = str(r.get(sev_col, "") or "").strip()
                    if sv:
                        slot["severities"].add(sv)
                if unit_col:
                    u = str(r.get(unit_col, "") or "").strip()
                    if u:
                        slot["units"].add(u)
                ts = _7d_dates.loc[idx]
                if pd.notna(ts) and (slot["last_ts"] is None or ts > slot["last_ts"]):
                    slot["last_ts"] = ts
            out["coaching_list"] = [
                {
                    "driver": s["driver"], "events": s["events"],
                    "types": sorted(s["types"]),
                    "severities": sorted(s["severities"]),
                    "units": sorted(s["units"]),
                    "last": s["last_ts"].strftime("%Y-%m-%d %H:%M") if s["last_ts"] is not None else "",
                }
                for s in sorted(agg.values(), key=lambda x: -x["events"])
            ]

    # HOS violations
    if hosv is not None and not hosv.empty:
        hd = _dates(hosv, HOSV_DATE)
        out["windows"]["hos"] = _count_windows(hd)
        out["trend"]["hos"] = _monthly_counts(hd)
        # Widened from 24h to 7d so the "HOS violations — last 7d" table on
        # page 1 reads useful data instead of "None in this window."
        out["detail"]["hos"] = _detail_rows(
            hosv[hd >= w["7d"]], hd[hd >= w["7d"]],
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
            opd, opdd,
            [("unit",), ("driver",), ("defect",), ("defect type",), ("resolved",)],
        )

    # --- Fleet Operations metrics (page 4) -----------------------------------
    # Speeding-event leaderboard: filter the safety-events stream for Event
    # Type containing "speeding" and group by driver over the last 7 days.
    if events is not None and not events.empty:
        ed = _dates(events, SAFETY_DATE)
        et_col = _find_col(events, ["event type"])
        dcol = _find_col(events, ["driver name", "driver"])
        if et_col and dcol:
            recent = events[ed >= w["7d"]]
            spd_mask = recent[et_col].astype(str).str.lower().str.contains("speed", na=False)
            spd = recent[spd_mask]
            if not spd.empty:
                top = (spd[dcol].astype(str).str.strip()
                       .replace({"": "(unknown)", "nan": "(unknown)"})
                       .value_counts().head(5))
                out["fleet"]["speeders"] = [{"driver": k, "count": int(v)}
                                            for k, v in top.items()
                                            if not _is_excluded_driver(k)]

    # MPG per truck: pull all IFTA_YYYY_MM sheets (most recent month wins per
    # vehicle when duplicated). Compute MPG = miles / gallons.
    #
    # Samsara's IFTA vehicle report carries `vehicleId` (internal numeric id)
    # but the human-readable truck number ("45209") lives on the Vehicles
    # sheet. Build an id -> name map so the MPG list can be keyed by truck
    # number — that's what every other table on the page joins by.
    def _exact_or_find(df, exact: str, fallback_needles: list[str]) -> str | None:
        """Prefer a column whose name is exactly `exact` (case-insensitive);
        fall back to a substring search. Avoids `_find_col(['id'])` grabbing
        'externalIds' before the actual 'id' column."""
        if df is None:
            return None
        target = exact.lower()
        for c in df.columns:
            if str(c).lower() == target:
                return c
        return _find_col(df, fallback_needles)

    vehicles_df = sheets.get("Vehicles")
    id_to_truck: dict[str, str] = {}
    if vehicles_df is not None and not vehicles_df.empty:
        v_id = _exact_or_find(vehicles_df, "id", ["vehicleid", "vehicle.id"])
        v_nm = _exact_or_find(vehicles_df, "name", ["vehiclename", "vehicle.name"])
        if v_id and v_nm:
            for _, r in vehicles_df.iterrows():
                vid = _normalize_id(r.get(v_id))
                vnm = str(r.get(v_nm) or "").strip()
                if vid and vnm:
                    id_to_truck[vid] = _truck_label(vnm)
        log.info("Vehicles id->truck map: %d entries (id col=%s, name col=%s, sample=%s)",
                 len(id_to_truck), v_id, v_nm, list(id_to_truck.items())[:2])

    # MPG source preference:
    #   1. Aggregate Trips data (per-trip fuelConsumed* + distance straight
    #      from OBD — works for any Samsara fleet, no IFTA dependency).
    #   2. FuelEnergy sheet (legacy, currently empty because the endpoint we
    #      hit returns 404 — kept for forward-compat if Samsara adds one).
    #   3. IFTA sheet (last fallback).
    mpg_built = False
    trips_df_for_mpg = sheets.get("Trips")
    if trips_df_for_mpg is not None and not trips_df_for_mpg.empty:
        t_veh = (_find_col(trips_df_for_mpg, ["vehiclename", "vehicle.name", "vehicle name"])
                 or _find_col(trips_df_for_mpg, ["vehicleid", "vehicle.id"]))
        t_dist = _find_col(trips_df_for_mpg, ["distancemiles", "distance.miles", "distancemeters", "distance.meters"])
        t_fuel = (_find_col(trips_df_for_mpg, ["fuelconsumedml", "fuel.consumed.ml", "fuelusedml", "fuel.consumed", "fuelused"])
                  or _find_col(trips_df_for_mpg, ["fuelconsumed", "fuel"]))
        # Date column for MTD filtering. v1 /fleet/trips returns `endMs`
        # (Unix millis); v2 returns `endTime` (ISO). Probe for both forms so
        # the MTD filter doesn't silently no-op when only the v1 shape is
        # present — that was inflating fleet_miles by summing the full
        # SAMSARA_DAYS_BACK window (90d) instead of just MTD.
        t_end = _find_col(trips_df_for_mpg, ["endtime", "end time", "endms"])
        t_start = _find_col(trips_df_for_mpg, ["starttime", "start time", "startms"])
        t_date = t_end or t_start
        log.info("Trips MPG probe: veh=%s dist=%s fuel=%s date=%s", t_veh, t_dist, t_fuel, t_date)
        if t_veh and t_dist and t_fuel:
            cols = [t_veh, t_dist, t_fuel] + ([t_date] if t_date else [])
            td = trips_df_for_mpg[cols].copy()
            # Filter to MTD so the tile labels (Fleet MPG · MTD, Best MPG MTD)
            # actually match the aggregation window.
            if t_date:
                # v1 `endMs` / `startMs` are integer Unix milliseconds; pandas
                # parses those when passed unit='ms'. ISO `endTime` parses fine
                # without the hint. Detect by column-name suffix.
                if str(t_date).lower().endswith("ms"):
                    td["_end"] = pd.to_datetime(td[t_date], errors="coerce",
                                                 utc=True, unit="ms")
                else:
                    td["_end"] = pd.to_datetime(td[t_date], errors="coerce", utc=True)
                mtd_start = pd.Timestamp.now(tz="UTC").normalize().replace(day=1)
                before = len(td)
                td = td[td["_end"] >= mtd_start]
                log.info("Trips MPG: filtered to MTD (%s+) -> %d / %d rows",
                         mtd_start.date(), len(td), before)
            else:
                log.warning("Trips MPG: NO date column matched — MTD filter SKIPPED. "
                            "Columns sampled: %s. Fleet miles will reflect the full "
                            "SAMSARA_DAYS_BACK window, not MTD.",
                            list(trips_df_for_mpg.columns)[:20])
            td["_dist"] = pd.to_numeric(td[t_dist], errors="coerce").fillna(0)
            td["_fuel"] = pd.to_numeric(td[t_fuel], errors="coerce").fillna(0)
            # Convert distance/fuel based on column-name unit hints.
            if "meter" in str(t_dist).lower():
                td["_miles"] = td["_dist"] / 1609.344
            else:
                td["_miles"] = td["_dist"]
            fn = str(t_fuel).lower()
            if "ml" in fn or "milliliter" in fn:
                td["_gallons"] = td["_fuel"] / 3785.411784
            elif "liter" in fn:
                td["_gallons"] = td["_fuel"] / 3.785411784
            else:
                td["_gallons"] = td["_fuel"]
            agg = td.groupby(t_veh, dropna=True).agg(_miles=("_miles", "sum"),
                                                     _gallons=("_gallons", "sum")).reset_index()
            agg = agg[(agg["_miles"] > 0) & (agg["_gallons"] > 0)]
            if not agg.empty:
                def _unit_label_trips(raw):
                    s = _normalize_id(raw)
                    if s in id_to_truck:
                        return id_to_truck[s]
                    return _truck_label(str(raw).strip())
                # Apply the excluded-truck filter BEFORE rolling up the headline
                # fleet totals so non-X-Trux units (JW Logistics, brokerage assets,
                # rentals, etc) don't bloat the page-8 "Fleet miles · MTD" tile.
                agg["_label"] = agg[t_veh].map(_unit_label_trips)
                _kept = agg["_label"].map(lambda lbl: not _is_excluded_truck(lbl))
                if _kept.sum() < len(agg):
                    log.info("Trips MPG: excluded %d of %d trucks from fleet totals "
                             "(JW Logistics / brokerage / rentals)",
                             len(agg) - int(_kept.sum()), len(agg))
                agg = agg[_kept].reset_index(drop=True)
            if not agg.empty:
                agg["_mpg"] = agg["_miles"] / agg["_gallons"]
                fleet_mpg = agg["_miles"].sum() / agg["_gallons"].sum()
                out["fleet"]["fleet_mpg"] = float(fleet_mpg)
                out["fleet"]["fleet_miles"] = float(agg["_miles"].sum())
                out["fleet"]["fleet_gallons"] = float(agg["_gallons"].sum())
                agg = agg.sort_values("_mpg", ascending=False).reset_index(drop=True)
                out["fleet"]["mpg"] = [
                    {"unit": r["_label"], "mpg": round(r["_mpg"], 2),
                     "miles": int(r["_miles"]), "gallons": round(r["_gallons"], 1),
                     "driver": ""}  # filled below after id_to_truck + recent map are built
                    for _, r in agg.iterrows()
                ]
                log.info("MPG source: Trips (%d trucks)", len(out["fleet"]["mpg"]))
                mpg_built = True
            else:
                log.warning("Trips MPG: aggregated table empty after positive-only filter")
        else:
            # Useful for diagnosis the next time the schema changes.
            log.warning("Trips MPG: required columns not all present — "
                        "columns sampled: %s", list(trips_df_for_mpg.columns)[:20])

    ifta = None
    if not mpg_built:
        fuel_energy = sheets.get("FuelEnergy")
        if fuel_energy is not None and not fuel_energy.empty:
            ifta = fuel_energy
            log.info("MPG source: FuelEnergy sheet (%d rows)", len(fuel_energy))
        else:
            ifta_keys = sorted([k for k in sheets if k.startswith("IFTA_")], reverse=True)
            if ifta_keys:
                ifta = sheets[ifta_keys[0]]
                log.info("MPG source: IFTA fallback (%s)", ifta_keys[0])
    if not mpg_built and ifta is not None and not ifta.empty:
        # Look for name FIRST (so "vehicleName" / "vehicle.name" beats the
        # broader "vehicle" substring that would otherwise grab vehicleId).
        v_col = (_find_col(ifta, ["vehiclename", "vehicle.name", "vehicle_name", "vehicle name", "unitname", "unit name"])
                 or _find_col(ifta, ["vehicleid", "vehicle.id", "vehicle"])
                 or _find_col(ifta, ["unit"]))
        # FuelEnergy uses meters; IFTA uses miles. Detect from column name.
        mi_col = _find_col(ifta, ["distancemiles", "miles", "distance"])
        ga_col = _find_col(ifta, ["gallons", "fuel"])
        if v_col and mi_col and ga_col:
            df = ifta.copy()
            raw_miles = pd.to_numeric(df[mi_col], errors="coerce").fillna(0)
            # Heuristic: if the column name signals meters, convert to miles
            # (1 mile = 1609.344 m). FuelEnergy returns totalDistanceMeters.
            if "meter" in str(mi_col).lower():
                df["_miles"] = raw_miles / 1609.344
            else:
                df["_miles"] = raw_miles
            raw_gallons = pd.to_numeric(df[ga_col], errors="coerce").fillna(0)
            # Heuristic: if column name signals liters or milliliters, convert.
            cn = str(ga_col).lower()
            if "milliliter" in cn or "ml" == cn[-2:] or "mlused" in cn:
                df["_gallons"] = raw_gallons / 3785.411784
            elif "liter" in cn:
                df["_gallons"] = raw_gallons / 3.785411784
            else:
                df["_gallons"] = raw_gallons
            df = df[(df["_miles"] > 0) & (df["_gallons"] > 0)]
            if not df.empty:
                # Resolve the value in v_col to a truck number — if the
                # column held vehicleId we go through id_to_truck; if it
                # already held the truck name we pass through.
                def _unit_label(raw):
                    s = _normalize_id(raw)
                    if s in id_to_truck:
                        return id_to_truck[s]
                    return _truck_label(str(raw).strip())
                # Drop excluded trucks BEFORE the headline rollup so the
                # Fleet miles · MTD tile reflects X-Trux only (mirror of the
                # Trips path above).
                df["_label"] = df[v_col].map(_unit_label)
                _kept = df["_label"].map(lambda lbl: not _is_excluded_truck(lbl))
                if _kept.sum() < len(df):
                    log.info("IFTA MPG: excluded %d of %d trucks from fleet totals",
                             len(df) - int(_kept.sum()), len(df))
                df = df[_kept].reset_index(drop=True)
            if not df.empty:
                df["_mpg"] = df["_miles"] / df["_gallons"]
                fleet_mpg = (df["_miles"].sum() / df["_gallons"].sum()) if df["_gallons"].sum() else None
                out["fleet"]["fleet_mpg"] = float(fleet_mpg) if fleet_mpg else None
                out["fleet"]["fleet_miles"] = float(df["_miles"].sum())
                out["fleet"]["fleet_gallons"] = float(df["_gallons"].sum())
                df = df.sort_values("_mpg", ascending=False).reset_index(drop=True)
                out["fleet"]["mpg"] = [
                    {"unit": r["_label"], "mpg": round(r["_mpg"], 2),
                     "miles": int(r["_miles"]), "gallons": round(r["_gallons"], 1),
                     "driver": ""}
                    for _, r in df.iterrows()
                ]

    # Idle hours per truck (top 5 idlers) from EngineIdle sheet.
    idle = sheets.get("EngineIdle")
    if idle is not None and not idle.empty and "Idle Hours" in idle.columns:
        wk_keys = ["W1", "W2", "W3", "W4", "Cur"]
        complete_keys = wk_keys[:-1]   # exclude current partial week
        def _idle_driver(name) -> str:
            if not name or str(name).lower() == "nan":
                return ""
            return "" if _is_excluded_driver(name) else str(name).strip()
        # Fallback driver lookup for trucks Samsara has no static assignment
        # for: take the most recent driver-of-record from the Trips sheet.
        # Keyed by truck label so it matches EngineIdle's Vehicle Name.
        trips_df = sheets.get("Trips")
        recent_driver_by_truck: dict[str, str] = {}
        if trips_df is not None and not trips_df.empty:
            # Trips carries vehicleId, not a name field — resolve through
            # id_to_truck after the lookup. Same fallback chain as MPG.
            t_vname = (_find_col(trips_df, ["vehiclename", "vehicle.name", "vehicle name"])
                       or _find_col(trips_df, ["vehicleid", "vehicle.id"]))
            t_dname = (_find_col(trips_df, ["drivername", "driver.name", "driver name"])
                       or _find_col(trips_df, ["driverid", "driver.id"]))
            t_end = _find_col(trips_df, ["endtime", "end time", "endts", "endms"])
            log.info("Trips driver-fallback probe: veh=%s drv=%s end=%s",
                     t_vname, t_dname, t_end)
            if t_vname and t_dname and t_end:
                # If the driver column is an id (not a name), build an id->name
                # map from the Drivers sheet.
                drivers_df = sheets.get("Drivers")
                drv_id_to_name: dict[str, str] = {}
                if "id" in str(t_dname).lower() and drivers_df is not None and not drivers_df.empty:
                    d_id = _exact_or_find(drivers_df, "id", ["driverid", "driver.id"])
                    d_nm = _exact_or_find(drivers_df, "name", ["drivername", "driver.name"])
                    if d_id and d_nm:
                        for _, dr in drivers_df.iterrows():
                            did = _normalize_id(dr.get(d_id))
                            dnm = str(dr.get(d_nm) or "").strip()
                            if did and dnm:
                                drv_id_to_name[did] = dnm
                log.info("Drivers id->name map: %d entries", len(drv_id_to_name))
                td = trips_df[[t_vname, t_dname, t_end]].copy()
                td["_end"] = pd.to_datetime(td[t_end], errors="coerce", utc=True)
                td = td.dropna(subset=["_end"]).sort_values("_end", ascending=False)
                using_driver_id = "id" in str(t_dname).lower()
                for _, r in td.iterrows():
                    raw_v = _normalize_id(r[t_vname])
                    vn = id_to_truck.get(raw_v) or _truck_label(str(r[t_vname]).strip())
                    raw_d = _normalize_id(r[t_dname])
                    # If we're looking up by driver id, ONLY accept rows we
                    # could resolve to a real name. Raw '0' / unknown ids
                    # represent unassigned trips and shouldn't surface in
                    # the table as the literal text "0".
                    if using_driver_id:
                        dn = drv_id_to_name.get(raw_d)
                    else:
                        dn = str(r[t_dname]).strip()
                    if not vn or not dn or dn.lower() in ("nan", "0", ""):
                        continue
                    if vn in recent_driver_by_truck:
                        continue
                    if _is_excluded_driver(dn):
                        continue
                    recent_driver_by_truck[vn] = dn
                log.info("Trips driver-fallback resolved: %d trucks",
                         len(recent_driver_by_truck))
        # Build a truck -> MPG map from the IFTA-driven mpg list compiled
        # above. Normalize both keys with _truck_label so '45209.0' (idle
        # source) matches '45209' (IFTA source).
        mpg_by_unit: dict[str, float] = {}
        for m in out["fleet"].get("mpg", []) or []:
            k = _truck_label(m.get("unit") or "")
            if k and _isnum(m.get("mpg")):
                mpg_by_unit[k] = float(m["mpg"])
        log.info("MPG join: mpg_by_unit keys sample=%s",
                 list(mpg_by_unit.keys())[:6])
        # All vehicles, ranked worst-to-best by **Avg / wk over the 4 complete
        # settlement weeks** (current partial week excluded). Largest idle
        # average = worst, so descending sort.
        rows = []
        for _, r in idle.iterrows():
            weeks_idle = [float(r.get(f"Idle_{k}") or 0) for k in wk_keys]
            weeks_engine = [float(r.get(f"Engine_{k}") or 0) for k in wk_keys]
            avg_wk = sum(weeks_idle[:-1]) / max(1, len(complete_keys))
            unit = _truck_label(r.get("Vehicle Name") or r.get("Vehicle ID") or "")
            primary_driver = _idle_driver(r.get("Driver Name"))
            driver_name = primary_driver or recent_driver_by_truck.get(unit, "")
            rows.append({
                "unit": unit,
                "driver": driver_name,
                "idle_hours": float(r.get("Idle Hours") or 0),
                "engine_hours": float(r.get("Engine Hours") or 0),
                "idle_pct": (float(r.get("Idle Hours") or 0) / float(r.get("Engine Hours") or 1)
                             if r.get("Engine Hours") else 0),
                "weeks_idle": weeks_idle,
                "weeks_engine": weeks_engine,
                "avg_wk": avg_wk,
                "mpg": mpg_by_unit.get(unit),
                "idle_gallons": float(r.get("Idle Gallons") or 0)
                                if _isnum(r.get("Idle Gallons")) else None,
            })
        rows.sort(key=lambda x: x["avg_wk"], reverse=True)
        rows = [r for r in rows if not _is_excluded_truck(r["unit"])]
        log.info("MPG join: idle row units sample=%s",
                 [r["unit"] for r in rows[:6]])
        out["fleet"]["idle"] = rows
        out["fleet"]["fleet_idle_hours"] = float(idle["Idle Hours"].sum())
        # Backfill driver name onto MPG rows. Source the FULL Trips-based
        # driver map (covers trucks with trips but no engine state history,
        # like 43193) — falling back to the idle rows' static-assignment
        # driver if the truck isn't in the Trips map.
        static_driver_by_truck = {r["unit"]: r.get("driver", "")
                                  for r in rows if r.get("driver")}
        for m in out["fleet"].get("mpg", []) or []:
            if m.get("driver"):
                continue
            unit = m.get("unit")
            m["driver"] = (recent_driver_by_truck.get(unit)
                           or static_driver_by_truck.get(unit, ""))
        # Settlement-week date-range labels (reuse the same helpers Driver
        # Mileage uses so both pages match).
        try:
            starts = _settlement_starts(pd.Timestamp.now(tz=CHI_TZ), n=SETTLEMENT_WEEKS)
            out["fleet"]["idle_labels"] = [_wk_label(s) for s in starts]
        except Exception:
            out["fleet"]["idle_labels"] = ["W1", "W2", "W3", "W4", "Current"]

    # Driver safety scores — top 5 and bottom 5 from DriverSafetyScores sheet.
    scores = sheets.get("DriverSafetyScores")
    if scores is None or scores.empty:
        log.info("DriverSafetyScores: empty")
    else:
        log.info("DriverSafetyScores: %d rows, ALL cols=%s",
                 len(scores), list(scores.columns))
    if scores is not None and not scores.empty:
        sc_col = _find_col(scores, ["safetyscore", "score", "totalnumberofpoints"])
        nm_col = _find_col(scores, ["driver name", "name"]) or "driverId"
        log.info("DriverSafetyScores: sc_col=%s nm_col=%s", sc_col, nm_col)
        if sc_col:
            df = scores.copy()
            df["_score"] = pd.to_numeric(df[sc_col], errors="coerce")
            df = df.dropna(subset=["_score"])
            log.info("DriverSafetyScores: %d rows with numeric score", len(df))
            # Drop placeholder / test driver records before computing the
            # fleet average or building any ranking.
            df = df[~df[nm_col].apply(_is_excluded_driver)] if nm_col in df.columns else df
            log.info("DriverSafetyScores: %d rows after exclusion filter", len(df))
            if not df.empty:
                out["fleet"]["fleet_score"] = float(df["_score"].mean())
                # Detect the component-event columns Samsara returns alongside
                # the composite safetyScore. Names vary slightly by API
                # version, so search for each.
                accel_col = _find_col(df, ["harshacceleration", "harsh_acceleration", "harshaccel"])
                brake_col = _find_col(df, ["harshbraking", "harsh_braking", "harshbrake"])
                turn_col = _find_col(df, ["harshturning", "harsh_turning", "harshturn"])
                # Speeding: Samsara returns time-over-limit in ms. Names have
                # drifted across API versions (speedingMilliseconds,
                # timeOverSpeedLimitMs, speedingTimeMs, speedingDurationMs),
                # so try a broad set of needles. Count field is the last
                # fallback if only an event count is exposed.
                speed_ms_col = _find_col(df, [
                    "speedingmilliseconds", "speeding_milliseconds",
                    "speedingms", "speedingmillis", "speedingmsec",
                    "speedingtimems", "speedingtimemilliseconds",
                    "speedingdurationms", "speedingduration",
                    "timeoverspeedlimit", "overspeedlimitms",
                ])
                speed_cnt_col = _find_col(df, ["speedingcount", "speeding_count", "speedingevents"])
                # Total drive time so we can express speeding as a % of time
                # behind the wheel (the chart Samsara itself shows). Try ms
                # first, fall back to seconds.
                drive_ms_col = _find_col(df, [
                    "totaltimedriven",          # totalTimeDrivenMs (Samsara v2)
                    "totaldrivingms",           # totalDrivingMs
                    "totaldriving",             # totalDrivingSeconds / Ms
                    "activedriving",            # activeDrivingMs
                    "totaltimems", "totaltimemilliseconds",
                    "totaldrivetimems", "totaldrivetimemilliseconds",
                    "drivingtimems", "drivetimems",
                    "totalengineonms", "totalonms",
                ])
                drive_s_col = _find_col(df, [
                    "totaltimeseconds", "totaldrivetimeseconds",
                    "drivingtimeseconds", "drivetimeseconds",
                ])
                crash_col = _find_col(df, ["crashcount", "crash_count", "crash"])
                miles_col = _find_col(df, ["totaldistancedrivenmiles", "distancedrivenmiles",
                                           "totaldistancedrivenmeters", "totalmiles"])
                log.info("DriverSafetyScores cols detected: accel=%s brake=%s turn=%s "
                         "speed_ms=%s speed_cnt=%s drive_ms=%s drive_s=%s crash=%s miles=%s",
                         accel_col, brake_col, turn_col, speed_ms_col, speed_cnt_col,
                         drive_ms_col, drive_s_col, crash_col, miles_col)
                def _i(r, col):
                    if not col:
                        return None
                    v = pd.to_numeric(pd.Series([r.get(col)]), errors="coerce").iloc[0]
                    return int(v) if _isnum(v) else None
                def _f(r, col):
                    if not col:
                        return None
                    v = pd.to_numeric(pd.Series([r.get(col)]), errors="coerce").iloc[0]
                    return float(v) if _isnum(v) else None
                def _speed_min(r):
                    if speed_ms_col:
                        v = _f(r, speed_ms_col)
                        return max(0, int(round(v / 60_000))) if _isnum(v) else None
                    return _i(r, speed_cnt_col)
                def _drive_ms(r):
                    if drive_ms_col:
                        return _f(r, drive_ms_col)
                    if drive_s_col:
                        v = _f(r, drive_s_col)
                        return v * 1000 if _isnum(v) else None
                    return None
                def _speed_pct(r):
                    sp_ms = _f(r, speed_ms_col) if speed_ms_col else None
                    dt_ms = _drive_ms(r)
                    if _isnum(sp_ms) and _isnum(dt_ms) and dt_ms > 0:
                        return round(sp_ms / dt_ms * 100, 1)
                    return None

                ranked = df.sort_values("_score", ascending=True)
                def _row(r):
                    return {
                        "driver": str(r.get(nm_col) or r.get("driverId") or ""),
                        "score": int(round(r["_score"])),
                        "harsh_accel": _i(r, accel_col),
                        "harsh_brake": _i(r, brake_col),
                        "harsh_turn": _i(r, turn_col),
                        "speed_min": _speed_min(r),
                        "speed_pct": _speed_pct(r),
                        "crashes": _i(r, crash_col),
                        "miles": _i(r, miles_col),
                    }
                out["fleet"]["scores_all"] = [_row(r) for _, r in ranked.iterrows()]
                out["fleet"]["scores_top"] = list(reversed(out["fleet"]["scores_all"][-5:]))
                out["fleet"]["scores_bottom"] = out["fleet"]["scores_all"][:5]

                # Additional windows of the Samsara safety-score sheet so the
                # brief can show 6-month / 3-month / MTD speeding % side by side.
                # Same per-driver formula; just a different source sheet.
                def _pct_by_name(sheet_df: pd.DataFrame, label: str) -> dict:
                    if sheet_df is None or sheet_df.empty:
                        return {}
                    _sp_ms = _find_col(sheet_df, [
                        "speedingmilliseconds", "speeding_milliseconds",
                        "speedingms", "speedingmillis", "speedingmsec",
                        "speedingtimems", "speedingtimemilliseconds",
                        "speedingdurationms", "speedingduration",
                        "timeoverspeedlimit", "overspeedlimitms",
                    ])
                    _dr_ms = _find_col(sheet_df, [
                        "totaltimedriven",          # totalTimeDrivenMs (Samsara v2)
                        "totaldrivingms",           # totalDrivingMs
                        "totaldriving",             # totalDrivingSeconds / Ms
                        "activedriving",            # activeDrivingMs
                        "totaltimems", "totaltimemilliseconds",
                        "totaldrivetimems", "totaldrivetimemilliseconds",
                        "drivingtimems", "drivetimems",
                        "totalengineonms", "totalonms",
                    ])
                    _dr_s = _find_col(sheet_df, [
                        "totaltimeseconds", "totaldrivetimeseconds",
                        "drivingtimeseconds", "drivetimeseconds",
                    ])
                    log.info("%s cols: speed_ms=%s drive_ms=%s drive_s=%s",
                             label, _sp_ms, _dr_ms, _dr_s)
                    pid: dict = {}
                    if "driverId" in sheet_df.columns and _sp_ms:
                        for _, mr in sheet_df.iterrows():
                            did = str(mr.get("driverId") or "")
                            if not did:
                                continue
                            sp = pd.to_numeric(pd.Series([mr.get(_sp_ms)]), errors="coerce").iloc[0]
                            dt = None
                            if _dr_ms:
                                dt = pd.to_numeric(pd.Series([mr.get(_dr_ms)]), errors="coerce").iloc[0]
                            elif _dr_s:
                                dt_s = pd.to_numeric(pd.Series([mr.get(_dr_s)]), errors="coerce").iloc[0]
                                dt = dt_s * 1000 if _isnum(dt_s) else None
                            if _isnum(sp) and _isnum(dt) and dt > 0:
                                pid[did] = round(sp / dt * 100, 1)
                    by_nm: dict = {}
                    if "Driver Name" in sheet_df.columns:
                        for _, mr in sheet_df.iterrows():
                            did = str(mr.get("driverId") or "")
                            nm = str(mr.get("Driver Name") or "")
                            if nm and did in pid:
                                by_nm[nm.strip().lower()] = pid[did]
                    return by_nm

                pct_mtd = _pct_by_name(sheets.get("DriverSafetyScoresMtd"), "DriverSafetyScoresMtd")
                pct_3mo = _pct_by_name(sheets.get("DriverSafetyScores3mo"), "DriverSafetyScores3mo")
                for r in out["fleet"]["scores_all"]:
                    nm = (r.get("driver") or "").strip().lower()
                    if nm in pct_mtd:
                        r["speed_pct_mtd"] = pct_mtd[nm]
                    if nm in pct_3mo:
                        r["speed_pct_3mo"] = pct_3mo[nm]

    # --- Coaching sessions ---------------------------------------------------
    coaching_sheet = sheets.get("CoachingSessions")
    out["coaching_sessions"] = {"self_past_due": [], "manager_past_due": [], "available": False}
    # coaching_acks: normalized driver name -> sorted list of UTC datetimes when
    # the driver signed/acknowledged a coaching session (Status == "completed"
    # in Samsara, which only flips after the driver signs off). Used to render
    # the "Ack" check in the page-1 safety-events + coaching-needs tables.
    out["coaching_acks"] = {}
    if coaching_sheet is not None and not coaching_sheet.empty:
        out["coaching_sessions"]["available"] = True
        today_d = _dt.date.today()
        for _, row in coaching_sheet.iterrows():
            status = str(row.get("Status") or "").strip().lower()
            # Build the per-driver acknowledgment timeline first — any session
            # marked "completed" with a Completed At timestamp counts.
            if status == "completed":
                drv = str(row.get("Driver Name") or "").strip().lower()
                comp_raw = str(row.get("Completed At") or "").strip()
                if drv and comp_raw:
                    try:
                        comp_ts = pd.to_datetime(comp_raw, utc=True)
                        if pd.notna(comp_ts):
                            out["coaching_acks"].setdefault(drv, []).append(comp_ts)
                    except Exception:
                        pass
            if status not in ("pending", "not started", "notstarted", "assigned"):
                continue
            due_raw = str(row.get("Due At") or "").strip()
            if not due_raw:
                continue
            try:
                due_d = pd.to_datetime(due_raw, utc=True).date()
            except Exception:
                continue
            if due_d >= today_d:
                continue  # not yet past due
            days_overdue = (today_d - due_d).days
            rec = {
                "driver":       str(row.get("Driver Name") or ""),
                "assigned_at":  str(row.get("Assigned At") or ""),
                "due_at":       due_d.strftime("%b %d"),
                "days_overdue": days_overdue,
                "behaviors":    str(row.get("Behaviors") or ""),
            }
            kind = str(row.get("Type") or "").strip().lower()
            if "manager" in kind:
                out["coaching_sessions"]["manager_past_due"].append(rec)
            else:
                out["coaching_sessions"]["self_past_due"].append(rec)
        for drv in out["coaching_acks"]:
            out["coaching_acks"][drv].sort()

    # --- Training assignments ------------------------------------------------
    training_sheet = sheets.get("TrainingAssignments")
    out["training"] = {"past_due": [], "available": False}
    if training_sheet is not None and not training_sheet.empty:
        out["training"]["available"] = True
        today_d = _dt.date.today()
        incomplete = {"notstarted", "not started", "inprogress", "in progress",
                      "not_started", "in_progress", "assigned", "pending"}
        for _, row in training_sheet.iterrows():
            status = str(row.get("Status") or "").strip().lower().replace(" ", "")
            if status not in incomplete:
                continue
            due_raw = str(row.get("Due At") or "").strip()
            if not due_raw:
                continue
            try:
                due_d = pd.to_datetime(due_raw, utc=True).date()
            except Exception:
                continue
            if due_d >= today_d:
                continue
            days_overdue = (today_d - due_d).days
            out["training"]["past_due"].append({
                "driver":       str(row.get("Driver Name") or ""),
                "course":       str(row.get("Course") or ""),
                "assigned_at":  str(row.get("Assigned At") or ""),
                "due_at":       due_d.strftime("%b %d"),
                "days_overdue": days_overdue,
            })

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
        ts = d.loc[idx]
        rec = {
            "time": ts.strftime("%H:%M") if pd.notna(ts) else "",
            "date": ts.strftime("%Y-%m-%d") if pd.notna(ts) else "",
        }
        for key, col in cols.items():
            v = r.get(col, "") if col else ""
            # NaN/None/empty surfaces as em-dash so missing data is obvious.
            if pd.isna(v) or str(v).strip().lower() in ("", "nan", "none"):
                rec[key] = "&mdash;"
            else:
                rec[key] = str(v)
        rows.append(rec)
    return rows[:25]


# ----------------------------------------------------------------------
# Driver mileage by settlement week (Page 4)
# ----------------------------------------------------------------------
# Settlement week runs Wed 3:00 PM -> following Wed 2:59 PM, America/Chicago.
CHI_TZ = "America/Chicago"
SETTLEMENT_WEEKS = 5   # 4 complete prior weeks + current partial week
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
    # Average distinct drivers running per week — averaged over the complete
    # prior weeks only (the current partial week would drag it low).
    drivers_per_week = [sum(1 for r in rows if r["weeks"][k] > 0) for k in range(SETTLEMENT_WEEKS)]
    complete_weeks = SETTLEMENT_WEEKS - 1
    avg_drivers_per_week = (sum(drivers_per_week[:complete_weeks]) / complete_weeks) if complete_weeks else None
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


def compute_csa_scorecard(sheets) -> dict | None:
    """Extract FMCSA CSA carrier scorecard from the 'CSA Scorecard' tab of
    SambaSafety_Master.xlsx. Returns None if the tab is absent."""
    if not sheets:
        return None
    csa_df = None
    for name, df in sheets.items():
        if df is None or df.empty:
            continue
        if "csa" in str(name).lower():
            csa_df = df
            break
    if csa_df is None or csa_df.empty:
        return None

    cat_c = _find_col(csa_df, ["category", "basic category", "basic"])
    pct_c = _find_col(csa_df, ["percentile", "csa percentile", "rank", "percentile rank"])
    measure_c = _find_col(csa_df, ["basicmeasure", "basic measure", "measure"])
    seg_c = _find_col(csa_df, ["segmentviolations", "segment violations", "violations"])
    insp_c = _find_col(csa_df, ["relevantinspections", "relevant inspections", "inspections"])
    snap_c = _find_col(csa_df, ["snapshotdate", "snapshot date", "snapshot"])
    dot_c = _find_col(csa_df, ["dotnumber", "dot number", "dot"])
    apu_c = _find_col(csa_df, ["avgpowerunits", "avg power units", "power units"])

    if not cat_c:
        return None

    basics = []
    for _, r in csa_df.iterrows():
        cat = str(r[cat_c]).strip() if cat_c else ""
        if not cat or cat.lower() in ("nan", "category"):
            continue
        pct = pd.to_numeric(r[pct_c], errors="coerce") if pct_c else float("nan")
        measure = pd.to_numeric(r[measure_c], errors="coerce") if measure_c else float("nan")
        seg = pd.to_numeric(r[seg_c], errors="coerce") if seg_c else float("nan")
        insp = pd.to_numeric(r[insp_c], errors="coerce") if insp_c else float("nan")
        cat_lower = cat.lower().rstrip("*")
        threshold = next((v for k, v in _CSA_INTERVENTION.items() if k in cat_lower), 80)
        basics.append({
            "category": cat,
            "percentile": float(pct) if pd.notna(pct) else None,
            "measure": float(measure) if pd.notna(measure) else None,
            "seg_violations": int(seg) if pd.notna(seg) else None,
            "rel_inspections": int(insp) if pd.notna(insp) else None,
            "threshold": threshold,
            "intervention": pd.notna(pct) and float(pct) >= threshold,
        })

    if not basics:
        return None

    # Metadata from first row
    first = csa_df.iloc[0]
    snapshot_date = str(first[snap_c]).strip() if snap_c and pd.notna(first[snap_c]) else ""
    dot_number = str(first[dot_c]).strip() if dot_c and pd.notna(first[dot_c]) else ""
    avg_pu = str(first[apu_c]).strip() if apu_c and pd.notna(first[apu_c]) else ""

    n_alert = sum(1 for b in basics if b["intervention"])
    worst = max(basics, key=lambda b: (b["percentile"] or 0))
    return {
        "basics": basics,
        "n_alert": n_alert,
        "worst": worst,
        "snapshot_date": snapshot_date,
        "dot_number": dot_number,
        "avg_power_units": avg_pu,
    }


# DOT medical card / CDL deadlines tracked from the Alvys Drivers sheet —
# parallel to LICENSE_EXPIRY_WARN_DAYS but for the Alvys-side feed. The
# 14-day "critical" cutoff is what triggers the per-driver name-out in
# the BOTTOM LINE (vs the 30-day pipeline that stays in the aggregate
# count).
MEDICAL_EXPIRY_WARN_DAYS = 30
DRIVER_EXPIRY_CRITICAL_DAYS = 14


def compute_alvys_drivers(sheets, now: pd.Timestamp | None = None) -> dict | None:
    """Read the `Drivers` sheet from Alvys Pipeline.xlsx and return the
    CDL + DOT-medical compliance shape the scorecard surfaces.

    Returns a dict with:
      monitored                  active driver count
      drivers                    [{name, type, status, license_exp,
                                   license_days, medical_exp,
                                   medical_days, ...}]
      license_issues_30          drivers w/ CDL expiring within 30d (sorted soonest first)
      license_critical_14        drivers w/ CDL expiring within 14d (subset)
      medical_issues_30          drivers w/ medical card expiring within 30d
      medical_critical_14        drivers w/ medical card expiring within 14d
      window_days_critical       14 (so the renderer can label the urgency window)
    """
    if not sheets:
        return None
    df = sheets.get("Drivers")
    if df is None or df.empty:
        return None
    now = now or pd.Timestamp.now()

    def _col(*candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    name_c = _col("Name", "Driver Name")
    type_c = _col("Type", "DriverType")
    status_c = _col("Status")
    lic_exp_c = _col("LicenseExpiresAt", "License Expiration", "CDL Expiration")
    med_exp_c = _col("MedicalExpiresAt", "Medical Expiration", "DOT Medical Expiration")
    term_c = _col("TerminatedAt", "Terminated", "TerminationDate")

    if not name_c:
        return None

    drivers = []
    for _, r in df.iterrows():
        name = str(r[name_c]).strip() if pd.notna(r[name_c]) else ""
        if not name or name.lower() == "nan":
            continue
        terminated = pd.notna(r[term_c]) if term_c else False
        if terminated:
            continue   # skip ex-employees
        status = str(r[status_c]).strip() if status_c and pd.notna(r[status_c]) else ""
        if status.lower() in {"inactive", "terminated", "deleted"}:
            continue

        def _days(col):
            if not col or pd.isna(r[col]):
                return None, None
            ts = pd.to_datetime(r[col], errors="coerce")
            if pd.isna(ts):
                return None, None
            # Alvys returns ISO timestamps with timezone; `now` is tz-naive
            # (and so is the rest of the scorecard's date arithmetic), so
            # strip tz before subtracting. We only care about the date.
            if getattr(ts, "tz", None) is not None:
                ts = ts.tz_localize(None)
            return ts, int((ts.normalize() - now.normalize()).days)

        lic_exp, lic_days = _days(lic_exp_c)
        med_exp, med_days = _days(med_exp_c)
        drivers.append({
            "name": name,
            "type": (str(r[type_c]).strip() if type_c and pd.notna(r[type_c]) else ""),
            "status": status or "Active",
            "license_exp": lic_exp,
            "license_days": lic_days,
            "medical_exp": med_exp,
            "medical_days": med_days,
        })

    def _within(window, key):
        out = [d for d in drivers
               if isinstance(d.get(key), int) and 0 <= d[key] <= window]
        out.sort(key=lambda d: d[key])
        return out

    return {
        "now": now,
        "monitored": len(drivers),
        "drivers": drivers,
        "license_issues_30": _within(LICENSE_EXPIRY_WARN_DAYS, "license_days"),
        "license_critical_14": _within(DRIVER_EXPIRY_CRITICAL_DAYS - 1, "license_days"),
        "medical_issues_30": _within(MEDICAL_EXPIRY_WARN_DAYS, "medical_days"),
        "medical_critical_14": _within(DRIVER_EXPIRY_CRITICAL_DAYS - 1, "medical_days"),
        "window_days_critical": DRIVER_EXPIRY_CRITICAL_DAYS,
    }


_EQUIP_WARN_DAYS     = 60   # orange flag when due within 60 days
_EQUIP_CRITICAL_DAYS = 30   # red flag when due within 30 days


def compute_alvys_equipment(sheets, now: pd.Timestamp | None = None) -> dict | None:
    """Read Trucks and Trailers sheets from Alvys Pipeline.xlsx.

    Returns a dict with:
      tractors   [{unit, vin, annual_due, annual_days, reg_due, reg_days, status}]
      trailers   [same shape]
      tractors_overdue_annual   / _warn60   / _warn30   counts
      trailers_overdue_annual   / _warn60   / _warn30
      tractors_overdue_reg      / _warn60_reg / _warn30_reg
      trailers_overdue_reg      / _warn60_reg / _warn30_reg
      field_names_found          dict of which candidate fields matched
    """
    if not sheets:
        return None
    trucks_df   = sheets.get("Trucks")
    trailers_df = sheets.get("Trailers")
    if (trucks_df is None or trucks_df.empty) and (trailers_df is None or trailers_df.empty):
        return None
    now = now or pd.Timestamp.now()

    def _days_until(val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None, None
        ts = pd.to_datetime(val, errors="coerce")
        if pd.isna(ts):
            return None, None
        if getattr(ts, "tz", None) is not None:
            ts = ts.tz_localize(None)
        return ts, int((ts.normalize() - now.normalize()).days)

    _TRAILER_EXCLUDE = {"preload 1", "preload 2", "preload 3", "preload 4", "preload 5"}
    _TRUCK_EXCLUDE   = {"test"}

    def _parse_sheet(df, exclude: set[str] | None = None):
        if df is None or df.empty:
            return []
        rows = []
        annual_col = next((c for c in df.columns if "AnnualInspection" in c or c == "AnnualInspectionDue"), None)
        reg_col    = next((c for c in df.columns if "Registration" in c or "Expir" in c and c != annual_col), None)
        unit_col   = next((c for c in ["Unit", "TruckNumber", "TrailerNumber", "Name", "UnitNumber"] if c in df.columns), None)
        for _, r in df.iterrows():
            unit = str(r[unit_col]).strip() if unit_col and pd.notna(r.get(unit_col)) else "—"
            if not unit or unit.lower() in {"nan", "none"}:
                unit = "—"
            if exclude and unit.lower() in exclude:
                continue
            vin  = str(r.get("VIN", "")).strip() if pd.notna(r.get("VIN", None)) else ""
            make = str(r.get("Make", "")).strip() if pd.notna(r.get("Make", None)) else ""
            model= str(r.get("Model", "")).strip() if pd.notna(r.get("Model", None)) else ""
            year = str(r.get("Year", "")).strip() if pd.notna(r.get("Year", None)) else ""
            status = str(r.get("Status", "")).strip()
            # Active-only filter: keep blanks (treat as active) and explicit
            # "Active"; drop "Inactive", "Sold", "OutOfService", "Retired", etc.
            if status and status.lower() != "active":
                continue
            annual_ts, annual_days = _days_until(r.get(annual_col) if annual_col else None)
            reg_ts,    reg_days    = _days_until(r.get(reg_col) if reg_col else None)
            # Last DOT inspection date — trailers-only, populated from Alvys
            # /maintenance/search (DOT/Annual category) by src/main.py. The
            # 120-day company-policy threshold counts FROM this date forward;
            # AnnualInspectionDue (above) is the federal 365-day rule.
            last_insp_raw = r.get("LastInspectionDate") if "LastInspectionDate" in df.columns else None
            last_insp_ts = None
            policy_days_left = None
            if last_insp_raw not in (None, "") and pd.notna(last_insp_raw):
                try:
                    last_insp_ts = pd.to_datetime(last_insp_raw, errors="coerce")
                    if pd.notna(last_insp_ts):
                        if getattr(last_insp_ts, "tz", None) is not None:
                            last_insp_ts = last_insp_ts.tz_localize(None)
                        days_since = (now.normalize() - last_insp_ts.normalize()).days
                        policy_days_left = 120 - days_since
                    else:
                        last_insp_ts = None
                except Exception:
                    last_insp_ts = None
            # Trucks-only extras — silently absent on the Trailers sheet.
            mileage = r.get("LastMileage") if "LastMileage" in df.columns else None
            try:
                mileage_int = int(float(mileage)) if mileage not in (None, "", float("nan")) and pd.notna(mileage) else None
            except (TypeError, ValueError):
                mileage_int = None
            oil_dt, oil_days = _days_until(r.get("LastOilChangeDate") if "LastOilChangeDate" in df.columns else None)
            oil_mi = r.get("LastOilChangeMileage") if "LastOilChangeMileage" in df.columns else None
            try:
                oil_mi_int = int(float(oil_mi)) if oil_mi not in (None, "", float("nan")) and pd.notna(oil_mi) else None
            except (TypeError, ValueError):
                oil_mi_int = None
            rows.append({
                "unit":             unit,
                "vin":              vin,
                "make":             make,
                "model":            model,
                "year":             year,
                "status":           status,
                "annual_due":       annual_ts,
                "annual_days":      annual_days,
                "last_inspection":  last_insp_ts,
                "policy_days":      policy_days_left,
                "reg_due":          reg_ts,
                "reg_days":         reg_days,
                "last_mileage":     mileage_int,
                "oil_change_date":  oil_dt,
                "oil_change_days":  oil_days,
                "oil_change_miles": oil_mi_int,
            })
        # Soonest urgency first. For trailers, the 120-day company policy fires
        # before the 365-day federal rule, so sort by policy_days when present
        # and fall back to annual_days.
        def _urgency(r):
            pd_v = r.get("policy_days")
            ad_v = r.get("annual_days")
            return (
                pd_v if isinstance(pd_v, int) else 9999,
                ad_v if isinstance(ad_v, int) else 9999,
            )
        rows.sort(key=_urgency)
        return rows

    tractors = _parse_sheet(trucks_df,   exclude=_TRUCK_EXCLUDE)
    trailers = _parse_sheet(trailers_df, exclude=_TRAILER_EXCLUDE)

    def _counts(rows, key):
        overdue = sum(1 for r in rows if isinstance(r.get(key), int) and r[key] < 0)
        w30     = sum(1 for r in rows if isinstance(r.get(key), int) and 0 <= r[key] <= 30)
        w60     = sum(1 for r in rows if isinstance(r.get(key), int) and 0 <= r[key] <= 60)
        return overdue, w30, w60

    t_od_a, t_w30_a, t_w60_a = _counts(tractors, "annual_days")
    r_od_a, r_w30_a, r_w60_a = _counts(trailers, "annual_days")
    t_od_r, t_w30_r, t_w60_r = _counts(tractors, "reg_days")
    r_od_r, r_w30_r, r_w60_r = _counts(trailers, "reg_days")
    # 120-day company policy: trailers only (where LastInspectionDate is populated).
    r_od_p, r_w30_p, _ = _counts(trailers, "policy_days")

    annual_found = any(isinstance(r.get("annual_days"), int) for r in tractors + trailers)
    reg_found    = any(isinstance(r.get("reg_days"),    int) for r in tractors + trailers)
    policy_found = any(isinstance(r.get("policy_days"), int) for r in trailers)

    return {
        "tractors": tractors,
        "trailers": trailers,
        "tractors_overdue_annual": t_od_a, "tractors_warn30_annual": t_w30_a, "tractors_warn60_annual": t_w60_a,
        "trailers_overdue_annual": r_od_a, "trailers_warn30_annual": r_w30_a, "trailers_warn60_annual": r_w60_a,
        "tractors_overdue_reg":    t_od_r, "tractors_warn30_reg":    t_w30_r, "tractors_warn60_reg":    t_w60_r,
        "trailers_overdue_reg":    r_od_r, "trailers_warn30_reg":    r_w30_r, "trailers_warn60_reg":    r_w60_r,
        "trailers_overdue_policy": r_od_p, "trailers_warn30_policy": r_w30_p,
        "annual_found": annual_found,
        "reg_found":    reg_found,
        "policy_found": policy_found,
        "total_tractors": len(tractors),
        "total_trailers": len(trailers),
    }


def build_page_equipment(equipment, date_str, kind="tractors", pg=4) -> str:
    """Equipment Compliance page — renders one fleet type per call.
    kind='tractors' → page 4; kind='trailers' → page 5."""
    title = ("Equipment Compliance &mdash; Tractor Inspections" if kind == "tractors"
             else "Equipment Compliance &mdash; Trailer Inspections")
    header = _header(title, pg, date_str, section="SAFETY")

    if not equipment:
        return (header
                + _brief("Equipment compliance data not yet loaded — run the Alvys refresh "
                         "to populate the Trucks and Trailers sheets in Alvys Pipeline.xlsx.", "mute"))

    annual_found = equipment.get("annual_found", False)
    reg_found    = equipment.get("reg_found",    False)

    if not annual_found and not reg_found:
        pending_note = (
            "<div style='padding:16px 24px;color:#64748b;font-size:13px;'>"
            "Inspection due-date fields not yet matched. Run the Alvys refresh and check "
            "<code>output/_debug/sample_trucks.json</code> for the actual field names, "
            "then update the candidate list in <code>_build_equipment_df()</code>.</div>"
        )
        return header + pending_note

    def _badge(days):
        if days is None:
            return f"<span style='color:{MUTE};'>—</span>"
        if days < 0:
            return (f"<span style='background:{BADBG};color:{BAD};font-size:11px;"
                    f"padding:2px 6px;border-radius:4px;font-weight:700;'>OVERDUE {abs(days)}d</span>")
        if days <= _EQUIP_CRITICAL_DAYS:
            return (f"<span style='background:{BADBG};color:{BAD};font-size:11px;"
                    f"padding:2px 6px;border-radius:4px;font-weight:700;'>{days}d</span>")
        if days <= _EQUIP_WARN_DAYS:
            return (f"<span style='background:{WARNBG};color:{WARN};font-size:11px;"
                    f"padding:2px 6px;border-radius:4px;font-weight:700;'>{days}d</span>")
        return f"<span style='color:{MUTE};font-size:12px;'>{days}d</span>"

    def _date_str(ts):
        if ts is None or (isinstance(ts, float) and pd.isna(ts)):
            return "—"
        try:
            return pd.Timestamp(ts).strftime("%b %d, %Y")
        except Exception:
            return "—"

    def _equipment_table(rows, kind):
        if not rows:
            return (f"<div style='padding:8px 0;color:{MUTE};font-size:13px;'>"
                    f"No {kind} records found.</div>")

        show_annual  = any(isinstance(r.get("annual_days"), int) for r in rows)
        show_policy  = any(isinstance(r.get("policy_days"), int) for r in rows)
        show_reg     = any(isinstance(r.get("reg_days"),    int) for r in rows)
        show_mileage = any(isinstance(r.get("last_mileage"), int) for r in rows)
        show_oil     = any(r.get("oil_change_date") is not None
                           or isinstance(r.get("oil_change_miles"), int)
                           for r in rows)

        th = f"<th style='text-align:left;padding:6px 8px;font-size:11px;letter-spacing:.4px;text-transform:uppercase;color:{MUTE};border-bottom:2px solid {LINE};'>{{t}}</th>"
        head_cols = [th.format(t="Unit")]
        if any(r.get("year") or r.get("make") for r in rows):
            head_cols.append(th.format(t="Year/Make"))
        if show_policy:
            head_cols.append(th.format(t="Last DOT Insp"))
            head_cols.append(th.format(t="120d Policy"))
        if show_annual:
            head_cols.append(th.format(t="Annual Insp Due"))
            head_cols.append(th.format(t="Days"))
        if show_reg:
            head_cols.append(th.format(t="Reg Expires"))
            head_cols.append(th.format(t="Days"))
        if show_mileage:
            head_cols.append(th.format(t="Last Mileage"))
        if show_oil:
            head_cols.append(th.format(t="Last Oil Change"))

        tbody = ""
        for i, r in enumerate(rows):
            bg = "#f8fafc" if i % 2 == 0 else "#fff"
            td = f"<td style='padding:6px 8px;font-size:13px;border-bottom:1px solid {LINE};vertical-align:middle;'>{{v}}</td>"
            label = r["unit"] or "—"
            if r.get("status") and r["status"].lower() not in {"active", ""}:
                label += f" <span style='color:{MUTE};font-size:11px;'>({r['status']})</span>"
            cols_td = [td.format(v=label)]
            if any(r.get("year") or r.get("make") for r in rows):
                ym = " ".join(filter(None, [r.get("year"), r.get("make"), r.get("model")])) or "—"
                cols_td.append(td.format(v=f"<span style='color:{MUTE};font-size:12px;'>{ym}</span>"))
            if show_policy:
                cols_td.append(td.format(v=_date_str(r.get("last_inspection"))))
                cols_td.append(td.format(v=_badge(r.get("policy_days"))))
            if show_annual:
                cols_td.append(td.format(v=_date_str(r.get("annual_due"))))
                cols_td.append(td.format(v=_badge(r.get("annual_days"))))
            if show_reg:
                cols_td.append(td.format(v=_date_str(r.get("reg_due"))))
                cols_td.append(td.format(v=_badge(r.get("reg_days"))))
            if show_mileage:
                mi = r.get("last_mileage")
                cols_td.append(td.format(v=f"{mi:,}" if isinstance(mi, int) else "—"))
            if show_oil:
                dt    = r.get("oil_change_date")
                miles = r.get("oil_change_miles")
                parts = []
                if dt is not None:
                    parts.append(_date_str(dt))
                if isinstance(miles, int):
                    parts.append(f"<span style='color:{MUTE};font-size:11px;'>@ {miles:,} mi</span>")
                cols_td.append(td.format(v=" ".join(parts) if parts else "—"))
            tbody += f"<tr style='background:{bg};'>{''.join(cols_td)}</tr>"

        return (f"<table width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;'>"
                f"<thead><tr>{''.join(head_cols)}</tr></thead>"
                f"<tbody>{tbody}</tbody></table>")

    def _summary_pill(overdue, warn30, warn60, label):
        parts = []
        if overdue:
            parts.append(f"<span style='background:{BADBG};color:{BAD};font-size:11px;padding:2px 7px;border-radius:4px;font-weight:700;margin-right:4px;'>{overdue} OVERDUE</span>")
        if warn30:
            parts.append(f"<span style='background:{BADBG};color:{BAD};font-size:11px;padding:2px 7px;border-radius:4px;margin-right:4px;'>{warn30} within 30d</span>")
        elif warn60:
            parts.append(f"<span style='background:{WARNBG};color:{WARN};font-size:11px;padding:2px 7px;border-radius:4px;margin-right:4px;'>{warn60} within 60d</span>")
        if not parts:
            parts.append(f"<span style='background:{GOODBG};color:{GOOD};font-size:11px;padding:2px 7px;border-radius:4px;'>All current</span>")
        return f"<span style='font-size:12px;font-weight:700;color:{INK};margin-right:8px;'>{label}</span>" + "".join(parts)

    def _section_block(rows, kind, overdue_a, w30_a, w60_a, overdue_r, w30_r, w60_r,
                       overdue_p=None, w30_p=None):
        parts = [_summary_pill(overdue_a, w30_a, w60_a, "Annual inspection (365d federal):")]
        if overdue_p is not None:
            parts.append(_summary_pill(overdue_p, w30_p, 0, "DOT inspection (120d policy):"))
        parts.append(_summary_pill(overdue_r, w30_r, w60_r, "Registration:"))
        summary = (f"<div style='padding:10px 0 6px;'>"
                   + "&nbsp;&nbsp;".join(parts)
                   + "</div>")
        return (f"{_section(kind + ' &mdash; ' + str(len(rows)) + ' units')}"
                + summary
                + _equipment_table(rows, kind))

    if kind == "tractors":
        body = _section_block(
            equipment["tractors"], "Tractors",
            equipment["tractors_overdue_annual"], equipment["tractors_warn30_annual"], equipment["tractors_warn60_annual"],
            equipment["tractors_overdue_reg"],    equipment["tractors_warn30_reg"],    equipment["tractors_warn60_reg"],
        )
    else:
        body = _section_block(
            equipment["trailers"], "Trailers",
            equipment["trailers_overdue_annual"], equipment["trailers_warn30_annual"], equipment["trailers_warn60_annual"],
            equipment["trailers_overdue_reg"],    equipment["trailers_warn30_reg"],    equipment["trailers_warn60_reg"],
            overdue_p=equipment.get("trailers_overdue_policy", 0),
            w30_p=equipment.get("trailers_warn30_policy", 0),
        )
    sort_note = ("Sort: soonest 120-day company policy first (trailers); soonest annual inspection first (tractors)."
                 if kind == "trailers"
                 else "Sort: soonest annual inspection first.")
    body += (f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
             f"Source: Alvys Pipeline.xlsx Trucks + Trailers sheets, populated from Alvys POST /maintenance/search "
             f"(Category = DOT/Annual). Red = overdue or &le;30d. Orange = 31&ndash;60d. {sort_note}</div>")

    return header + f"<div style='padding:8px 24px 18px;'>{body}</div>"


# ----------------------------------------------------------------------
# HTML design system
# ----------------------------------------------------------------------
# XFreight-branded palette (Style 04). Single accent = XFreight red.
# Variance-only color: red for negative/over-threshold, green for positive,
# everything else neutral grey. ACCENT replaces the older orange brand color
# throughout the brief — that retires the dashboard-y orange/blue mix.
XFREIGHT_RED = "#c41e2a"
XFREIGHT_RED_DARK = "#8f1620"
NAVY = "#1a1a1a"          # was deep navy — now near-black ink
INK = "#1a1a1a"
MUTE = "#6b6b6b"
LINE = "#ececec"          # softer hairline
TILEBG = "#fafafa"        # near-white card background
GOOD = "#0f6b3d"
GOODBG = "#e7f3ec"
WARN = XFREIGHT_RED       # warnings collapse into the brand accent
WARNBG = "#fde8ea"
PAGE_COUNT = 13
ACCENTBG = "#fde8ea"      # light red tint replaces the orange current-week column
BAD = XFREIGHT_RED
BADBG = "#fde8ea"
ACCENT = XFREIGHT_RED     # was orange — now brand red
BLUE = "#3a4a5a"          # neutral slate replaces the old chart blue
FONT = ("font-family:-apple-system,'Helvetica Neue',Helvetica,Arial,sans-serif;"
        "font-feature-settings:'tnum';")  # tabular numerals for clean column alignment
# Serif stack for page-section headlines + hero numbers.
FONT_SERIF = "font-family:Georgia,'Times New Roman',serif;"

# FMCSA CSA intervention thresholds by BASIC category.
# Unsafe Driving and Crash Indicator alert at 65th percentile for all carrier
# sizes; all other BASICs alert at 80th.
_CSA_INTERVENTION = {
    "unsafe driving": 65,
    "crash indicator": 65,
    "maintenance": 80,
    "hos compliance": 80,
    "hours-of-service compliance": 80,
    "hazardous materials": 80,
    "haz mat": 80,
    "driver fitness": 80,
    "controlled substances": 80,
    "drugs/alcohol": 80,
    "drugs & alcohol": 80,
    "controlled substances/alcohol": 80,
}


def _pill(t, k, nowrap=True):
    bg = {"good": GOODBG, "warn": WARNBG, "bad": BADBG, "mute": "#eef2f7"}[k]
    fg = {"good": GOOD, "warn": WARN, "bad": BAD, "mute": MUTE}[k]
    # Most pills are inline badges that shouldn't break across lines, but
    # the descriptive pills under tiles (e.g. "Costing Based on Last 10 Days",
    # "10d pay + YTD overhead") are narrower than their text and need to
    # wrap to 2 lines rather than overflow + clip — those callers pass
    # nowrap=False.
    ws = "white-space:nowrap" if nowrap else "white-space:normal"
    return (f"<span style='display:inline-block;background:{bg};color:{fg};font-size:11px;"
            f"font-weight:700;padding:2px 8px;border-radius:10px;line-height:1.4;{ws}'>{t}</span>")


def _wow(current, prior, lower_is_better: bool = False, fmt=None) -> str:
    """Week-over-week change badge: ▲ / ▼ with % change, colored good/bad."""
    if not _isnum(current) or not _isnum(prior) or prior == 0:
        return ""
    chg = (current - prior) / abs(prior)
    up = chg >= 0
    good = (not up) if lower_is_better else up
    color = GOOD if good else BAD
    arrow = "&#9650;" if up else "&#9660;"
    label = fmt(abs(chg)) if fmt else f"{abs(chg)*100:.0f}%"
    return (f"<span style='font-size:11px;font-weight:700;color:{color};"
            f"margin-left:4px;white-space:nowrap;'>{arrow} {label} WoW</span>")


def _tile(label, value, sub, width="25%"):
    """XFreight-branded tile — hero number in Georgia serif, restrained chrome,
    XFreight red rule under the label for visual rhythm across rows."""
    return (f"<td class='tile' width='{width}' style='padding:6px;' valign='top'>"
            f"<div style='background:#fff;border:1px solid {LINE};border-radius:8px;"
            f"padding:16px 16px 14px;border-top:3px solid {XFREIGHT_RED};'>"
            f"<div style='font-size:9.5px;letter-spacing:1.5px;text-transform:uppercase;"
            f"color:{MUTE};font-weight:700;margin-bottom:10px;'>{label}</div>"
            f"<div style='{FONT_SERIF}font-size:26px;font-weight:400;color:{INK};"
            f"letter-spacing:-0.8px;line-height:1;margin-bottom:8px;'>{value}</div>"
            f"<div style='font-size:11px;color:{MUTE};line-height:1.4;'>{sub}</div>"
            f"</div></td>")


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
    return (f"<td class='tile' width='25%' style='padding:6px;' valign='top'><div style='background:#fff;border:1px solid {LINE};"
            f"border-radius:10px;padding:12px 10px 10px;'><div style='font-size:11px;letter-spacing:.5px;"
            f"text-transform:uppercase;color:{hf};font-weight:700;background:{hb};display:inline-block;"
            f"padding:2px 8px;border-radius:8px;margin-bottom:8px;'>{label}</div>"
            f"<table width='100%' cellpadding='0' cellspacing='0'><tr>{c('24h', v24, True)}{c('7d', v7)}{c('MTD', vmtd)}</tr></table></div></td>")


def _bar_chart(title, months, values, sub="", fmt=str):
    if not months:
        return (f"<td class='tile' valign='top' style='padding:6px;'><div style='border:1px solid {LINE};border-radius:10px;"
                f"padding:14px;color:{MUTE};font-size:12px;'>{title}: data pending</div></td>")
    maxv = max(values) if max(values) else 1
    H = 84
    # Equal-width column for every month so the bars distribute evenly even
    # when label content varies (e.g. "$0.000" vs "$2.687", or "0" vs "146")
    # — without this the auto table layout shrinks short-label columns and
    # bunches the bars toward the wider-label columns.
    col_w = f"{100 / len(months):.4f}%"
    bar = lbl = ""
    for i, (m, v) in enumerate(zip(months, values)):
        h = max(int(round(H * v / maxv)), (3 if v > 0 else 0))
        last = (i == len(months) - 1)
        bc = ACCENT if last else BLUE
        # Months with no underlying data (v == 0) get a muted em-dash label
        # instead of "$0.000" / "0" so empty-month columns read as "no data"
        # rather than as a real zero. fmt(v) is used for true non-zero values.
        if v > 0:
            label_html = fmt(v)
            label_color = INK
        else:
            label_html = "&mdash;"
            label_color = MUTE
        # 7.5px label / 1px cell padding: 8.5px still left adjacent labels
        # touching when bars were clustered with similar values (e.g. Apr/May
        # rev/mile within $0.04 of each other). 7.5px gives ~0.22in label
        # width vs ~0.38in column = visible gap, and ~0.27in "$504K" vs
        # ~0.6in AR/AP column = no overflow at the right edge of the tile.
        # Add tiny letter-spacing tweak so the label digits don't sit too
        # close together.
        bar += (f"<td valign='bottom' align='center' width='{col_w}' style='padding:0 1px;'>"
                f"<div style='font-size:7.5px;font-weight:700;color:{label_color};margin-bottom:3px;white-space:nowrap;letter-spacing:-0.1px;'>{label_html}</div>"
                f"<div style='width:16px;height:{h}px;background:{bc};border-radius:3px 3px 0 0;margin:0 auto;'></div></td>")
        lcol = INK if last else MUTE
        lbl += (f"<td align='center' width='{col_w}' style='font-size:9px;color:{lcol};font-weight:{'700' if last else '400'};"
                f"padding-top:4px;white-space:nowrap;'>{m}</td>")
    return (f"<td class='tile' valign='top' style='padding:6px;'><div style='border:1px solid {LINE};border-radius:10px;padding:12px 12px 10px;overflow:hidden;'>"
            f"<div style='font-size:12px;font-weight:800;color:{NAVY};margin-bottom:2px;'>{title}</div>"
            f"<div style='font-size:11px;color:{MUTE};margin-bottom:10px;'>{sub}</div>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='height:{H+22}px;table-layout:fixed;'><tr>{bar}</tr></table>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='table-layout:fixed;'><tr>{lbl}</tr></table></div></td>")


def _donut_gauge(label: str, pct: float, sub_line: str, detail: str, width: str = "33%") -> str:
    """SVG circular donut gauge for compliance tiles (HOS, DVIR, safety score)."""
    import math
    r = 46
    cx = cy = 60
    circ = 2 * math.pi * r
    arc = circ * max(0.0, min(pct, 100.0)) / 100.0
    gap = circ - arc
    if pct >= 95:
        color = GOOD
    elif pct >= 80:
        color = WARN
    else:
        color = BAD
    pct_str = f"{pct:.0f}%"
    svg = (
        f'<svg width="120" height="120" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#e2e8f0" stroke-width="11"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="11"'
        f' stroke-dasharray="{arc:.2f} {gap:.2f}" stroke-linecap="round"'
        f' transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy - 5}" text-anchor="middle" font-size="21" font-weight="800"'
        f' font-family="Arial,Helvetica,sans-serif" fill="{INK}">{pct_str}</text>'
        f'<text x="{cx}" y="{cy + 12}" text-anchor="middle" font-size="8.5" font-weight="700"'
        f' font-family="Arial,Helvetica,sans-serif" fill="{color}" letter-spacing="0.6">{sub_line}</text>'
        f'</svg>'
    )
    return (
        f"<td class='tile' width='{width}' style='padding:6px;' valign='top'>"
        f"<div style='background:{TILEBG};border:1px solid {LINE};border-radius:10px;"
        f"padding:14px 10px 12px;text-align:center;'>"
        f"<div style='font-size:11px;letter-spacing:.6px;text-transform:uppercase;"
        f"color:{MUTE};font-weight:700;margin-bottom:8px;'>{label}</div>"
        f"{svg}"
        f"<div style='font-size:11px;color:{MUTE};margin-top:6px;'>{detail}</div>"
        f"</div></td>"
    )


def _section(t, span=4):
    """XFreight section header: serif italic accent + black 36px underbar.
    Inline-styled so it renders identically in email and PDF."""
    # Split a 'main // accent' title into pieces so we can italicize the accent
    # in XFreight red — mirrors the style-04 sample (e.g. 'X-Trux // Asset trucking').
    if "//" in t:
        main, _, accent_part = t.partition("//")
        title_html = (f"<span>{main.strip()}</span> "
                      f"<span style='color:{XFREIGHT_RED};font-style:italic;font-weight:700;'>// {accent_part.strip()}</span>")
    else:
        title_html = t
    return (f"<tr><td colspan='{span}' style='padding:22px 6px 4px;'>"
            f"<div style='{FONT_SERIF}font-size:17px;font-weight:400;color:{INK};"
            f"letter-spacing:-0.3px;'>{title_html}</div>"
            f"<div style='width:36px;height:2px;background:{INK};margin-top:6px;margin-bottom:10px;'></div>"
            f"</td></tr>")


def _xfreight_logo_svg(width: int = 180, height: int = 32) -> str:
    """Inline SVG re-creation of the XFREIGHT logo (red bar + white speed-line
    streaks on the left + italic bold white wordmark). Embedded inline so the
    email and PDF both render it without an external image dependency."""
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 220 38' "
        f"width='{width}' height='{height}' role='img' aria-label='XFreight'>"
        f"<rect width='220' height='38' rx='2' fill='{XFREIGHT_RED}'/>"
        f"<g fill='#fff'>"
        f"<rect x='8' y='6' width='38' height='2.4'/>"
        f"<rect x='10' y='10' width='34' height='2.4'/>"
        f"<rect x='6' y='14' width='42' height='2.4'/>"
        f"<rect x='12' y='18' width='30' height='2.4'/>"
        f"<rect x='8' y='22' width='38' height='2.4'/>"
        f"<rect x='10' y='26' width='34' height='2.4'/>"
        f"<rect x='6' y='30' width='42' height='2.4'/>"
        f"</g>"
        f"<text x='56' y='27' font-family='Helvetica,Arial,sans-serif' "
        f"font-weight='900' font-style='italic' font-size='22' "
        f"letter-spacing='-0.5' fill='#fff'>XFREIGHT</text>"
        f"</svg>"
    )


def _header(sub, pg, date_str, section=None):
    """Branded page header — XFreight logo bar + serif italic doc label + date,
    with an optional section chip and a thick red rule below.
    Used at the top of every detail page."""
    logo = _xfreight_logo_svg(width=150, height=26)
    section_chip = ""
    if section:
        section_chip = (
            f"<span style='display:inline-block;padding:2px 9px;border-radius:3px;"
            f"background:{XFREIGHT_RED};color:#fff;font-size:9px;font-weight:800;"
            f"letter-spacing:1.2px;margin-left:14px;vertical-align:middle;'>{section}</span>")
    # Two-line date treatment matches the style-04 sample.
    try:
        from datetime import datetime as _dt
        # date_str examples: 'Thursday, June 4, 2026' or '%A, %B %d, %Y'
        dt = _dt.strptime(date_str, "%A, %B %d, %Y")
        day_part = dt.strftime("%A")
        date_part = dt.strftime("%B %d, %Y")
    except Exception:
        day_part, date_part = date_str, ""
    return (
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-bottom:4px solid {XFREIGHT_RED};padding:6px 24px 14px;'>"
        f"<tr>"
        f"<td valign='middle' style='padding:0;'>"
        f"{logo}{section_chip}"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:13px;color:{INK};"
        f"font-weight:400;margin-top:8px;'>{sub}</div>"
        f"</td>"
        f"<td align='right' valign='middle' style='padding:0;font-size:9.5px;color:{MUTE};font-weight:500;'>"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:11px;color:{INK};"
        f"font-weight:600;margin-bottom:2px;'>{day_part}</div>"
        f"<div>{date_part}</div>"
        f"<div class='pg-of' style='font-size:9px;color:{MUTE};margin-top:4px;letter-spacing:0.5px;'>"
        f"Page {pg} of {PAGE_COUNT}</div>"
        f"</td>"
        f"</tr></table>")


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
    """Callout/lede block — left accent bar in brand red (or variance color),
    near-white fill, sans-serif body. Used for the Bottom Line and per-page notes."""
    bar = {"good": GOOD, "warn": WARN, "bad": BAD, "mute": XFREIGHT_RED}[k]
    return (f"<tr><td colspan='4' style='padding:6px;'>"
            f"<div style='border-left:4px solid {bar};background:#fafafa;"
            f"padding:12px 16px;font-size:12.5px;color:{INK};line-height:1.55;'>{text}</div>"
            f"</td></tr>")


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
                rpm_goal_trend=None, drag=None, margin_projection=None, uninvoiced=None,
                samba=None, alvys_drivers=None, dso_hist=None,
                ontime=None, dh_trend=None, customer_rpm=None, equipment=None) -> str:
    co = qb_company_totals(qb_pnl) if qb_pnl else {}
    w7 = (alvys or {}).get("7d", {})
    wmtd = (alvys or {}).get("mtd", {})
    w7a = ((alvys or {}).get("asset") or {}).get("7d", w7)  # X-Trux/XFreight 7d
    p7a = ((alvys or {}).get("asset") or {}).get("prior_7d", {})  # prior 7d (14d-7d)
    # X-Trux/XFreight MTD — same Power BI-aligned basis (revenue / Loaded
    # miles) that feeds the Revenue/Mile and Dead head % tiles. The bottom-
    # line blurb uses this so its RPM/DH numbers tie to the Power BI report
    # row-for-row instead of drifting on a 7d-rolling window readers can't
    # cross-check.
    wmtda = ((alvys or {}).get("asset") or {}).get("mtd", wmtd)

    fleet = (alvys or {}).get("fleet", {})
    empty_td = "<td class='tile-empty' width='25%' style='padding:6px;'></td>"
    # AR Past Due tile shows both system-of-record (QuickBooks) and
    # operational (Alvys) totals so the reconciliation gap is visible at the
    # headline. Gap = Alvys − QB usually represents delivered loads not yet
    # invoiced in QB (page 8 details).
    _qb_past_due = qb_ar.get("total_past_due") if qb_ar else None
    _alvys_past_due = (alvys_ar or {}).get("overdue") if alvys_ar else None
    _ar_gap = None
    if _isnum(_qb_past_due) and _isnum(_alvys_past_due):
        _ar_gap = float(_alvys_past_due) - float(_qb_past_due)

    def _dual_ar_tile() -> str:
        # NOTE on the inline word-break/white-space overrides: the global PDF
        # CSS rule `td.tile { word-break:break-word; overflow-wrap:anywhere }`
        # — which keeps long tile *labels* from blowing past the column width —
        # was also breaking the money values ($51,277 rendering as $51,27 / 7).
        # Each money <td> explicitly opts out with white-space:nowrap and
        # word-break:keep-all so the dollar amounts stay on one line.
        _money_td_style = (
            f"font-size:20px;font-weight:800;color:{INK};padding:2px 0;"
            "white-space:nowrap;word-break:keep-all;overflow-wrap:normal;"
        )
        rows = (f"<table width='100%' cellpadding='0' cellspacing='0' style='margin:6px 0 6px;'>"
                f"<tr><td style='font-size:13px;color:{MUTE};padding:2px 0;width:46px;'>QB</td>"
                f"<td align='right' style='{_money_td_style}'>"
                f"{money(_qb_past_due)}</td></tr>"
                f"<tr><td style='font-size:13px;color:{MUTE};padding:2px 0;'>Alvys</td>"
                f"<td align='right' style='{_money_td_style}'>"
                f"{money(_alvys_past_due)}</td></tr>")
        if _ar_gap is not None:
            gap_color = WARN if abs(_ar_gap) >= 1 else MUTE
            rows += (f"<tr><td style='font-size:12px;color:{MUTE};padding:4px 0 0;border-top:1px solid {LINE};'>Gap</td>"
                     f"<td align='right' style='font-size:14px;font-weight:700;color:{gap_color};"
                     f"padding:4px 0 0;border-top:1px solid {LINE};"
                     f"white-space:nowrap;word-break:keep-all;overflow-wrap:normal;'>"
                     f"{money(_ar_gap)}</td></tr>")
        rows += "</table>"
        return (f"<div style='background:{TILEBG};border:1px solid {LINE};border-radius:10px;"
                f"padding:14px 14px 12px;margin-bottom:12px;'>"
                f"<div style='font-size:11px;letter-spacing:.6px;text-transform:uppercase;color:{MUTE};"
                f"font-weight:700;'>AR past due</div>{rows}"
                f"<div style='font-size:12px;color:{MUTE};'>"
                f"{_pill('see pg 11', 'bad')} &middot; gap = un-invoiced loads (see pg 11)</div></div>")

    recv_left = ("<td class='tile' width='25%' valign='top' style='padding:6px;'>"
                 + _dual_ar_tile()
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
    _xt_asset = ((alvys or {}).get("asset") or {}).get("mtd", {})
    _xt_empty = _xt_asset.get("empty")
    _xt_loaded = _xt_asset.get("loaded")
    # Subtitle shows raw inputs so the math can be verified against Power BI row-for-row.
    _mi_sub = (f"{num(_xt_loaded)} loaded + {num(_xt_empty)} empty"
               if _isnum(_xt_loaded) and _isnum(_xt_empty)
               else _pill("X-Trux + XFreight", "mute"))
    _rpm_sub_tile = (f"{money(_xt_rev)} &divide; {num(_xt_miles)} mi"
                     if _isnum(_xt_rev) and _isnum(_xt_miles)
                     else _pill("X-Trux", "mute"))
    # Tile order pairs mileage with rev/mile (slots 1 & 2) and loads with
    # rev/load (slots 3 & 4) so each $/X ratio sits next to its denominator.
    _rpm_wow = _wow(w7a.get("rpm"), p7a.get("rpm"))
    _loads_wow = _wow(w7a.get("loads"), p7a.get("loads"))
    xtrux_r1 = (_tile("X-Trux Mileage &middot; MTD", num(_xt_miles), _mi_sub)
                + _tile("Revenue / mile &middot; MTD", rpm(_xt_rpm),
                        _rpm_sub_tile + ("&nbsp;" + _rpm_wow if _rpm_wow else ""))
                + _tile("X-Trux Loads &middot; MTD", num(_xt_loads),
                        _pill("X-Trux + XFreight", "mute") + ("&nbsp;" + _loads_wow if _loads_wow else ""))
                + _tile("Revenue / load &middot; MTD", money(_xt_rpl), _pill("X-Trux", "mute")))
    # Empty miles first (the raw number), Dead head % next (the ratio).
    _dh_sub = (f"{num(_xt_empty)} &divide; {num(_xt_miles)} mi &nbsp;"
               + f"goal &le;{pct(TARGET_DEADHEAD)} "
               + _pill("DH", _flag_kind(_xt_asset.get("deadhead"), TARGET_DEADHEAD, True))
               if _isnum(_xt_empty) and _isnum(_xt_miles)
               else f"goal &le;{pct(TARGET_DEADHEAD)} "
                    + _pill("DH", _flag_kind(_xt_asset.get("deadhead"), TARGET_DEADHEAD, True)))
    _dh_wow = _wow(w7a.get("deadhead"), p7a.get("deadhead"), lower_is_better=True, fmt=lambda v: f"{v*100:.1f}pp")
    _ontime = ontime or {}
    _ot_rate = _ontime.get("rate_mtd")
    _ot_tile = _tile(
        "On-time delivery &middot; MTD",
        (f"{_ot_rate:.0f}%" if _isnum(_ot_rate) else "n/a"),
        (f"{_ontime.get('on_time_mtd',0)} of {_ontime.get('total_mtd',0)} loads"
         if _ontime.get("available") else _pill("data pending", "mute")))
    xtrux_r2 = (_tile("Empty miles &middot; MTD", num(_xt_empty), _pill("X-Trux + XFreight", "mute"))
                + _tile("Dead head % &middot; MTD", pct(_xt_asset.get("deadhead")),
                        _dh_sub + ("&nbsp;" + _dh_wow if _dh_wow else ""))
                + _tile("Active trucks &middot; MTD", num(fleet.get("active_trucks")), _pill("X-Trux + XFreight", "mute"))
                + _ot_tile)
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
    # Under month-rollover, the "estimate" is just last completed month's
    # actual settled margin — relabel so the tile doesn't read "Est. June"
    # while showing May's final number.
    _est_prefix = "May" if False else "Est."  # placeholder, set below
    if _mp.get("rollover"):
        _tile_label = f"{_mp.get('mtd_label', 'Prior month')} margin &middot; final"
    else:
        _tile_label = f"Est. {_month_lbl} margin"
    def _proj_tile(ent_key, pill_text):
        ent = _mp.get(ent_key) or {}
        sub = (_pill(pill_text, "mute")
               + f" &middot; {_de}/{_dim}d &middot; t{_td} {pct(ent.get('trailing_margin_pct'))}")
        return _tile(_tile_label, money(ent.get("projected_margin")), sub)
    # Order: Combined projection in the leftmost slot (visually anchors the
    # row's lead number), per-entity projections in the middle, and the plain
    # Loads count on the right.
    t1b = (_proj_tile("combined", "X-Trux + X-Linx")
           + _proj_tile("X-Trux", "X-Trux")
           + _proj_tile("X-Linx", "X-Linx")
           + loads_tile)
    # X-Trux Overview row 3: 6-month avg rev / mile trend — overall (X-Trux +
    # XFreight asset fleet) plus a direct-customers vs broker-freight split,
    # with the dead-head % monthly trend sitting next to its tile on row 2.
    _rpm_d_labels, _rpm_d_values = ((rpm_trend or {}).get("direct") or ([], []))
    _rpm_b_labels, _rpm_b_values = ((rpm_trend or {}).get("broker") or ([], []))
    _rpm_c_labels, _rpm_c_values = ((rpm_trend or {}).get("combined") or ([], []))
    _rpm_sub = "monthly avg &middot; X-Trux + XFreight &middot; *MTD"
    _dh_t = dh_trend or {}
    _dh_trend_td = (_bar_chart("Dead head % &middot; 6-month trend",
                               _dh_t.get("labels") or [], _dh_t.get("values") or [],
                               "X-Trux + XFreight &middot; *MTD",
                               fmt=lambda v: f"{v:.1f}%")
                    if _dh_t.get("labels") else empty_td)
    xtrux_r3 = (_bar_chart("Overall &middot; rev / mile", _rpm_c_labels, _rpm_c_values, _rpm_sub, fmt=rpm2)
                + _bar_chart("Direct customers &middot; rev / mile", _rpm_d_labels, _rpm_d_values, _rpm_sub, fmt=rpm2)
                + _bar_chart("Broker freight &middot; rev / mile", _rpm_b_labels, _rpm_b_values, _rpm_sub, fmt=rpm2)
                + _dh_trend_td)

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
        # Gap to goal compares the Goal Rate against the MTD revenue / mile
        # (the $2.886 figure on the X-Trux Overview tile), NOT the 10-day
        # "actual recent" rate.  That way the gap reads against month-to-date
        # performance rather than the short trailing window.
        _goal_rpm = g.get("goal_rpm")
        _mtd_rpm = _xt_rpm  # MTD revenue / mile, computed earlier in this fn
        if _isnum(_goal_rpm) and _isnum(_mtd_rpm):
            gap = _goal_rpm - _mtd_rpm
            gap_kind = "good" if gap <= 0 else "bad"  # MTD >= goal is good
            gap_sub = _pill(("at/above goal" if gap <= 0 else "below goal"),
                            gap_kind, nowrap=False)
            gap_val = rpm(abs(gap))
        else:
            gap_kind, gap_sub, gap_val = "mute", _pill("need MTD rev/mi", "mute", nowrap=False), "n/a"
        # Cost-per-mile sub-pill spells out the time windows behind each
        # component so readers can audit the basis at a glance:
        #   driver pay = trailing N-day window (10d default, widens to
        #               30/60/90 on light weeks via RPM_GOAL_FALLBACK_WINDOWS)
        #   overhead   = fiscal-YTD (QB P&L is "This Fiscal Year")
        _pay_win = g.get("pay_window_used") or g.get("pay_window_days") or "?"
        # Tile sub-line pills under the rate-per-mile tiles get nowrap=False
        # so longer descriptive text ("10d pay + YTD overhead",
        # "Costing Based on Last 10 Days") wraps to a second line inside the
        # tile rather than overflowing and getting clipped.
        goal_tiles = (
            _tile("Cost / mile &middot; X-Trux", rpm(g.get("cost_per_mile")),
                  _pill(f"{_pay_win}d pay + YTD overhead", "mute", nowrap=False))
            + _tile("Goal rate / mile", rpm(g.get("goal_rpm")), goal_pill)
            + _tile("Actual / mile &middot; recent", rpm(g.get("actual_rpm")),
                    _pill(f"Costing Based on Last {g.get('pay_window_used') or g.get('pay_window_days')} Days",
                          "mute", nowrap=False))
            + _tile("Gap to goal / mile", gap_val, gap_sub))
        # Plain-language breakdown so the number is auditable from the email itself.
        _pp, _oh, _cpm = g.get("pay_per_mile"), g.get("overhead_per_mile"), g.get("cost_per_mile")
        _ins = g.get("insurance_surcharge")
        _win = g.get("pay_window_used") or g.get("pay_window_days")
        parts = []
        if _isnum(_pp):
            parts.append(f"driver/owner-op pay {rpm(_pp)}/mi (last {_win}d)")
        if _isnum(_oh):
            _pin = g.get("overhead_pin")
            _live = g.get("overhead_per_mile_live")
            if _isnum(_pin):
                # Office overhead is hand-set while the costing algorithm is being
                # proven out — surface the pin AND the live computed value so the
                # two can be watched until they converge.
                oh_txt = f"office overhead {rpm(_oh)}/mi (pinned while costing algorithm catches up"
                if _isnum(_live):
                    oh_txt += f"; live calc {rpm(_live)}/mi"
                oh_txt += ")"
            else:
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
        if _isnum(_ins) and _ins > 0:
            parts.append(f"liability insurance {rpm(_ins)}/mi (temporary until costing catches up)")
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
                       "overhead held at YTD rate &middot; *MTD", fmt=rpm2)
            + _bar_chart("Goal / mile", gt["labels"], gt.get("goal") or [], _gt_sub, fmt=rpm2)
            + _bar_chart("Actual / mile", gt["labels"], gt.get("actual") or [], _gt_sub, fmt=rpm2)
            + empty_td)

    # AR & AP 6-month balance trend
    ar_labels, ar_vals = ar_hist if ar_hist else ([], [])
    ap_labels, ap_vals = ap_hist if ap_hist else ([], [])
    ar_chart = _bar_chart("AR &mdash; receivable balance", ar_labels, ar_vals,
                          "open AR by month-end &middot; X-Trux + X-Linx &middot; *as-of", fmt=money_m)
    ap_chart = _bar_chart("AP &mdash; payable balance", ap_labels, ap_vals,
                          "total open AP by month-end &middot; *as-of", fmt=money_m)

    # Explicit widths so the AR + AP chart cells don't overlap in landscape
    # PDF.  recv_left is 25%; the two chart cells split the remaining 75% with
    # a slight extra to the right so the rounded edges stay aligned.
    ar_col_td = (f"<td valign='top' width='37%'><table width='100%' cellpadding='0' cellspacing='0' "
                 f"style='table-layout:fixed;'><tr>{ar_chart}</tr></table></td>")
    ap_col_td = (f"<td valign='top' width='38%'><table width='100%' cellpadding='0' cellspacing='0' "
                 f"style='table-layout:fixed;'><tr>{ap_chart}</tr></table></td>")

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

    # Top-5 overdue AR customers (31+ days, by total balance) from QB.
    # Replaces the older "Alvys 61+ spot-check" and "Top 5 customers" tables
    # with the same 4-tile + overdue-invoice detail visual as page 8.
    _qb_overdue_html = ""
    if qb_ar:
        _total31 = qb_ar.get("total31")
        _ovr_rows = qb_ar.get("rows", []) or []
        if _total31 or _ovr_rows:
            _ovr_body = ""
            for r in _ovr_rows:
                k = "bad" if r["bucket"] == "91+" else "warn"
                _ovr_body += _tr(
                    [r["customer"], r["invoice"], r["date"], r["due"], money(r["amount"]), r["bucket"]],
                    ["left", "left", "left", "left", "right", "left"],
                    [None, None, None, None, (k if r["bucket"] == "91+" else None), k],
                )
            _ovr_total = (
                f"<tr><td colspan='4' style='padding:9px 8px;font-weight:800;color:{INK};"
                f"border-top:2px solid {LINE};'>Total 31+ days overdue</td>"
                f"<td align='right' style='padding:9px 8px;font-weight:800;color:{BAD};"
                f"border-top:2px solid {LINE};'>{money(_total31)}</td>"
                f"<td style='border-top:2px solid {LINE};'></td></tr>"
            )
            _qb_overdue_html = (
                f"{_section('Overdue invoices (31+ days) by customer &middot; X-Trux + X-Linx &middot; as of ' + date_str)}"
                f"{_table(['Customer', 'Invoice', 'Inv date', 'Due date', 'Amount', 'Bucket'], ['left', 'left', 'left', 'left', 'right', 'left'], _ovr_body + _ovr_total)}"
            )

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
    _fleet_score = (sf.get("fleet") or {}).get("fleet_score")
    _fleet_score_tile = _tile(
        "Fleet avg safety score",
        (f"{_fleet_score:.0f}" if _isnum(_fleet_score) else "n/a"),
        _pill("0&ndash;100 &middot; higher better", "mute"),
    )
    safety_charts = (chart("events", "Safety events", "per month &middot; *MTD")
                     + chart("hos", "HOS violations", "per month &middot; *MTD")
                     + chart("dvir", "DVIR defects", "reported/mo &middot; *MTD")
                     + _fleet_score_tile)

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

    # Alvys AR aging tiles — all 5 buckets in a single row at 20% each.
    aar = alvys_ar or {}
    alvys_ar_row = ""
    if aar.get("total"):
        _w = "20%"
        # Labels are intentionally short ("Current", "1-30 days", ...) — the
        # section header above already qualifies them as "Alvys AR · aging by
        # due date", and the long "Alvys AR ·" prefix squeezed the value text
        # in 20%-wide tiles.
        alvys_ar_row = (
            _tile("Current", money(aar.get("current")), _pill("not overdue", "mute"), _w)
            + _tile("1&ndash;30 days", money(aar.get("d1_30")), _pill("past due", "warn"), _w)
            + _tile("31&ndash;60 days", money(aar.get("d31_60")), _pill("escalate", "warn"), _w)
            + _tile("61&ndash;90 days", money(aar.get("d61_90")), _pill("escalate", "bad"), _w)
            + _tile("91+ days", money(aar.get("d91plus")), _pill("collections", "bad"), _w)
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

    _goal_rpm = (rpm_goal or {}).get("goal_rpm")
    _goal_txt = f"goal {rpm(_goal_rpm)}" if _isnum(_goal_rpm) else "goal pending QB cost-out"
    # Insights-driven bottom-line bar + action items + coaching cards.
    # Rule-based templates from scorecard_insights.py — $0 ongoing cost.
    # Falls back to the legacy hand-crafted blurb if anything raises.
    _insights_bottom = None
    _insights_actions: list = []
    _insights_coaching: list = []
    try:
        from src import scorecard_insights as _insights
        _prior_snapshot = None
        try:
            from src.scorecard_snapshots import read_prior_snapshot
            _prior_snapshot = read_prior_snapshot()
        except Exception as e:
            log.warning("prior snapshot load failed: %s", e)
        _insights_bottom = _insights.bottom_line(
            alvys=alvys, qb_pnl=qb_pnl, samsara=samsara, rpm_goal=rpm_goal,
            margin_projection=margin_projection, qb_ar=qb_ar, ar_hist=ar_hist,
            samba=samba, alvys_entities=alvys_entities,
            alvys_drivers=alvys_drivers, equipment=equipment,
            prior_snapshot=_prior_snapshot)
        _insights_actions = _insights.action_items(
            alvys=alvys, qb_ar=qb_ar, alvys_ar=alvys_ar, samsara=samsara,
            rpm_goal=rpm_goal, uninvoiced=uninvoiced,
            prior_snapshot=_prior_snapshot, samba=samba,
            alvys_drivers=alvys_drivers)
        _insights_coaching = _insights.coaching_cards(samsara=samsara)
    except Exception as e:
        log.warning("scorecard_insights failed (%s: %s) — using legacy blurb",
                    type(e).__name__, e)

    # Every number gets an explicit scope/window so the blurb is comparable to
    # other views in the email and to Power BI (which uses different windows).
    legacy_bottom = (f"{_lead_phrase(wmtd, rpm_goal)} "
              f"For X-Trux/XFreight asset loads (MTD): "
              f"RPM {rpm(wmtda.get('rpm'))} ({_goal_txt}), "
              f"deadhead {pct(wmtda.get('deadhead'))} (goal &le;{pct(TARGET_DEADHEAD)}). "
              f"{money(qb_ar.get('total31') if qb_ar else None)} is 31+ days overdue per QuickBooks "
              f"(X-Trux + X-Linx snapshot &mdash; see pg 12). "
              f"Safety: {swv('events', '24h')} events &amp; {swv('hos', '24h')} HOS violations &middot; last 24h.")
    if drag and drag.get("text"):
        legacy_bottom += f" {drag['text']}"
    bottom = _insights_bottom if _insights_bottom else legacy_bottom

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

    # Month-rollover banner: when MTD has just turned over and we've swapped
    # the MTD numbers for last month's totals, surface that clearly at the top
    # so a reader doesn't think the numbers are wrong.
    rollover_banner = ""
    if (alvys or {}).get("rollover"):
        lm_label = alvys.get("mtd_label", "last month")
        rollover_banner = (
            f"<div style='padding:8px 24px 0;'>"
            f"<div style='background:{WARNBG};border-left:4px solid {WARN};border-radius:6px;"
            f"padding:10px 14px;color:{INK};font-size:13px;'>"
            f"<b>Month rollover</b> &middot; only {pd.Timestamp.now().day} day(s) into the new month. "
            f"MTD tiles below show <b>{lm_label}</b> final numbers until enough loads accumulate."
            f"</div></div>")
    _mtd_label = (alvys or {}).get("mtd_label", "MTD")
    _entity_section = (f"Revenue / cost / margin by entity &middot; {_mtd_label}"
                       if _mtd_label != "MTD"
                       else "Revenue / cost / margin by entity &middot; MTD")

    # Action-item cards — derived from threshold breaches by
    # scorecard_insights.action_items(). Max 3. Renders as a 3-col row of
    # colored cards immediately under the Bottom Line bar.
    action_items_html = ""
    if _insights_actions:
        _kind_color = {"bad": (BAD, BADBG), "warn": (WARN, WARNBG),
                       "good": (GOOD, GOODBG)}
        _cards = []
        for sev, title, body in _insights_actions:
            fg, bg = _kind_color.get(sev, (MUTE, "#eef2f7"))
            _cards.append(
                f"<td width='33%' valign='top' style='padding:6px;'>"
                f"<div style='background:{bg};border-radius:10px;padding:14px 14px 12px;"
                f"border-left:4px solid {fg};'>"
                f"<div style='font-size:11px;letter-spacing:.5px;text-transform:uppercase;"
                f"color:{fg};font-weight:800;margin-bottom:6px;'>{title}</div>"
                f"<div style='font-size:13px;color:{INK};line-height:1.45;'>{body}</div>"
                f"</div></td>")
        # Pad to 3 cols so the row stays balanced
        while len(_cards) < 3:
            _cards.append("<td width='33%' style='padding:6px;'></td>")
        action_items_html = (
            f"<div style='padding:4px 18px 0;'>"
            f"<div style='font-size:11px;letter-spacing:.6px;text-transform:uppercase;"
            f"color:{MUTE};font-weight:800;padding:8px 6px 4px;'>Act today</div>"
            f"<table width='100%' cellpadding='0' cellspacing='0'>"
            f"<tr>{''.join(_cards)}</tr></table></div>")

    # Coaching cards — per-driver talk tracks tied to idle thresholds.
    coaching_html = ""
    if _insights_coaching:
        _cards = []
        for name_line, fact, talk in _insights_coaching:
            _cards.append(
                f"<td width='33%' valign='top' style='padding:6px;'>"
                f"<div style='background:{TILEBG};border:1px solid {LINE};"
                f"border-radius:10px;border-left:4px solid {ACCENT};"
                f"padding:14px 14px 12px;'>"
                f"<div style='font-size:11px;letter-spacing:.5px;text-transform:uppercase;"
                f"color:{INK};font-weight:800;margin-bottom:4px;'>{name_line}</div>"
                f"<div style='font-size:11px;color:{MUTE};margin-bottom:8px;'>{fact}</div>"
                f"<div style='font-size:12px;color:{INK};line-height:1.4;font-style:italic;'>"
                f"{talk}</div></div></td>")
        while len(_cards) < 3:
            _cards.append("<td width='33%' style='padding:6px;'></td>")
        coaching_html = (
            f"<div style='padding:4px 18px 0;'>"
            f"<div style='font-size:11px;letter-spacing:.6px;text-transform:uppercase;"
            f"color:{MUTE};font-weight:800;padding:8px 6px 4px;'>Coaching this week &middot; "
            f"derived from idle ranking</div>"
            f"<table width='100%' cellpadding='0' cellspacing='0'>"
            f"<tr>{''.join(_cards)}</tr></table></div>")

    return (f"{_header('Morning Executive Brief', 1, date_str)}"
            f"<div style='padding:18px 24px 4px;'>"
            f"<div style='background:#fafafa;border-left:4px solid {XFREIGHT_RED};padding:16px 20px;"
            f"color:{INK};font-size:13.5px;line-height:1.6;'>"
            f"<span style='color:{XFREIGHT_RED};font-weight:800;text-transform:uppercase;"
            f"font-size:10px;letter-spacing:1.5px;display:block;margin-bottom:6px;'>The bottom line</span>"
            f"{bottom}</div></div>"
            f"{rollover_banner}"
            f"{action_items_html}"
            f"{coaching_html}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"{warn_row}"
            f"{_section('XFreight Overview')}"
            f"<tr>{t1}</tr><tr>{t1b}</tr>"
            f"{_section(_entity_section)}"
            f"{_table(['Entity', 'Revenue', 'Cost', 'Margin', 'Margin %'], ['left', 'right', 'right', 'right', 'right'], entity_rows + entity_total)}"
            f"{mtd_note}"
            f"{_section('X-Trux Overview')}<tr>{xtrux_r1}</tr><tr>{xtrux_r2}</tr><tr>{xtrux_r3}</tr>"
            + (f"{_section('X-Trux Rate-per-Mile Goal &middot; cost-out')}<tr>{goal_tiles}</tr>{goal_note}"
               + (f"<tr>{goal_trend_row}</tr>" if goal_trend_row else "")
               if goal_tiles else "")
            + f"{_section('X-Linx Overview')}<tr>{xlinx_tiles}</tr>"
            + (f"{_section('AR reconciliation &mdash; QuickBooks vs Alvys &middot; X-Trux + X-Linx')}<tr>{recon_row}</tr>"
               f"{_brief(recon_note, recon['kind'])}"
               if recon_row else "")
            + (f"{_section('Alvys AR &mdash; aging by due date &middot; X-Trux + X-Linx open invoices')}<tr>{alvys_ar_row}</tr>"
               if alvys_ar_row else "")
            + f"{_section('Receivables &amp; payables &mdash; 6-month balance trend')}<tr>{recv_left}{ar_col_td}{ap_col_td}</tr>"
            + f"{_brief(ar_insight, 'bad' if ar_rising else 'good')}"
            + _qb_overdue_html
            + f"{_section('Safety &amp; compliance &mdash; 24h / 7d / MTD &middot; X-Trux / XFreight fleet')}<tr>{safety_tiles}</tr>"
            + f"{_section('Safety &amp; compliance &mdash; 6-month trend (MTD)')}<tr>{safety_charts}</tr>"
            + _safety_detail_tables(samsara)
            + f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            + f"{asof}Orange bar = current month (MTD, partial). Sources: Alvys Master 2026, QuickBooks, Samsara.</div>")


def _safety_detail_tables(samsara) -> str:
    """HOS violations / Safety events (last 7d) / Open DVIR defects /
    Coaching needs assigned tables. Rendered at the bottom of page 1."""
    detail = (samsara or {}).get("detail", {})
    acks_by_driver = (samsara or {}).get("coaching_acks", {}) or {}

    def _when(r) -> str:
        # Combine date + time for the 7-day windows so the reader knows what
        # day each violation/event landed on.
        return (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;"

    def _ack_after(driver: str, event_ts):
        """Return the latest matching ack timestamp (a UTC pd.Timestamp) if
        the driver signed off on a coaching session at or after the given
        event timestamp, else None."""
        if not driver or event_ts is None or pd.isna(event_ts):
            return None
        latest = None
        for ack_ts in acks_by_driver.get(driver.strip().lower(), []):
            if ack_ts >= event_ts and (latest is None or ack_ts > latest):
                latest = ack_ts
        return latest

    def _ack_cell(yes: bool) -> str:
        # &check; renders as a clean ✓ in both desktop email and WeasyPrint PDF.
        return "&check;" if yes else "&mdash;"

    # "Leave it on for 3 days after acknowledgment" — a driver stays on the
    # Coaching needs assigned list until they've signed, and then for this
    # many days after their signature before they drop off entirely.
    _ACK_KEEP_DAYS = 3
    _now_utc = pd.Timestamp.now(tz="UTC")

    hos_rows = "".join(
        _tr([r.get("driver name", ""), _when(r), r.get("violation type", ""), r.get("status", "")],
            ["left", "left", "left", "left"], [None, None, "bad", None])
        for r in detail.get("hos", []))

    event_rows = ""
    for r in detail.get("events", []):
        evt_ts = pd.to_datetime(
            (r.get("date", "") + " " + r.get("time", "")).strip(),
            errors="coerce", utc=True)
        acked = _ack_after(r.get("driver name", ""), evt_ts) is not None
        event_rows += _tr(
            [r.get("driver name", ""), r.get("unit", ""), _when(r),
             r.get("event type", ""), r.get("severity", ""), r.get("status", ""),
             _ack_cell(acked)],
            ["left", "left", "left", "left", "left", "left", "center"],
            [None, None, None, None,
             ("bad" if str(r.get("severity", "")).lower() == "high" else "warn"),
             None, ("good" if acked else "mute")])

    dvir_rows = "".join(
        _tr([r.get("unit", "&mdash;"), r.get("driver", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("defect", ""), r.get("defect type", ""), "Open"],
            ["left", "left", "left", "left", "left", "left"],
            [None, None, None, None, "warn", "bad"])
        for r in detail.get("dvir", []))

    # Coaching needs assigned — per-driver list over the last 7 days. Every
    # driver with any safety event in the window stays on the list; the
    # action column tells the safety manager whether to assign coaching now
    # (>= threshold) or just monitor (one-off).
    coaching_list = (samsara or {}).get("coaching_list") or []
    coach_rows = ""
    _seven_d_ago = _now_utc - pd.Timedelta(days=7)
    for c in coaching_list:
        n = c.get("events", 0)
        last_ts = pd.to_datetime(c.get("last", ""), errors="coerce", utc=True)
        is_coaching = n >= COACH_EVENT_THRESHOLD
        if is_coaching:
            # "Assign coaching": stays on the list until the driver signs,
            # then for _ACK_KEEP_DAYS more days as a closeout indicator.
            ack_ts = _ack_after(c.get("driver", ""), last_ts)
            if ack_ts is not None and (_now_utc - ack_ts).total_seconds() > _ACK_KEEP_DAYS * 86400:
                continue
            acked = ack_ts is not None
        else:
            # "Monitor": one-off events don't need driver acknowledgment —
            # roll off naturally after 7 days from the event itself. The Ack
            # column reads as N/A so it doesn't imply a missing signature.
            if pd.notna(last_ts) and last_ts < _seven_d_ago:
                continue
            acked = False
        action = "Assign coaching" if is_coaching else "Monitor"
        action_kind = "bad" if is_coaching else "warn"
        events_kind = "bad" if is_coaching else ("warn" if n > 0 else None)
        types_str = ", ".join(c.get("types") or [])[:60] or "&mdash;"
        ack_cell = _ack_cell(acked) if is_coaching else "n/a"
        ack_color = ("good" if acked else "mute") if is_coaching else "mute"
        coach_rows += _tr(
            [c.get("driver", ""), types_str, str(n), c.get("last", "") or "&mdash;",
             action, ack_cell],
            ["left", "left", "right", "left", "left", "center"],
            [None, None, events_kind, None, action_kind, ack_color],
        )

    return (
        f"{_section('HOS violations &mdash; last 7 days')}"
        f"{_table(['Driver', 'Reported', 'Violation', 'Status'], ['left', 'left', 'left', 'left'], hos_rows)}"
        f"{_section('Safety events &mdash; last 7 days')}"
        f"{_table(['Driver', 'Unit', 'Reported', 'Event', 'Severity', 'Status', 'Ack'], ['left', 'left', 'left', 'left', 'left', 'left', 'center'], event_rows)}"
        f"{_section('DVIR defects (open) &mdash; all unresolved')}"
        f"{_table(['Unit', 'Driver', 'Reported', 'Defect', 'Type', 'Status'], ['left', 'left', 'left', 'left', 'left', 'left'], dvir_rows)}"
        f"{_section('Coaching needs assigned &mdash; drivers with safety events &middot; last 7 days')}"
        f"{_table(['Driver', 'Event Types', 'Events (7d)', 'Last Event', 'Action', 'Ack'], ['left', 'left', 'right', 'left', 'left', 'center'], coach_rows)}"
    )


def build_page2(samsara, date_str) -> str:
    # Driver safety scores table (moved here from the Fleet Operations page
    # so all safety content lives on one page). All drivers ranked
    # worst-to-best; lowest scores get the red treatment so they pop.
    fleet = (samsara or {}).get("fleet", {}) or {}
    scores_all = fleet.get("scores_all") or []
    def _score_kind(s: int) -> str:
        if s < 90:
            return "bad"
        if s < 100:
            return "warn"
        return "good"
    def _evt(v):
        return "&ndash;" if v is None else str(v)
    def _evt_kind(v):
        if v is None or v == 0:
            return None
        return "bad"
    def _spd_cell(r):
        """Render speeding as % of drive time when available, else minutes."""
        pct_v = r.get("speed_pct")
        mins  = r.get("speed_min")
        if _isnum(pct_v):
            return f"{pct_v:.1f}%"
        if _isnum(mins):
            return f"{mins} min"
        return "&ndash;"
    def _spd_kind(r):
        pct_v = r.get("speed_pct")
        if _isnum(pct_v):
            if pct_v == 0:
                return None
            return "bad" if pct_v >= 5 else ("warn" if pct_v >= 1 else None)
        mins = r.get("speed_min")
        if mins is None or mins == 0:
            return None
        return "bad" if mins >= 60 else "warn"
    if scores_all:
        # Header reflects what we're showing: when % of drive time is available
        # for ANY driver, sub-label as "% drive time"; otherwise it's minutes.
        _any_pct = any(_isnum(r.get("speed_pct")) for r in scores_all)
        _spd_hdr = "Speed Over Limit (% drive time)" if _any_pct else "Speed Over Limit"
        s_headers = ["Driver", "Score", "Harsh accel", "Harsh brake",
                     "Harsh turn", _spd_hdr, "Crashes"]
        body = ""
        for r in scores_all:
            body += _tr(
                [r["driver"], str(r["score"]),
                 _evt(r.get("harsh_accel")), _evt(r.get("harsh_brake")),
                 _evt(r.get("harsh_turn")), _spd_cell(r),
                 _evt(r.get("crashes"))],
                ["left", "right", "right", "right", "right", "right", "right"],
                [None, _score_kind(r["score"]),
                 _evt_kind(r.get("harsh_accel")), _evt_kind(r.get("harsh_brake")),
                 _evt_kind(r.get("harsh_turn")), _spd_kind(r),
                 _evt_kind(r.get("crashes"))])
        score_all_tbl = _table(s_headers,
                               ["left", "right", "right", "right", "right",
                                "right", "right"], body)
    else:
        score_all_tbl = (f"<tr><td colspan='7' style='padding:12px 8px;"
                         f"color:{MUTE};font-size:12.5px;'>(no data)</td></tr>")
    total_d = max(1, len(scores_all))

    # --- Coaching & Training tiles -------------------------------------------
    coaching_info  = (samsara or {}).get("coaching_sessions", {})
    training_info  = (samsara or {}).get("training", {})
    self_pd        = coaching_info.get("self_past_due", [])
    mgr_pd         = coaching_info.get("manager_past_due", [])
    train_pd       = training_info.get("past_due", [])
    coaching_avail = coaching_info.get("available", False)
    training_avail = training_info.get("available", False)

    def _ct_tile(label, count, sub):
        col = BAD if count > 0 else GOOD
        return (f"<td class='tile' width='33%' style='padding:6px;' valign='top'>"
                f"<div style='background:{TILEBG};border:1px solid {LINE};border-radius:10px;"
                f"padding:14px 14px 12px;'>"
                f"<div style='font-size:11px;letter-spacing:.6px;text-transform:uppercase;"
                f"color:{MUTE};font-weight:700;'>{label}</div>"
                f"<div style='font-size:32px;font-weight:800;color:{col};"
                f"margin:8px 0 6px;line-height:1;'>{count}</div>"
                f"<div style='font-size:12px;color:{MUTE};'>{sub}</div>"
                f"</div></td>")

    def _coaching_table_rows():
        all_rec = [(r, "Self-coaching") for r in self_pd] + [(r, "Manager-led") for r in mgr_pd]
        rows = ""
        for r, kind in sorted(all_rec, key=lambda x: -x[0]["days_overdue"]):
            beh = (r.get("behaviors") or "")[:55]
            try:
                assigned = pd.to_datetime(r.get("assigned_at", ""), utc=True).strftime("%b %d")
            except Exception:
                assigned = r.get("assigned_at", "") or "&ndash;"
            rows += _tr(
                [r["driver"], kind, assigned, r["due_at"], f"{r['days_overdue']}d", beh or "&ndash;"],
                ["left", "left", "left", "left", "right", "left"],
                [None, None, None, "warn", "bad", None])
        return rows

    def _training_table_rows():
        rows = ""
        for r in sorted(train_pd, key=lambda x: -x["days_overdue"]):
            course = (r.get("course") or "")[:50]
            try:
                assigned = pd.to_datetime(r.get("assigned_at", ""), utc=True).strftime("%b %d")
            except Exception:
                assigned = r.get("assigned_at", "") or "&ndash;"
            rows += _tr(
                [r["driver"], course or "&ndash;", assigned, r["due_at"], f"{r['days_overdue']}d"],
                ["left", "left", "left", "left", "right"],
                [None, None, None, "warn", "bad"])
        return rows

    coaching_section = ""
    if coaching_avail or training_avail:
        coaching_section = (
            f"<tr>"
            f"{_ct_tile('Self-Coaching Past Due', len(self_pd), 'sessions overdue')}"
            f"{_ct_tile('Manager Coaching Past Due', len(mgr_pd), 'sessions overdue')}"
            f"{_ct_tile('Training Assignments Past Due', len(train_pd), 'assignments overdue')}"
            f"</tr>"
        )
        if coaching_avail:
            _c_hdr = ['Driver', 'Type', 'Assigned', 'Due Date', 'Days Past Due', 'Behaviors']
            _c_al  = ['left', 'left', 'left', 'left', 'right', 'left']
            _c_tbl = _table(_c_hdr, _c_al, _coaching_table_rows(), span=4)
            coaching_section += (
                f"{_section('Coaching sessions past due &mdash; self &amp; manager-led', span=4)}"
                f"{_c_tbl}"
            )
        if training_avail:
            _t_hdr = ['Driver', 'Course', 'Assigned', 'Due Date', 'Days Past Due']
            _t_al  = ['left', 'left', 'left', 'left', 'right']
            _t_tbl = _table(_t_hdr, _t_al, _training_table_rows(), span=4)
            coaching_section += (
                f"{_section('Training assignments past due', span=4)}"
                f"{_t_tbl}"
            )

    # --- Speeding section — drivers with any time over posted speed limit ------
    # Two columns: 6-month % of drive time, and current-MTD %. Action threshold
    # uses the 6-month figure (more stable signal); MTD trends the recent move.
    speeders_ranked = [r for r in reversed(scores_all)  # reversed = highest speed_min first
                       if r.get("speed_min") is not None]
    speeders_ranked.sort(key=lambda r: -(r.get("speed_pct") if _isnum(r.get("speed_pct")) else (r["speed_min"] or 0) / 1000.0))
    spd_count = sum(1 for r in speeders_ranked if (r.get("speed_min") or 0) > 0)

    def _spd_cell(pct_v, sm):
        if _isnum(pct_v):
            return f"{pct_v:.1f}%"
        if sm:
            return f"{sm} min"
        return "&mdash;"

    def _spd_kind(pct_v, sm):
        if _isnum(pct_v):
            if pct_v >= 5: return "bad"
            if pct_v >= 1: return "warn"
            return None
        if sm and sm >= 60: return "bad"
        if sm: return "warn"
        return None

    def _spd_comment(pct_6mo, pct_3mo, pct_mtd):
        """Plain-language comment per the speeding-threshold rubric.

        Base message uses the PEAK of the three windows so a chronic 6mo problem
        and an acute MTD spike both surface. A trend suggestion is layered on:
        falling fast / improving / spiking / trending worse / no improvement.
        """
        pcts = [p for p in (pct_6mo, pct_3mo, pct_mtd) if _isnum(p)]
        peak = max(pcts) if pcts else None
        base = ""
        if _isnum(peak):
            if peak >= 3.0:
                base = "STOP this driver now"
            elif peak >= 2.5:
                base = "Need to sit down with this driver &mdash; they have a problem"
            elif peak >= 2.25:
                base = "This is too fast"
            elif peak >= 2.0:
                base = "Driver needs a conversation"
            elif peak >= 1.75:
                base = "Where is the fire?"
            elif peak >= 1.5:
                base = "We have a problem with speed"
            elif peak >= 1.25:
                base = "Watch this driver"
        trend = ""
        if _isnum(pct_6mo) and _isnum(pct_mtd) and pct_6mo >= 0:
            # MTD spike vs the longer windows — recent jump, address immediately.
            longer = max(pct_6mo, pct_3mo) if _isnum(pct_3mo) else pct_6mo
            if _isnum(longer) and pct_mtd - longer >= 2.0:
                trend = "spiking &mdash; recent jump, address now"
            elif pct_6mo >= 1.0 and pct_mtd <= pct_6mo * 0.3:
                trend = "falling fast &mdash; keep it up"
            elif pct_6mo >= 1.0 and pct_mtd <= pct_6mo * 0.6:
                trend = "improving &mdash; keep it up"
            elif pct_mtd - pct_6mo >= 1.0:
                trend = "trending worse"
            elif base and pct_mtd >= pct_6mo - 0.1:
                trend = "no improvement &mdash; requires action"
        if base and trend:
            return f"{base}. {trend}."
        return base or trend

    def _spd_comment_kind(comment, pct_6mo, pct_3mo, pct_mtd):
        if not comment:
            return None
        pcts = [p for p in (pct_6mo, pct_3mo, pct_mtd) if _isnum(p)]
        peak = max(pcts) if pcts else None
        if _isnum(peak) and peak >= 2.25:
            return "bad"
        if "spiking" in comment or "trending worse" in comment:
            return "bad"
        if ("falling fast" in comment or "improving" in comment) and _isnum(peak) and peak < 1.5:
            return "good"
        return "warn"

    def _spd_rows():
        rows = ""
        for r in speeders_ranked:
            sm = r.get("speed_min") or 0
            if sm == 0:
                continue
            pct_6mo = r.get("speed_pct")
            pct_3mo = r.get("speed_pct_3mo")
            pct_mtd = r.get("speed_pct_mtd")
            comment = _spd_comment(pct_6mo, pct_3mo, pct_mtd)
            comment_kind = _spd_comment_kind(comment, pct_6mo, pct_3mo, pct_mtd)
            rows += _tr(
                [r["driver"], str(r["score"]),
                 _spd_cell(pct_6mo, sm), _spd_cell(pct_3mo, None),
                 _spd_cell(pct_mtd, None), comment or "&mdash;"],
                ["left", "right", "right", "right", "right", "left"],
                [None, _score_kind(r["score"]),
                 _spd_kind(pct_6mo, sm), _spd_kind(pct_3mo, None),
                 _spd_kind(pct_mtd, None), comment_kind])
        return rows

    _spd_tbl = _table(
        ["Driver", "Safety Score",
         "Speed Over Limit (6 mo)", "Speed Over Limit (3 mo)",
         "Speed Over Limit (MTD)", "Comments"],
        ["left", "right", "right", "right", "right", "left"],
        _spd_rows(), span=4,
    )


    return (f"{_header('Safety &amp; Compliance Detail &mdash; last 24h &middot; X-Trux / XFreight fleet', 3, date_str, section='SAFETY')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"{_section(f'Speed over posted limit &middot; {spd_count} of {total_d} drivers &middot; 6-month period')}"
            f"{_spd_tbl}"
            f"{coaching_section}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"24h sections: Samsara (SafetyEvents, HOS_Violations, DVIR_Defects). "
            f"Speed Over Limit = time-over-posted-limit &divide; total drive time, shown as % "
            f"when both fields are available (&ge;5% flagged for coaching, 1&ndash;5% monitored); "
            f"falls back to minutes over limit when drive time isn&rsquo;t exposed. "
            f"Coaching &amp; training: Samsara Coaching Sessions / "
            f"Training Assignments (past-due only; tiles hidden when module not enabled).</div>")


def build_page2b(samsara, date_str, pg: int = 4) -> str:
    """Driver safety scores — own page (split from build_page2 so the Speed
    Over Limit table and the per-driver score table don't share a single page)."""
    fleet = (samsara or {}).get("fleet", {}) or {}
    scores_all = fleet.get("scores_all") or []

    def _score_kind(s: int) -> str:
        if s < 90:
            return "bad"
        if s < 100:
            return "warn"
        return "good"

    def _evt(v):
        return "&ndash;" if v is None else str(v)

    def _evt_kind(v):
        if v is None or v == 0:
            return None
        return "bad"

    def _spd_cell(r):
        pct_v = r.get("speed_pct")
        mins = r.get("speed_min")
        if _isnum(pct_v):
            return f"{pct_v:.1f}%"
        if _isnum(mins):
            return f"{mins} min"
        return "&ndash;"

    def _spd_kind(r):
        pct_v = r.get("speed_pct")
        if _isnum(pct_v):
            if pct_v == 0:
                return None
            return "bad" if pct_v >= 5 else ("warn" if pct_v >= 1 else None)
        mins = r.get("speed_min")
        if mins is None or mins == 0:
            return None
        return "bad" if mins >= 60 else "warn"

    if scores_all:
        _any_pct = any(_isnum(r.get("speed_pct")) for r in scores_all)
        _spd_hdr = "Speed Over Limit (% drive time)" if _any_pct else "Speed Over Limit"
        s_headers = ["Driver", "Score", "Harsh accel", "Harsh brake",
                     "Harsh turn", _spd_hdr, "Crashes"]
        body = ""
        for r in scores_all:
            body += _tr(
                [r["driver"], str(r["score"]),
                 _evt(r.get("harsh_accel")), _evt(r.get("harsh_brake")),
                 _evt(r.get("harsh_turn")), _spd_cell(r),
                 _evt(r.get("crashes"))],
                ["left", "right", "right", "right", "right", "right", "right"],
                [None, _score_kind(r["score"]),
                 _evt_kind(r.get("harsh_accel")), _evt_kind(r.get("harsh_brake")),
                 _evt_kind(r.get("harsh_turn")), _spd_kind(r),
                 _evt_kind(r.get("crashes"))])
        score_all_tbl = _table(s_headers,
                               ["left", "right", "right", "right", "right",
                                "right", "right"], body)
    else:
        score_all_tbl = (f"<tr><td colspan='7' style='padding:12px 8px;"
                         f"color:{MUTE};font-size:12.5px;'>(no data)</td></tr>")

    return (f"{_header('Driver Safety Scores &mdash; all drivers, worst to best', pg, date_str, section='SAFETY')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"{_section('Driver safety scores &middot; all drivers, worst to best &middot; last 6 months')}"
            f"{score_all_tbl}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Source: Samsara Driver Safety Scores (per-driver composite, last 6 months). "
            f"Lower score = worse; component event counts (harsh accel/brake/turn, "
            f"crashes) are the inputs that drove it.</div>")


def build_page_fleet(samsara, date_str, customer_rpm=None) -> str:
    """Page 8: Fleet Operations — MPG and speeding. Idle detail is its own
    page (build_page_idle, pg 9); driver safety scores live on the Safety
    Scores page (build_page2b, pg 4)."""
    fleet = (samsara or {}).get("fleet", {}) or {}
    mpg_rows = fleet.get("mpg") or []

    # Top tiles — fleet-wide summary numbers.
    fleet_mpg = fleet.get("fleet_mpg")
    fleet_score = fleet.get("fleet_score")
    fleet_idle = fleet.get("fleet_idle_hours")
    fleet_miles = fleet.get("fleet_miles")
    tiles = (
        _tile("Fleet MPG", (f"{fleet_mpg:.2f}" if _isnum(fleet_mpg) else "n/a"),
              _pill("MTD (Based on Samsara)", "mute"))
        + _tile("Fleet miles &middot; MTD", num(fleet_miles),
                _pill("MTD (Based on Samsara)", "mute"))
        + _tile("Fleet idle hours &middot; 5 wks", num(fleet_idle), _pill("detail on pg 9", "mute"))
        + _tile("Fleet avg safety score",
                (f"{fleet_score:.0f}" if _isnum(fleet_score) else "n/a"),
                _pill("0&ndash;100, higher better", "mute"))
    )

    # Top 5 MPG (best) — the highlights, plus a bottom-5 table further down.
    top5_mpg = mpg_rows[:5]
    bot5_mpg = list(reversed(mpg_rows[-5:])) if len(mpg_rows) >= 5 else []
    mpg_headers = ["Truck", "Driver", "MPG", "Miles", "Gallons"]
    mpg_aligns = ["left", "left", "right", "right", "right"]

    def _mpg_row(r, mpg_kind: str | None) -> str:
        return _tr([r["unit"], r.get("driver") or "&mdash;",
                    f"{r['mpg']:.2f}", num(r["miles"]), f"{r['gallons']:.0f}"],
                   mpg_aligns, [None, None, mpg_kind, None, None])

    mpg_top_tbl = (_table(mpg_headers, mpg_aligns,
                          "".join(_mpg_row(r, "good") for r in top5_mpg))
                   if top5_mpg
                   else f"<tr><td colspan='5' style='padding:12px 8px;color:{MUTE};font-size:12.5px;'>(no data)</td></tr>")
    mpg_bot_tbl = (_table(mpg_headers, mpg_aligns,
                          "".join(_mpg_row(r, "bad") for r in bot5_mpg))
                   if bot5_mpg
                   else f"<tr><td colspan='5' style='padding:12px 8px;color:{MUTE};font-size:12.5px;'>(no data)</td></tr>")

    return (f"{_header('Fleet Operations &mdash; MPG / Speeding', 8, date_str, section='OPERATIONAL')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Best MPG &middot; top 5 trucks (MTD &middot; Based on Samsara)')}"
            f"{mpg_top_tbl}"
            f"{_section('Worst MPG &middot; bottom 5 trucks (MTD &middot; Based on Samsara)')}"
            f"{mpg_bot_tbl}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Source: Samsara Trips (MPG). "
            f"Per-driver speed-over-limit % and the speeder ranking are on "
            f"the Driver Safety Scores page (pg 4); "
            f"idle detail is on the Fleet Idle page (pg 9).</div>")


def build_page_idle(samsara, date_str, avg_fuel_price: float | None = None) -> str:
    """Page 4: Fleet Idle — every truck ranked worst-to-best by average idle
    hours per week, with a 5-settlement-week breakdown (Wed 3pm CT → Wed
    2:59pm CT, current week tinted), idle %, estimated idle gallons, and MPG.
    Split out of Fleet Operations so the full fleet fits on its own page."""
    fleet = (samsara or {}).get("fleet", {}) or {}
    idle_rows = fleet.get("idle") or []
    fleet_idle = fleet.get("fleet_idle_hours")

    # 5 settlement weeks; current tinted. Avg / wk averages the 4 complete
    # weeks (excludes the partial current week).
    idle_labels = fleet.get("idle_labels") or ["W1", "W2", "W3", "W4", "Current"]
    n_weeks = len(idle_labels)
    cur_idx = n_weeks - 1
    complete_weeks = n_weeks - 1

    # Summary tiles for the page.
    n_trucks = len(idle_rows)
    total_idle = sum((r.get("idle_hours") or 0) for r in idle_rows)
    total_gal = sum((r.get("idle_gallons") or 0) for r in idle_rows)
    worst = idle_rows[0] if idle_rows else None
    # Idle cost: prefer real Alvys Discount PPU; fall back to $4.00/gal estimate
    _fuel_price = avg_fuel_price if _isnum(avg_fuel_price) and avg_fuel_price > 0 else 4.00
    _fuel_src = f"${_fuel_price:.3f}/gal Alvys avg" if (_isnum(avg_fuel_price) and avg_fuel_price > 0) else "$4.00/gal est."
    total_cost = total_gal * _fuel_price
    worst_cost = (worst.get("idle_gallons") or 0) * _fuel_price if worst else 0
    tiles = (
        _tile("Trucks ranked", num(n_trucks), _pill("worst-to-best by avg / wk", "mute"))
        + _tile("Fleet idle hours", num(fleet_idle if _isnum(fleet_idle) else total_idle),
                _pill("last 5 settlement weeks", "mute"))
        + _tile("Idle cost &middot; est.", (f"${total_cost:,.0f}" if total_gal else "n/a"),
                _pill(f"0.8 gph &times; {_fuel_src}", "mute"))
        + _tile("Worst idler", (worst["unit"] if worst else "n/a"),
                _pill((f"{worst['idle_hours']:.0f} hrs &middot; ${worst_cost:,.0f} est." if worst else "&mdash;"),
                      "bad" if worst else "mute"))
    )

    def _icell(text, al="right", cur=False, bold=False):
        bg = f"background:{ACCENTBG};" if cur else ""
        return (f"<td align='{al}' style='padding:8px 8px;font-size:12.5px;color:{INK};"
                f"font-weight:{'700' if bold else '400'};border-bottom:1px solid {LINE};{bg}'>{text}</td>")

    def _ihcell(text, al="right", cur=False):
        bg = ACCENTBG if cur else TILEBG
        fg = ACCENT if cur else MUTE
        return (f"<td align='{al}' style='padding:8px 8px;font-size:10px;text-transform:uppercase;"
                f"letter-spacing:.4px;color:{fg};font-weight:700;background:{bg};border-bottom:1px solid {LINE};'>{text}</td>")

    if idle_rows:
        idle_head = ("<tr>"
                     + _ihcell("Truck", "left")
                     + _ihcell("Driver", "left")
                     + "".join(_ihcell(idle_labels[k], "right", cur=(k == cur_idx)) for k in range(n_weeks))
                     + _ihcell("Total", "right")
                     + _ihcell("Avg / wk", "right")
                     + _ihcell("Avg / wk $", "right")
                     + _ihcell("Idle %", "right")
                     + _ihcell("Idle Gal", "right")
                     + _ihcell("Idle $", "right")
                     + _ihcell("MPG", "right")
                     + "</tr>")
        idle_body = ""
        for r in idle_rows:
            weeks = r.get("weeks_idle") or [0] * n_weeks
            avg_wk = r.get("avg_wk", (sum(weeks[:complete_weeks]) / complete_weeks) if complete_weeks else 0)
            wk_cells = "".join(
                _icell(f"{weeks[k]:.1f}" if weeks[k] else "&ndash;", "right", cur=(k == cur_idx))
                for k in range(n_weeks))
            pct_txt = f"{r['idle_pct']*100:.0f}%" if r.get("idle_pct") else "n/a"
            pct_style = f"color:{WARN};font-weight:700;"
            pct_cell = (f"<td align='right' style='padding:8px 8px;font-size:12.5px;{pct_style}"
                        f"border-bottom:1px solid {LINE};'>{pct_txt}</td>")
            total_style = f"color:{BAD};font-weight:700;"
            total_cell = (f"<td align='right' style='padding:8px 8px;font-size:12.5px;{total_style}"
                          f"border-bottom:1px solid {LINE};'>{r['idle_hours']:.1f}</td>")
            mpg_val = r.get("mpg")
            mpg_txt = f"{mpg_val:.2f}" if _isnum(mpg_val) else "&ndash;"
            ig_val = r.get("idle_gallons")
            ig_txt = f"{ig_val:.0f}" if _isnum(ig_val) and ig_val > 0 else "&ndash;"
            ig_style = f"color:{BAD};font-weight:700;" if _isnum(ig_val) and ig_val > 0 else ""
            ig_cell = (f"<td align='right' style='padding:8px 8px;font-size:12.5px;{ig_style}"
                       f"border-bottom:1px solid {LINE};'>{ig_txt}</td>")
            # Approx $ cost = idle gallons × fuel price (total across 5 wks, and per week avg)
            total_cost_val = (ig_val * _fuel_price) if (_isnum(ig_val) and ig_val > 0) else None
            wk_gal_val = avg_wk * 0.8 if _isnum(avg_wk) else None
            wk_cost_val = (wk_gal_val * _fuel_price) if (_isnum(wk_gal_val) and wk_gal_val > 0) else None
            tc_txt = f"${total_cost_val:,.0f}" if _isnum(total_cost_val) else "&ndash;"
            wc_txt = f"${wk_cost_val:,.0f}" if _isnum(wk_cost_val) else "&ndash;"
            cost_style = f"color:{BAD};font-weight:700;"
            tc_cell = (f"<td align='right' style='padding:8px 8px;font-size:12.5px;"
                       f"{cost_style if _isnum(total_cost_val) else ''}border-bottom:1px solid {LINE};'>{tc_txt}</td>")
            wc_cell = (f"<td align='right' style='padding:8px 8px;font-size:12.5px;"
                       f"{cost_style if _isnum(wk_cost_val) else ''}border-bottom:1px solid {LINE};'>{wc_txt}</td>")
            idle_body += ("<tr>"
                          + _icell(r["unit"], "left")
                          + _icell(r.get("driver") or "&mdash;", "left")
                          + wk_cells
                          + total_cell
                          + _icell(f"{avg_wk:.1f}", "right")
                          + wc_cell
                          + pct_cell
                          + ig_cell
                          + tc_cell
                          + _icell(mpg_txt, "right")
                          + "</tr>")
        idle_tbl = (f"<tr><td colspan='4' class='scroll-wide' style='padding:0 6px;'>"
                    f"<table width='100%' cellpadding='0' cellspacing='0' "
                    f"style='border:1px solid {LINE};border-radius:8px;border-collapse:separate;overflow:hidden;'>"
                    f"{idle_head}{idle_body}</table></td></tr>")
    else:
        idle_tbl = f"<tr><td colspan='4' style='padding:12px 8px;color:{MUTE};font-size:12.5px;'>(no data)</td></tr>"

    _cost_note = (f"Idle cost = idle gallons &times; {_fuel_src} (Alvys Discount PPU 60-day avg). "
                  if (_isnum(avg_fuel_price) and avg_fuel_price > 0)
                  else "Idle cost = idle gallons &times; $4.00/gal placeholder (set Alvys Fuel data for live price). ")
    return (f"{_header('Fleet Idle &mdash; All Trucks by Settlement Week', 9, date_str, section='OPERATIONAL')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Idlers &middot; all trucks ranked worst-to-best by avg / wk &middot; current week tinted')}"
            f"{idle_tbl}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Source: Samsara engine-state history (idle, last 5 settlement weeks; "
            f"idle gallons = idle_hours &times; 0.8 gph fleet-average heuristic). "
            f"{_cost_note}"
            f"Avg / wk averages the 4 complete weeks (excludes the partial current week).</div>")


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
    return (f"{_header('Accounts Receivable &mdash; Overdue (31+ days)', 8, date_str, section='ACCOUNTING')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{_tile('31&ndash;60 days', money(totals.get('31&ndash;60')), _pill('watch', 'warn'))}"
            f"{_tile('61&ndash;90 days', money(totals.get('61&ndash;90')), _pill('escalate', 'warn'))}"
            f"{_tile('91+ days', money(totals.get('91+')), _pill('collections', 'bad'))}"
            f"{_tile('Total 31+', money(total31), _pill('overdue', 'bad'))}</tr>"
            f"{_section('Overdue invoices (31+ days) by customer &middot; X-Trux + X-Linx &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'Invoice', 'Inv date', 'Due date', 'Amount', 'Bucket'], ['left', 'left', 'left', 'left', 'right', 'left'], rows + total_row)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Current and 1&ndash;30 day balances omitted by request. X-Trux Inc + X-Linx Inc only. "
            f"Source: QuickBooks A/R Aging Detail.</div>")


def build_page4(mileage, date_str) -> str:
    m = mileage or {}
    labels = (m.get("labels") or ["", "", "", ""])
    rows = m.get("rows") or []
    week_totals = m.get("week_totals") or [0] * SETTLEMENT_WEEKS
    cur = SETTLEMENT_WEEKS - 1

    # Drivers below target (current settlement week only)
    _below_tgt = sum(1 for r in rows if 0 < r["weeks"][cur] < DRIVER_TARGET_MILES)
    _below_kind = "bad" if _below_tgt >= 3 else ("warn" if _below_tgt >= 1 else "good")
    tiles = (_tile("Drivers &middot; this week", num(m.get("drivers_this_week")),
                   _pill("settled legs", "mute")
                   + " &middot; "
                   + _pill(f"avg {num(m.get('avg_per_driver'))} mi / driver", "mute"))
             + _tile("Miles &middot; this week", num(m.get("miles_this_week")), _pill(labels[cur] or "current", "mute"))
             + _tile("Miles &middot; last week", num(m.get("miles_last_week")), _pill(labels[cur - 1] or "prior", "mute"))
             + _tile("Drivers below target &middot; this week", num(_below_tgt),
                     _pill(f"&lt; {num(DRIVER_TARGET_MILES)} mi this week", _below_kind)))

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

    # Avg / wk excludes the current (partial) week so it reflects a true
    # full-week run-rate rather than getting dragged low mid-week.
    complete_weeks = SETTLEMENT_WEEKS - 1
    body = ""
    for r in rows:
        wk_cells = "".join(
            mcell(num(r["weeks"][k]) if r["weeks"][k] else "&ndash;", "right", cur=(k == cur))
            for k in range(SETTLEMENT_WEEKS))
        avg_wk = ((r["total"] - r["weeks"][cur]) / complete_weeks) if complete_weeks else 0
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
        # Total row's "Avg / wk" cell mirrors the per-row formula: full-week
        # run-rate that excludes the partial current week.
        gt = m.get("grand_total") or 0
        grand_avg = ((gt - week_totals[cur]) / complete_weeks) if complete_weeks else 0
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

    return (f"{_header('Driver Mileage by Settlement Week &mdash; X-Trux / XFreight fleet', 7, date_str, section='OPERATIONAL')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Driver miles by settlement week &middot; last ' + str(SETTLEMENT_WEEKS) + ' weeks')}"
            f"{table}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Settlement weeks run Wed 3:00 PM &rarr; the following Wed 2:59 PM (America/Chicago); the current "
            f"week is tinted. Avg / wk excludes the current (partial) week. Each trip leg is credited to its Driver 1 / Truck / miles and bucketed by its own "
            f"actual delivery (last stop arrival). Cancelled and not-yet-delivered legs are excluded; asset fleet "
            f"only. Source: Alvys API (Trips, via the pipeline file).</div>")


def build_page5(uninv, alvys_ar, date_str) -> str:
    u = uninv or {}
    rows_data = u.get("rows", [])
    od = u.get("oldest_days")
    a = alvys_ar or {}
    custs = a.get("d91plus_customers") or []
    n_loads = sum(c["loads"] for c in custs)

    uninv_tiles = (_tile("Loads delivered, not invoiced", num(u.get("count")), _pill("X-Trux + X-Linx", "mute"))
                   + _tile("Un-invoiced revenue", money(u.get("total_revenue")), _pill("to bill", "warn"))
                   + _tile("Oldest delivered", (num(od) + " days" if _isnum(od) else "n/a"), _pill("since delivery", "bad"))
                   + "<td class='tile-empty' width='25%' style='padding:6px;'></td>")
    uninv_body = ""
    for r in rows_data:
        dd = r["days"] or 0
        k = "bad" if dd >= 14 else ("warn" if dd >= 7 else None)
        days_txt = str(r["days"]) if r["days"] is not None else "&ndash;"
        cust = r["customer"] or "&mdash; (no customer name)"
        uninv_body += _tr([r["load"], cust, r["entity"], r["delivered"], days_txt, money(r["revenue"])],
                          ["left", "left", "left", "left", "right", "right"],
                          [None, None, None, None, k, None])
    shown, count = u.get("shown", len(rows_data)), u.get("count", 0)
    uninv_more = (f"<tr><td colspan='6' style='padding:8px;color:{MUTE};font-size:11px;'>"
                  f"Showing the {shown} oldest of {count} loads.</td></tr>") if count > shown else ""

    ar_tiles = (_tile("90+ days AR", money(a.get("d91plus")), _pill("X-Trux + X-Linx", "bad"))
                + _tile("Customers 90+", num(len(custs)), _pill("over 90 days", "bad"))
                + _tile("Loads 90+", num(n_loads), _pill("open invoices", "mute"))
                + "<td class='tile-empty' width='25%' style='padding:6px;'></td>")
    ar_body = ""
    for c in custs:
        ar_body += _tr([c["customer"] or "&mdash; (no customer name)", str(c["loads"]),
                        str(c["oldest_days"]), money(c["amount"])],
                       ["left", "right", "right", "right"], [None, None, "bad", "bad"])

    return (f"{_header('Alvys Accounting &mdash; Un-invoiced &amp; Aged AR', 9, date_str, section='ACCOUNTING')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{uninv_tiles}</tr>"
            f"{_section('Delivered loads awaiting invoice &middot; oldest first &middot; as of ' + date_str)}"
            f"{_table(['Load #', 'Customer', 'Entity', 'Delivered', 'Days', 'Revenue'], ['left', 'left', 'left', 'left', 'right', 'right'], uninv_body + uninv_more)}"
            f"<tr>{ar_tiles}</tr>"
            f"{_section('Customers with open balances over 90 days &middot; by total &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'Loads', 'Oldest (days)', 'Amount'], ['left', 'right', 'right', 'right'], ar_body)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Top: delivered loads with no Invoiced Date &mdash; the un-billed revenue behind most of the "
            f"QuickBooks-vs-Alvys AR gap. &lsquo;Delivered&rsquo; is the actual last-stop arrival "
            f"(Scheduled Delivery if arrival is missing). "
            f"Bottom: open invoiced balances aged &gt;90 days past the Customer Due Date (Invoiced Date + 30d if none); "
            f"many may already be paid in QuickBooks &mdash; see the page-1 AR reconciliation note. "
            f"X-Trux Inc + X-Linx Inc, JW Logistics excluded. Source: Alvys API (Loads, via the pipeline file).</div>")


def build_page_ar_accounting(qb_ar, uninv, alvys_ar, date_str) -> str:
    """Page 9 — QB AR Overdue (31+) combined with Alvys Un-invoiced & Aged AR."""
    # -- QB AR Overdue section --
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
    qb_tiles = (f"<tr>{_tile('31&ndash;60 days', money(totals.get('31&ndash;60')), _pill('watch', 'warn'))}"
                f"{_tile('61&ndash;90 days', money(totals.get('61&ndash;90')), _pill('escalate', 'warn'))}"
                f"{_tile('91+ days', money(totals.get('91+')), _pill('collections', 'bad'))}"
                f"{_tile('Total 31+', money(total31), _pill('overdue', 'bad'))}</tr>")

    # -- Alvys Accounting section --
    u = uninv or {}
    rows_data = u.get("rows", [])
    od = u.get("oldest_days")
    a = alvys_ar or {}
    custs = a.get("d91plus_customers") or []
    n_loads = sum(c["loads"] for c in custs)

    uninv_tiles = (_tile("Loads delivered, not invoiced", num(u.get("count")), _pill("X-Trux + X-Linx", "mute"))
                   + _tile("Un-invoiced revenue", money(u.get("total_revenue")), _pill("to bill", "warn"))
                   + _tile("Oldest delivered", (num(od) + " days" if _isnum(od) else "n/a"), _pill("since delivery", "bad"))
                   + "<td class='tile-empty' width='25%' style='padding:6px;'></td>")
    uninv_body = ""
    for r in rows_data:
        dd = r["days"] or 0
        k = "bad" if dd >= 14 else ("warn" if dd >= 7 else None)
        days_txt = str(r["days"]) if r["days"] is not None else "&ndash;"
        cust = r["customer"] or "&mdash; (no customer name)"
        uninv_body += _tr([r["load"], cust, r["entity"], r["delivered"], days_txt, money(r["revenue"])],
                          ["left", "left", "left", "left", "right", "right"],
                          [None, None, None, None, k, None])
    shown, count = u.get("shown", len(rows_data)), u.get("count", 0)
    uninv_more = (f"<tr><td colspan='6' style='padding:8px;color:{MUTE};font-size:11px;'>"
                  f"Showing the {shown} oldest of {count} loads.</td></tr>") if count > shown else ""

    ar_tiles = (_tile("90+ days AR", money(a.get("d91plus")), _pill("X-Trux + X-Linx", "bad"))
                + _tile("Customers 90+", num(len(custs)), _pill("over 90 days", "bad"))
                + _tile("Loads 90+", num(n_loads), _pill("open invoices", "mute"))
                + "<td class='tile-empty' width='25%' style='padding:6px;'></td>")
    ar_body = ""
    for c in custs:
        ar_body += _tr([c["customer"] or "&mdash; (no customer name)", str(c["loads"]),
                        str(c["oldest_days"]), money(c["amount"])],
                       ["left", "right", "right", "right"], [None, None, "bad", "bad"])

    return (f"{_header('Accounts Receivable &mdash; Overdue &amp; Alvys Accounting', 11, date_str, section='ACCOUNTING')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"{qb_tiles}"
            f"{_section('Overdue invoices (31+ days) by customer &middot; X-Trux + X-Linx &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'Invoice', 'Inv date', 'Due date', 'Amount', 'Bucket'], ['left', 'left', 'left', 'left', 'right', 'left'], rows + total_row)}"
            f"<tr><td colspan='4' style='padding:6px 0;border-top:2px solid {LINE};'></td></tr>"
            f"<tr>{uninv_tiles}</tr>"
            f"{_section('Delivered loads awaiting invoice &middot; oldest first &middot; as of ' + date_str)}"
            f"{_table(['Load #', 'Customer', 'Entity', 'Delivered', 'Days', 'Revenue'], ['left', 'left', 'left', 'left', 'right', 'right'], uninv_body + uninv_more)}"
            f"<tr>{ar_tiles}</tr>"
            f"{_section('Customers with open balances over 90 days &middot; by total &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'Loads', 'Oldest (days)', 'Amount'], ['left', 'right', 'right', 'right'], ar_body)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Top: QuickBooks A/R Aging Detail, X-Trux + X-Linx, current and 1&ndash;30 day balances omitted. "
            f"Middle: delivered Alvys loads with no Invoiced Date &mdash; the un-billed revenue behind most of the QB-vs-Alvys AR gap. "
            f"Bottom: open invoiced balances aged &gt;90 days past the Customer Due Date. "
            f"JW Logistics excluded throughout. Source: QuickBooks + Alvys API.</div>")


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
             + "<td class='tile-empty' width='25%' style='padding:6px;'></td>")

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

    return (f"{_header('AR Reconciliation by Customer &mdash; QuickBooks vs Alvys', 12, date_str, section='ACCOUNTING')}"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            f"<tr>{tiles}</tr>"
            f"{_section('Where the QB&ndash;Alvys gap sits &middot; by customer &middot; as of ' + date_str)}"
            f"{_table(['Customer', 'QuickBooks', 'Alvys', 'Variance'], ['left', 'right', 'right', 'right'], body)}"
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Open AR per customer, QuickBooks vs Alvys (X-Trux + X-Linx, JW excluded). Variance = QB &minus; Alvys; "
            f"a negative (red) value means Alvys shows more open AR &mdash; most often invoices already paid in QB but "
            f"not synced back. Rows sum to the page-1 variance. Customers joined by name; a one-sided row can be the "
            f"same customer spelled differently in the two systems. True bill-by-bill matching needs a shared invoice "
            f"number (not in the Alvys feed today). Sources: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")


def build_page8(qb_ar, alvys_ar, date_str) -> str:
    b = compute_bill_reconciliation(qb_ar, alvys_ar) or {}
    head = _header("AR Reconciliation by Invoice &mdash; QuickBooks vs Alvys", 13, date_str, section='ACCOUNTING')
    if not b.get("available"):
        msg = ("No open invoices to match this run &mdash; the QuickBooks A/R detail has no invoice "
               "numbers, or there is no open AR. See page 9 for the customer-level reconciliation.")
        return (f"{head}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
                f"{_brief(msg, 'warn')}</table>"
                f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
                f"Source: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")

    if b.get("no_match"):
        # Neither invoice # nor Load # overlapped QB's Num — show samples to compare formats.
        msg = ("Couldn&rsquo;t match bills: neither the Alvys invoice number nor the Alvys Load # overlaps the "
               "QuickBooks invoice &lsquo;Num&rsquo;. Sample identifiers below &mdash; the two systems appear to "
               "number invoices differently. Use page 9 (by customer) meanwhile.")
        srows = ""
        al_s, qb_s = b.get("alvys_sample", []), b.get("qb_sample", [])
        for i in range(max(len(al_s), len(qb_s))):
            srows += _tr([al_s[i] if i < len(al_s) else "", qb_s[i] if i < len(qb_s) else ""],
                         ["left", "left"], [None, None])
        return (f"{head}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
                f"{_brief(msg, 'warn')}"
                f"{_section('Sample identifiers &middot; Alvys vs QuickBooks')}"
                f"{_table(['Alvys invoice # / Load #', 'QuickBooks Num'], ['left', 'left'], srows)}</table>"
                f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
                f"Source: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")

    ao, qo, mm = b["alvys_only"], b["qb_only"], b["mismatch"]
    LIM = 20
    match_pct = (b["matched"] / b["alvys_n"]) if b["alvys_n"] else None
    key_label = "Load #" if b.get("key_used") == "load" else "invoice #"
    tiles = (_tile("Open in Alvys, not QB", money(b["alvys_only_total"]), _pill(f"{len(ao)} bills", "bad"))
             + _tile("Open in QB, not Alvys", money(b["qb_only_total"]), _pill(f"{len(qo)} bills", "warn"))
             + _tile("Match rate", pct(match_pct), _pill(f"on {key_label} &middot; {b['matched']}/{b['alvys_n']}", "mute"))
             + "<td class='tile-empty' width='25%' style='padding:6px;'></td>")

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
            f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
            f"Matched on Alvys {key_label} vs QuickBooks invoice &lsquo;Num&rsquo; (X-Trux + X-Linx, JW excluded). "
            f"&lsquo;Open in Alvys, not in QuickBooks&rsquo; are the bills driving the gap &mdash; most are likely "
            f"paid in QB but not synced back to Alvys. If the match rate is low, the two systems number bills "
            f"differently and this view is partial &mdash; use page 9. Sources: QuickBooks A/R Aging Detail, Alvys API (Loads).</div>")


def build_page9(samba, date_str, alvys_drivers=None) -> str:
    header = _header('Driver Compliance &mdash; SambaSafety + Alvys', 2, date_str, section='SAFETY')
    footer = (f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
              f"License numbers masked to last 4. Violations show the last {VIOLATION_WINDOW_DAYS} days. "
              f"License + MVR: SambaSafety. DOT medical card: Alvys Drivers feed.</div>")
    if not samba or not samba.get("monitored"):
        # SambaSafety not loaded — but Alvys medical-card data may still be available.
        return (f"{header}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
                f"{_section('Driver compliance &middot; SambaSafety')}"
                f"<tr><td colspan='4' style='padding:14px 6px;color:{MUTE};font-size:12.5px;'>"
                f"SambaSafety data unavailable this run.</td></tr>"
                + _alvys_medical_block(alvys_drivers)
                + footer)

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
            + _alvys_medical_block(alvys_drivers)
            + f"{_section('Recent violations &amp; MVR alerts &middot; last ' + str(samba['window_days']) + ' days')}{viol_block}"
            + f"{_section('Risk leaderboard &middot; highest-scoring drivers')}{risk_block}"
            + footer)


def _alvys_medical_block(alvys_drivers) -> str:
    """DOT medical card status block — Alvys is the system of record.
    Renders a section title + table (or a 'all good' brief). Safe to
    call with None / empty data."""
    if not alvys_drivers or not alvys_drivers.get("monitored"):
        return ""
    med30 = alvys_drivers.get("medical_issues_30") or []
    title = _section('DOT medical card &middot; expirations within 30d &middot; Alvys Drivers feed')
    if not med30:
        return title + _brief(
            "All active drivers have a current DOT medical card (none expiring within 30 days).",
            "good")
    rows = ""
    for d in med30:
        days = d.get("medical_days")
        exp = d.get("medical_exp")
        exp_txt = exp.strftime("%b %d, %Y") if exp is not None and not pd.isna(exp) else "&mdash;"
        days_txt = f"{int(days)}d" if isinstance(days, int) else "&mdash;"
        kind = "bad" if isinstance(days, int) and days <= 7 else "warn"
        rows += _tr(
            [d["name"], d.get("type") or "&mdash;", d.get("status") or "Active",
             exp_txt, days_txt],
            ["left", "left", "left", "left", "right"],
            [None, None, None, kind, kind])
    return title + _table(
        ["Driver", "Type", "Status", "Medical expires", "Days"],
        ["left", "left", "left", "left", "right"], rows)


def build_csa_scorecard_page(csa, date_str) -> str:
    """Page 10 — FMCSA CSA carrier BASIC percentile scores from SambaSafety."""
    head = _header("CSA Carrier Scorecard &mdash; X-Trux, Inc.", 10, date_str, section='SAFETY')
    if not csa or not csa.get("basics"):
        return (f"{head}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
                f"{_brief('CSA scorecard data unavailable this run &mdash; place CSA2010 Preview Scorecard.csv in OneDrive/SambaSafety/.', 'warn')}"
                f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
                f"Source: SambaSafety CSA Scorecard (FMCSA BASIC percentile ranks for X-Trux, Inc.).</div>")

    basics = csa["basics"]
    n_alert = csa["n_alert"]
    worst = csa["worst"] or {}
    snapshot = csa.get("snapshot_date") or "latest"
    dot_num = csa.get("dot_number") or "841776"
    mc_num = "375851"  # X-Trux, Inc. motor carrier authority
    avg_pu = csa.get("avg_power_units") or ""

    worst_name = worst.get("category", "n/a")
    worst_pct = worst.get("percentile")
    worst_pct_txt = f"{worst_pct:.0f}th" if worst_pct is not None else "n/a"
    alert_k = "bad" if n_alert > 0 else "good"
    alert_label = f"{n_alert} BASIC{'s' if n_alert != 1 else ''} above threshold"

    apu_sub = _pill(f"Avg {avg_pu} power units", "mute") if avg_pu else _pill(f"MC #{mc_num}", "mute")
    tiles = (
        _tile("Highest Risk BASIC", worst_name,
              _pill(f"{worst_pct_txt} percentile", "bad" if worst.get("intervention") else "warn"))
        + _tile("Intervention Alerts", str(n_alert), _pill(alert_label, alert_k))
        + _tile("Carrier Identity", f"DOT #{dot_num}", _pill(f"MC #{mc_num}", "mute"))
        + _tile("FMCSA Snapshot", snapshot, apu_sub)
    )

    body = ""
    for b in sorted(basics, key=lambda x: (x["percentile"] or 0), reverse=True):
        pct = b["percentile"]
        pct_txt = f"{pct:.1f}" if pct is not None else "&mdash;"
        insp = str(b["rel_inspections"]) if b["rel_inspections"] is not None else "&mdash;"
        measure_txt = f"{b['measure']:.2f}" if b["measure"] is not None else "&mdash;"
        if b["intervention"]:
            status_pill = _pill("INTERVENTION LIKELY", "bad")
            row_k = "bad"
        elif pct is not None and pct >= b["threshold"] * 0.75:
            status_pill = _pill("WATCH", "warn")
            row_k = "warn"
        else:
            status_pill = _pill("OK", "good")
            row_k = None
        body += _tr(
            [b["category"], insp, measure_txt, f"{pct_txt} &nbsp; {status_pill}"],
            ["left", "right", "right", "left"],
            [None, None, None, row_k],
        )

    section_label = (f"FMCSA BASIC Category Scores &middot; X-Trux, Inc. "
                     f"(DOT #{dot_num} &middot; MC #{mc_num}) &middot; Snapshot {snapshot}")
    return (
        f"{head}<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
        f"<tr>{tiles}</tr>"
        f"{_section(section_label)}"
        f"{_table(['BASIC Category', 'Rel. Inspections', 'BASIC Measure', 'CSA Percentile Rank'], ['left', 'right', 'right', 'left'], body)}"
        f"</table><div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;border-top:1px solid {LINE};margin-top:14px;'>"
        f"Percentile ranks from FMCSA Carrier Safety Measurement System (CSMS) via SambaSafety. "
        f"Unsafe Driving &amp; Crash Indicator alert at 65th percentile; all other BASICs at 80th. "
        f"Source: SambaSafety CSA Scorecard (DOT #{dot_num} &middot; MC #{mc_num}).</div>"
    )


def build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing,
               alvys_ar=None, warnings=None, data_asof=None, mileage=None, uninvoiced=None,
               rpm_trend=None, rpm_goal=None, rpm_goal_trend=None, samba=None, drag=None,
               margin_projection=None, alvys_drivers=None, equipment=None,
               dso_hist=None, avg_fuel_price=None, ontime=None, dh_trend=None,
               customer_rpm=None, csa=None) -> str:
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    pb = f"<div class='page-break' style='height:18px;background:#f3f3f3;'></div>"
    note = ""
    if missing:
        note = (f"<div style='background:{WARNBG};color:{WARN};font-size:12px;padding:8px 24px;'>"
                f"Note: could not read {', '.join(missing)} this run &mdash; those sections may be blank.</div>")
    wrap = lambda inner: f"<div class='brief-wrap' style='margin:0 auto;background:#fff;'>{inner}</div>"

    # Per-page insight strips — bridge from the page 1 narrative to detail.
    # Falls back to empty dict if scorecard_insights raises.
    _page_strips: dict = {}
    try:
        from src import scorecard_insights as _insights
        _page_strips = _insights.page_strips(
            alvys=alvys, qb_ar=qb_ar, alvys_ar=alvys_ar, samsara=samsara,
            uninvoiced=uninvoiced, samba=samba)
    except Exception as e:
        log.warning("page_strips failed (%s: %s)", type(e).__name__, e)

    def _strip(page_n: int) -> str:
        s = _page_strips.get(page_n)
        if not s:
            return ""
        return (
            f"<div style='padding:8px 24px 0;'>"
            f"<div style='background:{ACCENTBG};border-left:4px solid {ACCENT};"
            f"border-radius:6px;padding:10px 14px;color:{INK};font-size:12.5px;"
            f"line-height:1.45;'>"
            f"<span style='color:{ACCENT};font-weight:800;letter-spacing:.5px;"
            f"text-transform:uppercase;font-size:10px;'>"
            f"Context from today's brief</span><br>{s}</div></div>")
    # Mobile rendering deliberately keeps the desktop 4-column tile layout —
    # readers preferred seeing all four tiles in a row (with shrink-to-fit
    # text) over the responsive 1-up / 2-up stack patterns we tried.
    # `td.tile` / `td.tile-empty` classes remain on the cells in case we
    # want to revisit responsive overrides later. The .scroll-wide and
    # padding-trim rules below are kept since they don't affect the tile
    # layout and still help wide tables / headers on small screens.
    mobile_css = (
        "<style>"
        "@media only screen and (max-width:600px){"
        # Wide tables (driver mileage, AR reconciliation, bill matching) get
        # horizontal scroll instead of squishing.
        ".scroll-wide{overflow-x:auto !important;-webkit-overflow-scrolling:touch;}"
        # Trim the section header / page header padding so more vertical space
        # is usable on small screens.
        "td[style*='padding:18px 24px']{padding:14px 16px !important;}"
        "}"
        "</style>"
    )
    # Print CSS — drives WeasyPrint's pagination. Force background colors to
    # render in print (default behavior strips them), set Letter size with
    # narrow margins, and break to a new page wherever we render the page-break
    # divider in the HTML stream.
    print_css = (
        "<style>"
        # Letter size with a running XFreight footer (brand left, page n/m right).
        # 0.35in side margins give ~7.8in usable; .brief-wrap below is forced to
        # 100% width in print so the 760px email wrap doesn't clip the right edge.
        "@page{size:letter;margin:0.45in 0.35in 0.55in;"
        "@bottom-left{content:'XFREIGHT · Executive Brief';"
        "font-family:Helvetica,Arial,sans-serif;font-size:8.5pt;color:#999;"
        "font-weight:700;letter-spacing:1.5px;}"
        "@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);"
        "font-family:Helvetica,Arial,sans-serif;font-size:8.5pt;color:#999;}}"
        "body{-webkit-print-color-adjust:exact;print-color-adjust:exact;}"
        ".page-break{page-break-after:always;break-after:page;height:0 !important;background:transparent !important;}"
        # 760px email constraint is screen-only so WeasyPrint never sees it
        # and the brief fills the full letter printable area in the PDF.
        "@media screen{.brief-wrap{max-width:760px;}}"
        # Each content 'page' is designed for email scroll, not letter-fit; the
        # PDF footer's 'Page N of M' uses the real letter-page count, so the
        # in-content header's PG number was confusing. Hide it in print.
        ".pg-of{display:inline;}"
        "@media print{"
        # Ensure full-width in print (belt-and-suspenders alongside screen-only max-width).
        ".brief-wrap{max-width:none;width:100%;}"
        # Let wide tables wrap to a new page rather than clip in print.
        ".scroll-wide{overflow:visible !important;}"
        # Avoid splitting an individual row mid-cell (the row stays intact),
        # but let multi-row tables (driver mileage, idle, AR detail, speed
        # table, etc.) split across page boundaries — otherwise a multi-row
        # data table that doesn't fit the remaining space gets bumped whole
        # to the next page and leaves the prior page mostly empty.
        "tr{page-break-inside:avoid;break-inside:avoid;}"
        "table{page-break-inside:auto;break-inside:auto;}"
        # Hide the in-content 'Page N of M' badge in print to avoid the
        # mismatch with the real-letter-page counter in the running footer.
        ".pg-of{display:none !important;}"
        "}"
        "</style>"
    )
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"{mobile_css}{print_css}</head>"
            f"<body style='margin:0;background:#f3f3f3;{FONT}'>"
            f"{wrap(note + build_page1(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, date_str, alvys_ar=alvys_ar, warnings=warnings, data_asof=data_asof, rpm_trend=rpm_trend, rpm_goal=rpm_goal, rpm_goal_trend=rpm_goal_trend, drag=drag, margin_projection=margin_projection, uninvoiced=uninvoiced, samba=samba, alvys_drivers=alvys_drivers, dso_hist=dso_hist, ontime=ontime, dh_trend=dh_trend, customer_rpm=customer_rpm, equipment=equipment))}{pb}"
            # Driver Mileage runs immediately after the Executive Brief (whose
            # last section is X-Linx Overview) so the per-driver weekly view
            # follows the entity-level summary. Safety and AR pages then come
            # behind it. Function names build_page<N> are kept for stability,
            # but the page-number arguments in _header reflect the actual
            # render order.
            # Pages 2-13 grouped into three sections (SAFETY leads):
            #   SAFETY       (pages 2-6): SambaSafety driver/MVR scan,
            #                              Samsara speed-over-limit detail (pg 3),
            #                              Driver safety scores (pg 4),
            #                              Equipment compliance tractors (pg 5),
            #                              Equipment compliance trailers (pg 6)
            #   OPERATIONAL  (pages 7-9): driver mileage, fleet MPG/speeding,
            #                              fleet idle
            #   CSA SCORECARD (page 10):  FMCSA carrier BASIC percentiles (SambaSafety)
            #   ACCOUNTING   (pages 11-13): QB AR overdue + Alvys un-invoiced/90+ AR
            #                              combined (pg 11); QB-vs-Alvys recon (pg 12);
            #                              bill match (pg 13)
            # Function names (build_pageN) are kept stable; the integer page
            # number arg to _header() reflects the actual render position.
            # -- SAFETY --
            # SambaSafety driver scan (build_page9) leads the safety section;
            # Samsara safety detail (build_page2) follows.
            f"{wrap(_strip(2) + build_page9(samba, date_str, alvys_drivers=alvys_drivers))}{pb}"
            f"{wrap(_strip(3) + build_page2(samsara, date_str))}{pb}"
            f"{wrap(_strip(4) + build_page2b(samsara, date_str, pg=4))}{pb}"
            f"{wrap(_strip(5) + build_page_equipment(equipment, date_str, kind='tractors', pg=5))}{pb}"
            f"{wrap(_strip(6) + build_page_equipment(equipment, date_str, kind='trailers', pg=6))}{pb}"
            # -- OPERATIONAL --
            f"{wrap(_strip(7) + build_page4(mileage, date_str))}{pb}"
            f"{wrap(_strip(8) + build_page_fleet(samsara, date_str, customer_rpm=customer_rpm))}{pb}"
            f"{wrap(_strip(9) + build_page_idle(samsara, date_str, avg_fuel_price=avg_fuel_price))}{pb}"
            # -- CSA SCORECARD --
            f"{wrap(_strip(10) + build_csa_scorecard_page(csa, date_str))}{pb}"
            # -- ACCOUNTING --
            f"{wrap(_strip(11) + build_page_ar_accounting(qb_ar, uninvoiced, alvys_ar, date_str))}{pb}"
            f"{wrap(_strip(12) + build_page7(qb_ar, alvys_ar, date_str))}{pb}"
            f"{wrap(_strip(13) + build_page8(qb_ar, alvys_ar, date_str))}"
            f"</body></html>")


# ----------------------------------------------------------------------
# Orchestration (testable without network)
# ----------------------------------------------------------------------
def build_report(alvys_sheets, pnl_sheets, ar_sheets, ar_hist_sheets, ap_hist_sheets, samsara_sheets, missing,
                 alvys_pipeline_sheets=None, data_asof=None, sambasafety_sheets=None,
                 dso_hist_sheets=None) -> str:
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
    csa = compute_csa_scorecard(sambasafety_sheets) if sambasafety_sheets else None
    # Alvys-side driver compliance (CDL + DOT medical card expirations).
    # Read from the same Alvys Pipeline.xlsx as everything else — the
    # `Drivers` sheet is added by src.main when the pipeline writes it.
    alvys_drivers = compute_alvys_drivers(alvys_pipeline_sheets) if alvys_pipeline_sheets else None
    equipment = compute_alvys_equipment(alvys_pipeline_sheets) if alvys_pipeline_sheets else None
    w7a = ((alvys or {}).get("asset") or {}).get("7d") or (alvys or {}).get("7d")
    drag = compute_drag_attribution(alvys_sheets, qb_ar, w7a, rpm_goal, samsara)
    # DSO history: filter to X-Trux only (asset fleet — same scope the user sees in QB).
    _dso_companies = frozenset({"x-trux inc"})
    dso_hist = compute_dso_history(dso_hist_sheets, companies=_dso_companies)
    avg_fuel_price = compute_avg_fuel_price(alvys_pipeline_sheets) if alvys_pipeline_sheets else None
    dh_trend = compute_dh_trend(alvys_sheets) if alvys_sheets else None
    ontime = compute_ontime(alvys_pipeline_sheets) if alvys_pipeline_sheets else None
    customer_rpm = compute_customer_rpm(alvys_pipeline_sheets) if alvys_pipeline_sheets else None
    html = build_html(alvys, alvys_entities, qb_pnl, qb_ar, ar_hist, ap_hist, samsara, missing,
                      alvys_ar=alvys_ar, warnings=warnings, data_asof=data_asof, mileage=mileage,
                      uninvoiced=uninvoiced, rpm_trend=rpm_trend, rpm_goal=rpm_goal,
                      rpm_goal_trend=rpm_goal_trend, samba=samba, drag=drag,
                      margin_projection=margin_projection, alvys_drivers=alvys_drivers,
                      equipment=equipment, dso_hist=dso_hist,
                      avg_fuel_price=avg_fuel_price, ontime=ontime, dh_trend=dh_trend,
                      customer_rpm=customer_rpm, csa=csa)
    # Write today's snapshot for tomorrow's trend-aware action items.
    # The Karpathy-Wiki commit step in the workflow picks it up automatically.
    try:
        from src.scorecard_snapshots import collect_kpis, write_snapshot
        kpis = collect_kpis(alvys=alvys, qb_ar=qb_ar, alvys_ar=alvys_ar,
                            samsara=samsara, uninvoiced=uninvoiced,
                            rpm_goal=rpm_goal)
        write_snapshot(kpis)
    except Exception as e:
        log.warning("Snapshot write skipped (%s: %s)", type(e).__name__, e)
    # Stash the compute dicts on the returned string-like-thing so main()
    # can pass them to the lint checks without re-running everything.
    return _ReportResult(html, samsara=samsara, qb_ar=qb_ar, alvys_ar=alvys_ar)


class _ReportResult(str):
    """str subclass that carries the compute dicts as attributes — lets
    build_report keep returning a string for all existing callers while
    main() pulls the lint context off it."""
    def __new__(cls, html: str, **ctx):
        inst = super().__new__(cls, html)
        inst._ctx = ctx
        return inst


# ----------------------------------------------------------------------
# Email send (Microsoft Graph)
# ----------------------------------------------------------------------
def render_pdf(html: str) -> bytes | None:
    """Render the brief HTML to PDF bytes via WeasyPrint.

    Returns None if WeasyPrint isn't available so the email path keeps working
    even if the system libs (pango/cairo) are missing in CI.
    """
    try:
        from weasyprint import HTML  # type: ignore
    except Exception as e:
        log.warning("WeasyPrint not available — skipping PDF attachment: %s", e)
        return None
    # WeasyPrint logs every unsupported CSS property (we use plenty of
    # email-only quirks) and fontTools emits per-table DEBUG noise during
    # font subsetting — quiet both to ERROR so the run log stays readable.
    for _lg in ("weasyprint", "fontTools", "fontTools.subset",
                "fontTools.ttLib", "fontTools.ttLib.ttFont"):
        _logger = logging.getLogger(_lg)
        _logger.setLevel(logging.ERROR)
        _logger.propagate = False
    try:
        from weasyprint import CSS  # type: ignore

        # --- Pre-process HTML before handing to WeasyPrint ---

        # 1. Strip the screen-only 760px email cap so WeasyPrint uses the
        #    full letter page content area.
        pdf_html = html.replace(
            "@media screen{.brief-wrap{max-width:760px;}}",
            ".brief-wrap{max-width:none;width:100%;}"
        )

        # 2. Force outer content tables to table-layout:fixed.  With the default
        #    'auto' layout, long label text ("XFREIGHT REVENUE · MTD" etc.)
        #    can push a tile wider than 25%, overflowing the page.
        pdf_html = pdf_html.replace(
            "cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>",
            "cellpadding='0' cellspacing='0' style='padding:8px 18px 0;"
            "table-layout:fixed;width:100%;'>"
        )

        # 3. PDF-only page breaks before specific section headers so dense
        #    content (tile grids, customer tables) lands on a fresh page
        #    instead of getting orphaned at the bottom of the prior one.
        #    Each break closes the current table, drops a page-break div,
        #    then re-opens a new table — WeasyPrint honors break-before
        #    reliably between table boxes, not inside them.
        _section_tr_open = "<tr><td colspan='4' style='padding:22px 6px 4px;'>"
        _reopen_table = (
            "<table width='100%' cellpadding='0' cellspacing='0' "
            "style='padding:8px 18px 0;table-layout:fixed;width:100%;'>"
        )
        _pb_block = (
            "</table>"
            "<div style='page-break-before:always;break-before:page;height:0;'></div>"
            + _reopen_table
        )

        def _inject_pb_before(marker_text: str) -> None:
            """Find the first <tr> wrapping `marker_text` and inject a page
            break before it.  Only affects the first occurrence so other
            instances of the same section title (on dedicated pages) are
            untouched."""
            nonlocal pdf_html
            idx = pdf_html.find(marker_text)
            if idx <= 0:
                return
            tr_start = pdf_html.rfind(_section_tr_open, 0, idx)
            if tr_start <= 0:
                return
            pdf_html = pdf_html[:tr_start] + _pb_block + pdf_html[tr_start:]

        # XFreight Overview — pushes the entity tiles + reconciliation to
        # page 2, letting page 1 carry only the narrative.
        _inject_pb_before("XFreight Overview")
        # Overdue invoices (31+ days) table — pushes the customer-by-customer
        # AR detail to a fresh page after the AR aging tiles / Receivables
        # & payables chart row.
        _inject_pb_before("Overdue invoices (31+ days) by customer")
        # Safety & compliance — starts the safety tile + 6-month trend block
        # on a fresh page after the AR overdue customer table.  Match the
        # HTML-entity form ("&amp;" etc.) as it appears in the rendered string.
        _inject_pb_before("Safety &amp; compliance &mdash; 24h")
        # DVIR defects table — push to a fresh page after safety events.
        _inject_pb_before("DVIR defects (open) &mdash; all unresolved")
        # Risk leaderboard — push to fresh page after violations/MVR alerts.
        _inject_pb_before("Risk leaderboard &middot; highest-scoring drivers")

        # 4. Tag the wrapper <tr> emitted by _table() and other data-table
        #    builders so the inner data table can split across page boundaries.
        #    The wrappers all share `<td colspan='4' style='padding:0 6px;'>`
        #    (some also carry class='scroll-wide' for the wide mobile-scroll
        #    tables — idle, driver mileage, etc.). The global
        #    `tr { page-break-inside: avoid }` rule below would otherwise
        #    force the entire wrapper row — and the multi-row data table
        #    nested inside it — onto a single page, bumping whole tables to
        #    the next page when they don't fit and leaving the prior page
        #    empty under just a section header.
        pdf_html = pdf_html.replace(
            "<tr><td colspan='4' style='padding:0 6px;'>",
            "<tr class='pdf-data-wrap'><td colspan='4' style='padding:0 6px;'>",
        )
        pdf_html = pdf_html.replace(
            "<tr><td colspan='4' class='scroll-wide' style='padding:0 6px;'>",
            "<tr class='pdf-data-wrap'><td colspan='4' class='scroll-wide' style='padding:0 6px;'>",
        )

        # 5. Page source-note footers (the "Source: ... " divs that close each
        #    page builder) were getting orphaned onto an extra page when the
        #    content above ended near the bottom of the prior page — leaving
        #    pages like "page 19" almost entirely empty under just the source
        #    line.  Tag every source-footer div so we can apply
        #    page-break-before:avoid and shrink the top margin in PDF, pulling
        #    the source line back onto the same page as the data.
        pdf_html = pdf_html.replace(
            "<div style='padding:14px 24px 22px;color:#6b6b6b;font-size:11px;"
            "border-top:1px solid #ececec;margin-top:14px;'>",
            "<div class='pdf-source-note' style='padding:6px 24px 14px;color:#6b6b6b;"
            "font-size:11px;border-top:1px solid #ececec;margin-top:2px;'>",
        )

        # --- CSS override appended after document stylesheets ---
        # Switch the PDF to LANDSCAPE letter (11in x 8.5in) — the email is
        # 760px wide, which exceeds portrait letter's ~7.8in printable area
        # and clips the right-side tiles.  Landscape gives ~10.1in of usable
        # width — plenty for the 4-up tile layout to render edge-to-edge.
        # The running footers are re-declared because @page rules don't
        # cascade between stylesheets.
        _pdf_override = CSS(string=(
            "@page{size:letter landscape;margin:0.45in 0.5in 0.55in;"
            "@bottom-left{content:'XFREIGHT · Executive Brief';"
            "font-family:Helvetica,Arial,sans-serif;font-size:8.5pt;color:#999;"
            "font-weight:700;letter-spacing:1.5px;}"
            "@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);"
            "font-family:Helvetica,Arial,sans-serif;font-size:8.5pt;color:#999;}}"
            ".brief-wrap{max-width:none!important;width:100%!important;}"
            # Tile cells: clip overflow and wrap so nothing bleeds outside the
            # fixed-width column.
            "td.tile{overflow:hidden!important;word-break:break-word!important;"
            "overflow-wrap:anywhere!important;}"
            "td.tile>div{overflow:hidden!important;}"
            # _table()'s outer wrapper row: allow it to break across pages
            # so the multi-row inner data table can span page boundaries.
            # Individual data rows inside still inherit the global
            # tr{page-break-inside:avoid} so they stay intact.
            "tr.pdf-data-wrap{page-break-inside:auto!important;"
            "break-inside:auto!important;}"
            # Per-page source-note footer: stays with the prior data table
            # rather than getting orphaned onto an otherwise-empty page.
            ".pdf-source-note{page-break-before:avoid!important;"
            "break-before:avoid!important;}"
        ))

        pdf_bytes = (
            HTML(string=pdf_html)
            .render(stylesheets=[_pdf_override], presentational_hints=True)
            .write_pdf()
        )
        log.info("Generated PDF (%.1f KB)", len(pdf_bytes) / 1024)
        return pdf_bytes
    except Exception as e:
        log.warning("PDF rendering failed (%s: %s) — email will go without attachment",
                    type(e).__name__, e)
        return None


def send_email(token: str, from_upn: str, to_emails: list[str], subject: str,
               html: str, attachments: list[dict] | None = None) -> None:
    """Send the brief. attachments=[{name, content_bytes, mime}, ...] are
    delivered as Microsoft Graph fileAttachments (base64-encoded)."""
    import base64
    url = f"{GRAPH}/users/{from_upn}/sendMail"
    message: dict = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to_emails],
    }
    if attachments:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": a["name"],
                "contentType": a.get("mime", "application/octet-stream"),
                "contentBytes": base64.b64encode(a["content_bytes"]).decode("ascii"),
            }
            for a in attachments
        ]
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"message": message},
        timeout=60,
    )
    if resp.status_code == 202:
        attach_note = f" with {len(attachments)} attachment(s)" if attachments else ""
        log.info("Scorecard email sent to %s%s", ", ".join(to_emails), attach_note)
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

    # Idempotency: if today's brief was already sent (marker file present in
    # OneDrive), exit cleanly so backup cron runs don't email duplicates.
    # Manual workflow_dispatch runs and the SCORECARD_SKIP_IDEMPOTENCY=1 env
    # toggle both bypass the check so on-demand resends still work.
    if (os.environ.get("GITHUB_EVENT_NAME", "").strip() != "workflow_dispatch"
            and os.environ.get("SCORECARD_SKIP_IDEMPOTENCY", "").strip() != "1"):
        today_key = _today_chicago_key()
        marker_path = f"{_SENT_MARKER_FOLDER}/sent-{today_key}.txt"
        try:
            download_file(token, upn, marker_path)
            log.info("=" * 55)
            log.info("Today's brief was already sent (marker: %s)", marker_path)
            log.info("Skipping. workflow_dispatch or SCORECARD_SKIP_IDEMPOTENCY=1 forces resend.")
            log.info("=" * 55)
            return 0
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code == 404:
                log.info("No sent marker for %s — proceeding.", today_key)
            else:
                log.warning("Idempotency check HTTP %s; proceeding anyway.", code)
        except Exception as e:
            log.warning("Idempotency check failed (%s); proceeding anyway.", e)

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
    dso_hist_sheets = _safe_read(token, upn, f"{qb_dir}/QB_DSO_History.xlsx", [], "QB DSO history")
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
                        sambasafety_sheets=samba_sheets, dso_hist_sheets=dso_hist_sheets)
    # Pre-send review — two layers:
    #   1. scorecard_lint  — rule-based, always on, catches known regressions
    #   2. scorecard_review — LLM-based (Claude), opt-in via ANTHROPIC_API_KEY,
    #      catches the things rules miss (plausibility, format drift, etc.)
    # Both produce Finding objects; merged together so subject_prefix counts
    # errors from either source.
    try:
        from src.scorecard_lint import lint, format_findings, subject_prefix
        ctx = getattr(html, "_ctx", {}) or {}
        findings = lint(str(html), **ctx)
        try:
            from src.scorecard_review import review as llm_review
            findings.extend(llm_review(str(html), **ctx))
        except Exception as e:
            log.warning("LLM scorecard review skipped (%s: %s)", type(e).__name__, e)
        if findings:
            log.warning("Scorecard review findings:\n%s", format_findings(findings))
        else:
            log.info("Scorecard review: clean (rules + LLM)")
        prefix = subject_prefix(findings)
    except Exception as e:
        log.warning("Scorecard review skipped (%s: %s)", type(e).__name__, e)
        prefix = ""
    subject = f"{prefix}XFreight Executive Brief — {datetime.now():%b %d, %Y}"
    pdf_bytes = render_pdf(str(html))
    attachments = []
    if pdf_bytes:
        pdf_name = f"XFreight_Executive_Brief_{datetime.now():%Y-%m-%d}.pdf"
        attachments.append({
            "name": pdf_name,
            "content_bytes": pdf_bytes,
            "mime": "application/pdf",
        })
    # When the PDF rendered successfully, the email body is a short cover
    # note pointing at the attachment. The full inline HTML body is only
    # used as a fallback when PDF rendering failed, so the brief still
    # reaches the recipient one way or another.
    if pdf_bytes:
        body_html = (
            "<div style=\"font-family:-apple-system,'Helvetica Neue',Helvetica,"
            "Arial,sans-serif;font-size:14px;color:#1a1a1a;line-height:1.5;"
            "padding:24px;max-width:560px;\">"
            "<div style=\"font-weight:700;letter-spacing:1.5px;font-size:11px;"
            "color:#c41e2a;text-transform:uppercase;margin-bottom:14px;\">"
            "XFreight &middot; Executive Brief</div>"
            f"<p style=\"margin:0 0 12px;\">Your daily XFreight Executive Brief "
            f"for <b>{datetime.now():%A, %B %d, %Y}</b> is attached as a PDF.</p>"
            "<p style=\"margin:0;color:#6b6b6b;font-size:12.5px;\">"
            "If the attachment doesn&rsquo;t open, reply to this email and "
            "we&rsquo;ll resend.</p>"
            "</div>"
        )
    else:
        body_html = str(html)
    send_email(token, from_upn, to_emails, subject, body_html, attachments=attachments)

    # Write today's 'sent' marker so the staggered backup crons short-circuit.
    # Failure to write the marker is non-fatal — at worst we re-send today.
    try:
        import tempfile
        today_key = _today_chicago_key()
        marker_name = f"sent-{today_key}.txt"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
            tf.write(f"{today_key}\n{datetime.now().isoformat()}\n")
            _marker_tmp = Path(tf.name)
        try:
            ensure_folder(token, upn, _SENT_MARKER_FOLDER)
            upload_file(token=token, user_upn=upn,
                        folder_path=_SENT_MARKER_FOLDER,
                        filename=marker_name, file_path=_marker_tmp)
            log.info("Marker written: %s/%s", _SENT_MARKER_FOLDER, marker_name)
        finally:
            _marker_tmp.unlink(missing_ok=True)
    except Exception as e:
        log.warning("Failed to write 'sent' marker (%s) — backup crons may resend.", e)

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
