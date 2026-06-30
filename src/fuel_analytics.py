"""Fuel cost analytics — computed directly from Alvys fuel transactions +
trip mileage, with no Excel/OneDrive staging step in between.

This mirrors xfreight_etas.py's architecture (direct Alvys/Samsara API calls,
render straight out) rather than scorecard_email.py's architecture (read
pre-staged OneDrive Excel files). compute_fuel() is a pure function over raw
Alvys API records — the same shape AlvysClient.fetch_fuel() / fetch_trips()
return — so it is independently testable without live credentials.

Inputs:
  fuel_records  — raw items from AlvysClient.fetch_fuel(start_date)
  trip_records  — raw items from AlvysClient.fetch_trips(start_date), which
                   supply the per-truck/driver mileage denominator for $/mile
                   (fuel transactions don't carry mileage themselves)

SCOPE NOTE — Phase 1 of a larger fuel-analytics build. This module computes
fuel spend / gallons / price-per-gallon / fleet fuel-cost-per-mile / per-driver
breakdown as STANDALONE diagnostics. It is deliberately NOT merged into
compute_rpm_goal's cost_per_mile / goal_rpm in scorecard_email.py yet — that
integration is gated on confirming two open accounting questions first:
  1. Does QuickBooks "Total Expenses" (the line already driving the RPM goal's
     overhead_per_mile) include fuel-card spend? If so, adding this module's
     fuel_cost_per_mile on top would double-count it.
  2. Is Alvys "Driver Rate" (driver pay) gross of fuel-card deductions, or
     already net of them? If net, adding fuel cost on top of driver pay would
     also double-count.
Until both are confirmed against real QuickBooks/Alvys data, treat
fuel_cost_per_mile as informational only — do not fold it into the official
cost-per-mile / rate-negotiation number.

Also deliberately out of scope here (follow-up phases):
  - Teams coaching cards (the suppression/persistence plumbing already exists
    in src/suppression_registry.py and the talk-track pattern already exists
    in src/scorecard_insights.py::coaching_cards — this module's
    high_cost_drivers list is shaped to plug into that pattern directly)
  - Wiring into the daily brief's live render pipeline / GitHub Actions
    secrets (scorecard_email.py currently only reads OneDrive Excel; adding
    a live Alvys/Samsara call there is a real workflow-config change)
  - Power BI feed
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Cached FRED diesel price written by market_context.py — read it instead of
# making a second live FRED call from this module.
_MARKET_CONTEXT_PATH = (Path(__file__).resolve().parent.parent
                        / "Karpathy-Wiki" / "wiki" / "market-context.json")

# Per spec: a driver above this fuel $/mile gets flagged for coaching.
FUEL_HIGH_COST_THRESHOLD_PER_MILE = 0.55

MUTE = "#6b6b6b"
AMBER = "#d97706"
RED = "#c41e2a"
LINE = "#e5e5e5"
TILEBG = "#fafafa"


# ---------------------------------------------------------------------------
# Raw-record helpers
# ---------------------------------------------------------------------------
def _isnum(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v  # excludes NaN


def _g(d: dict, *path: str):
    """Dotted-path getter for raw Alvys JSON, tolerant of missing keys."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _parse_iso(s) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _norm_driver_name(name: str | None) -> str:
    """Lowercase, strip punctuation/digits, collapse whitespace — enough to
    join a fuel transaction's free-text DriverName to a trip's Driver1.FullName
    even when formatting differs slightly."""
    s = (name or "").lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fuel_amount(rec: dict) -> float:
    """Dollar amount actually paid for a fuel transaction. Prefer Total.Amount
    (includes any transaction fee — what was actually owed); fall back to
    FuelTotal.Amount (the fuel-product-only net) when Total is absent."""
    amt = _g(rec, "Total", "Amount")
    if not _isnum(amt):
        amt = _g(rec, "FuelTotal", "Amount")
    return float(amt) if _isnum(amt) else 0.0


def _fuel_gallons(rec: dict) -> float:
    qty = _g(rec, "Quantity", "Value")
    return float(qty) if _isnum(qty) else 0.0


def _trip_truck_name(trip: dict) -> str | None:
    truck = trip.get("Truck") or {}
    if not isinstance(truck, dict):
        return None
    return (truck.get("TruckNum") or truck.get("TruckNumber")
            or truck.get("Number") or truck.get("Name"))


def _trip_driver_name(trip: dict) -> str | None:
    drv = trip.get("Driver1") or {}
    if not isinstance(drv, dict):
        return None
    return drv.get("FullName") or drv.get("Name") or drv.get("DisplayName")


def _trip_miles(trip: dict) -> float:
    val = _g(trip, "TotalMileage", "Distance", "Value")
    return float(val) if _isnum(val) else 0.0


def _trip_date(trip: dict) -> datetime | None:
    """Best-effort date for bucketing a trip into a month. Trips don't carry a
    single canonical 'when did this mileage happen' field, so try the most
    recent-activity fields in order."""
    for key in ("UpdatedAt", "CompletedAt", "CreatedAt"):
        dt = _parse_iso(trip.get(key))
        if dt:
            return dt
    return None


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _month_key(dt: datetime) -> tuple[int, int]:
    return (dt.year, dt.month)


# ---------------------------------------------------------------------------
# Core: one month's fuel analytics
# ---------------------------------------------------------------------------
def compute_fuel(
    fuel_records: list[dict] | None,
    trip_records: list[dict] | None,
    *,
    now: datetime | None = None,
    national_diesel_price: float | None = None,
    high_cost_threshold: float = FUEL_HIGH_COST_THRESHOLD_PER_MILE,
) -> dict | None:
    """Fleet + per-driver fuel cost analytics for the current month.

    national_diesel_price: live FRED US diesel $/gal (from market_context's
        cached series) for the "vs national average" comparison; omit to skip.

    Returns None only when there are no fuel records at all. Otherwise returns
    every metric it can compute and leaves the rest None, so a caller can
    render a partial result — fail-soft, matching the rest of the pipeline.
    """
    if not fuel_records:
        return None

    now = now or datetime.now(timezone.utc)
    month_start = _month_start(now)

    # --- Per-truck / per-driver mileage from trips, scoped to this month ---
    miles_by_truck: dict[str, float] = {}
    miles_by_driver: dict[str, float] = {}
    fleet_miles_mtd = 0.0
    for trip in (trip_records or []):
        dt = _trip_date(trip)
        if dt is None or dt < month_start:
            continue
        miles = _trip_miles(trip)
        if miles <= 0:
            continue
        fleet_miles_mtd += miles
        truck = _trip_truck_name(trip)
        if truck:
            tkey = str(truck).strip()
            miles_by_truck[tkey] = miles_by_truck.get(tkey, 0.0) + miles
        driver = _trip_driver_name(trip)
        dkey = _norm_driver_name(driver)
        if dkey:
            miles_by_driver[dkey] = miles_by_driver.get(dkey, 0.0) + miles

    # --- Fuel transactions, scoped to this month ----------------------------
    spend_mtd = 0.0
    gallons_mtd = 0.0
    by_key: dict[str, dict] = {}   # join key -> {driver, truck, spend, gallons}
    skipped_no_date = 0
    for rec in fuel_records:
        dt = _parse_iso(rec.get("TransactionDate"))
        if dt is None:
            skipped_no_date += 1
            continue
        if dt < month_start:
            continue
        amt = _fuel_amount(rec)
        gal = _fuel_gallons(rec)
        spend_mtd += amt
        gallons_mtd += gal

        driver_raw = (rec.get("DriverName") or "").strip()
        truck_raw = (rec.get("TruckNumber") or "").strip()
        dkey = _norm_driver_name(driver_raw)
        key = dkey or (f"truck:{truck_raw}" if truck_raw else "unassigned")
        slot = by_key.setdefault(key, {
            "driver": driver_raw or None, "truck": truck_raw or None,
            "spend": 0.0, "gallons": 0.0,
        })
        slot["spend"] += amt
        slot["gallons"] += gal
        if not slot["truck"] and truck_raw:
            slot["truck"] = truck_raw

    avg_price_per_gallon = (spend_mtd / gallons_mtd) if gallons_mtd else None
    fuel_cost_per_mile = (spend_mtd / fleet_miles_mtd) if fleet_miles_mtd else None
    price_vs_national = (
        avg_price_per_gallon - national_diesel_price
        if (_isnum(avg_price_per_gallon) and _isnum(national_diesel_price)) else None
    )

    # --- Per-driver rollup, miles joined in by normalized name (then truck) -
    driver_rows: list[dict] = []
    for key, slot in by_key.items():
        dkey = _norm_driver_name(slot["driver"])
        miles = miles_by_driver.get(dkey) if dkey else None
        if not miles and slot["truck"]:
            miles = miles_by_truck.get(slot["truck"])
        cost_per_mile = (slot["spend"] / miles) if miles else None
        driver_rows.append({
            "driver": slot["driver"] or "Unassigned",
            "truck": slot["truck"] or "—",
            "spend": round(slot["spend"], 2),
            "gallons": round(slot["gallons"], 1),
            "miles": round(miles, 1) if miles else None,
            "cost_per_mile": round(cost_per_mile, 4) if cost_per_mile is not None else None,
        })
    driver_rows.sort(key=lambda r: (r["cost_per_mile"] is None, -(r["cost_per_mile"] or 0)))

    high_cost_drivers = [
        r for r in driver_rows
        if r["cost_per_mile"] is not None and r["cost_per_mile"] > high_cost_threshold
    ]

    warnings: list[str] = []
    if skipped_no_date:
        warnings.append(
            f"{skipped_no_date} fuel transaction(s) had no TransactionDate and were excluded.")
    if gallons_mtd and not fleet_miles_mtd:
        warnings.append(
            "Fuel spend recorded but no trip mileage found this month — "
            "fuel cost/mile cannot be computed.")

    return {
        "month_start": month_start,
        "spend_mtd": round(spend_mtd, 2),
        "gallons_mtd": round(gallons_mtd, 1),
        "avg_price_per_gallon": round(avg_price_per_gallon, 3) if avg_price_per_gallon is not None else None,
        "national_diesel_price": national_diesel_price,
        "price_vs_national": round(price_vs_national, 3) if price_vs_national is not None else None,
        "fleet_miles_mtd": round(fleet_miles_mtd, 1) if fleet_miles_mtd else None,
        "fuel_cost_per_mile": round(fuel_cost_per_mile, 4) if fuel_cost_per_mile is not None else None,
        "high_cost_threshold": high_cost_threshold,
        "by_driver": driver_rows,
        "high_cost_drivers": high_cost_drivers,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Six-month rolling trend (one pull covers it — fuel transactions are a
# historical log, not a snapshot, so no rolling-CSV accumulation is needed)
# ---------------------------------------------------------------------------
def compute_fuel_trend(
    fuel_records: list[dict] | None,
    trip_records: list[dict] | None,
    *,
    now: datetime | None = None,
    months: int = 6,
) -> dict:
    """Month-by-month fuel spend / avg $/gal / fuel $/mile for the trailing
    `months` calendar months (current month included, partial/MTD).

    Returns {"labels": [...], "spend": [...], "avg_price_per_gallon": [...],
    "fuel_cost_per_mile": [...]} — current month's label gets a trailing '*'
    to mark it as month-to-date, matching the convention used by the other
    trend charts in this codebase (e.g. compute_rpm_goal_trend).
    """
    now = now or datetime.now(timezone.utc)
    cur_start = _month_start(now)
    month_starts: list[datetime] = []
    y, m = cur_start.year, cur_start.month
    for _ in range(months):
        month_starts.append(datetime(y, m, 1, tzinfo=timezone.utc))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    month_starts.reverse()

    spend_by_month: dict[tuple[int, int], float] = {k: 0.0 for k in map(_month_key, month_starts)}
    gallons_by_month: dict[tuple[int, int], float] = {k: 0.0 for k in spend_by_month}
    miles_by_month: dict[tuple[int, int], float] = {k: 0.0 for k in spend_by_month}
    earliest = month_starts[0]

    for rec in (fuel_records or []):
        dt = _parse_iso(rec.get("TransactionDate"))
        if dt is None or dt < earliest:
            continue
        key = _month_key(dt)
        if key not in spend_by_month:
            continue
        spend_by_month[key] += _fuel_amount(rec)
        gallons_by_month[key] += _fuel_gallons(rec)

    for trip in (trip_records or []):
        dt = _trip_date(trip)
        if dt is None or dt < earliest:
            continue
        key = _month_key(dt)
        if key not in miles_by_month:
            continue
        miles_by_month[key] += _trip_miles(trip)

    labels, spend, avg_ppg, cost_pm = [], [], [], []
    for i, ms in enumerate(month_starts):
        key = _month_key(ms)
        label = ms.strftime("%b")
        if i == len(month_starts) - 1:
            label += "*"
        labels.append(label)
        spend.append(round(spend_by_month[key], 2))
        g = gallons_by_month[key]
        avg_ppg.append(round(spend_by_month[key] / g, 3) if g else None)
        mi = miles_by_month[key]
        cost_pm.append(round(spend_by_month[key] / mi, 4) if mi else None)

    return {"labels": labels, "spend": spend, "avg_price_per_gallon": avg_ppg,
            "fuel_cost_per_mile": cost_pm}


# ---------------------------------------------------------------------------
# Live-fetch convenience wrapper (the actual "direct from Alvys API" entry
# point — not yet called from anywhere; a caller wires this to a schedule).
# ---------------------------------------------------------------------------
def fetch_and_compute_fuel(alvys_client, start_date: str, **kwargs) -> dict | None:
    """Pull fuel + trip records straight from Alvys and run compute_fuel().
    No Excel/OneDrive staging — alvys_client is an AlvysClient instance."""
    fuel_records = alvys_client.fetch_fuel(start_date)
    trip_records = alvys_client.fetch_trips(start_date)
    return compute_fuel(fuel_records, trip_records, **kwargs)


def read_national_diesel_price(path: "Path | str | None" = None) -> float | None:
    """Read the live US diesel $/gal that market_context.py already fetched
    and cached, instead of making a second live FRED call from here.
    Fail-soft: returns None on any missing/unreadable/malformed cache —
    callers should treat the national comparison as optional."""
    p = Path(path) if path else _MARKET_CONTEXT_PATH
    try:
        data = json.loads(p.read_text())
        val = data["sources"]["diesel_us"]["current"]["value"]
        return float(val) if _isnum(val) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Coaching talk-track — matches the quoted, threshold-tiered style already
# used by scorecard_insights.py::_pick_talk_track for idle-time coaching.
# ---------------------------------------------------------------------------
def fuel_talk_track(cost_per_mile: float, threshold: float,
                    fleet_avg: float | None = None) -> str:
    """Pre-written talk track for a high-fuel-cost-per-mile coaching card."""
    over = cost_per_mile - threshold
    avg_note = (f" Fleet average is ${fleet_avg:.2f}/mi."
                if _isnum(fleet_avg) else "")
    if cost_per_mile > threshold * 1.5:
        return (f'"You\'re running ${cost_per_mile:.2f}/mi in fuel — about '
                f'{(cost_per_mile / threshold - 1) * 100:.0f}% over our '
                f'${threshold:.2f}/mi line.{avg_note} Let\'s check idle time, '
                f'route choice, and whether you\'re buying at preferred-network '
                f'stops on the card."')
    return (f'"Fuel cost is ${cost_per_mile:.2f}/mi this month, ${over:.2f} over '
            f'our ${threshold:.2f}/mi target.{avg_note} Anything different about '
            f'your routes, idle habits, or where you\'re fueling up lately?"')


# ---------------------------------------------------------------------------
# HTML rendering — a self-contained section, pluggable into the daily brief
# ---------------------------------------------------------------------------
def render_fuel_section_html(fuel: dict | None) -> str:
    """Render the daily-brief Fuel section described in the spec:
    fleet spend MTD, gallons MTD, avg $/gal vs national, fuel cost/mile,
    and a high-fuel-cost-driver callout list.

    NOTE: fuel_cost_per_mile is shown as a standalone diagnostic, not yet
    folded into the brief's official cost-per-mile figure — see module
    docstring for why.
    """
    if not fuel:
        return (f"<div style='padding:16px 24px;color:{MUTE};font-size:12px;'>"
                f"No fuel transactions this month.</div>")

    def _money(v):
        return f"${v:,.2f}" if v is not None else "—"

    def _ppg(v):
        return f"${v:.3f}/gal" if v is not None else "—"

    def _pm(v):
        return f"${v:.3f}/mi" if v is not None else "—"

    vs_nat = fuel.get("price_vs_national")
    if vs_nat is None:
        vs_nat_str = ""
    else:
        sign = "+" if vs_nat >= 0 else "&minus;"
        color = RED if vs_nat > 0 else "#16a34a"
        vs_nat_str = (f"&nbsp;<span style='color:{color};font-size:11px;'>"
                      f"({sign}${abs(vs_nat):.3f} vs national)</span>")

    tiles = "".join(
        f"<div style='flex:1;min-width:140px;padding:12px;background:{TILEBG};"
        f"border:1px solid {LINE};border-radius:6px;'>"
        f"<div style='font-size:10px;text-transform:uppercase;letter-spacing:0.5px;"
        f"color:{MUTE};'>{label}</div>"
        f"<div style='font-size:18px;font-weight:700;margin-top:4px;'>{value}</div></div>"
        for label, value in (
            ("Fuel Spend MTD", _money(fuel.get("spend_mtd"))),
            ("Gallons MTD", f"{fuel.get('gallons_mtd', 0):,.0f} gal"),
            ("Avg Price / Gal", _ppg(fuel.get("avg_price_per_gallon")) + vs_nat_str),
            ("Fuel Cost / Mile", _pm(fuel.get("fuel_cost_per_mile"))),
        )
    )

    high_cost = fuel.get("high_cost_drivers") or []
    threshold = fuel.get("high_cost_threshold", FUEL_HIGH_COST_THRESHOLD_PER_MILE)
    if high_cost:
        rows = "".join(
            f"<tr style='border-bottom:1px solid {LINE};'>"
            f"<td style='padding:6px 10px;font-weight:700;'>{r['driver']}</td>"
            f"<td style='padding:6px 10px;color:{MUTE};'>{r['truck']}</td>"
            f"<td style='padding:6px 10px;color:{RED};font-weight:700;'>{_pm(r['cost_per_mile'])}</td>"
            f"<td style='padding:6px 10px;'>{_money(r['spend'])}</td>"
            f"<td style='padding:6px 10px;'>{r['gallons']:,.0f} gal</td>"
            f"</tr>"
            for r in high_cost
        )
        high_cost_html = (
            f"<div style='margin-top:14px;'>"
            f"<div style='font-weight:700;text-transform:uppercase;font-size:11px;"
            f"letter-spacing:0.8px;color:{AMBER};'>High Fuel Cost Drivers "
            f"(&gt;{_pm(threshold)})</div>"
            f"<table cellpadding='0' cellspacing='0' style='width:100%;border-collapse:collapse;"
            f"margin-top:6px;font-size:12px;'>"
            f"<thead><tr style='background:{TILEBG};border-bottom:2px solid {LINE};'>"
            f"<th style='padding:6px 10px;text-align:left;font-size:10px;color:{MUTE};'>Driver</th>"
            f"<th style='padding:6px 10px;text-align:left;font-size:10px;color:{MUTE};'>Truck</th>"
            f"<th style='padding:6px 10px;text-align:left;font-size:10px;color:{MUTE};'>$/Mile</th>"
            f"<th style='padding:6px 10px;text-align:left;font-size:10px;color:{MUTE};'>Spend MTD</th>"
            f"<th style='padding:6px 10px;text-align:left;font-size:10px;color:{MUTE};'>Gallons</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
    else:
        high_cost_html = (
            f"<div style='margin-top:14px;color:{MUTE};font-size:12px;'>"
            f"No drivers above {_pm(threshold)} this month.</div>"
        )

    warn_html = ""
    if fuel.get("warnings"):
        warn_html = "".join(
            f"<div style='color:{AMBER};font-size:11px;margin-top:4px;'>&#9888; {w}</div>"
            for w in fuel["warnings"]
        )

    return (
        f"<div style='padding:16px 24px;'>"
        f"<div style='font-weight:700;text-transform:uppercase;font-size:11px;"
        f"letter-spacing:0.8px;color:{MUTE};margin-bottom:8px;'>Fuel</div>"
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;'>{tiles}</div>"
        f"{high_cost_html}{warn_html}</div>"
    )
