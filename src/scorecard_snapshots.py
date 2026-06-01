"""Daily KPI snapshots for trend-aware insights.

Writes one JSON file per day to `Karpathy-Wiki/raw/snapshots/YYYY-MM-DD.json`
at the end of each scorecard run, capturing the day's key KPIs. The next
morning's run reads the most recent prior snapshot and feeds it to
`scorecard_insights.action_items()` so trend labels like "CLIMBING" /
"GROWING" can be verified rather than asserted.

Storage cost: ~1 KB per day, ~365 KB/year, auto-committed by the same
workflow step that already archives the rendered brief.

Schema is intentionally flat — one level deep, all leaf values — so adding
a new tracked KPI is a one-line change in `collect_kpis()`.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path("Karpathy-Wiki/raw/snapshots")


def _safe_get(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def collect_kpis(*, alvys, qb_ar, alvys_ar, samsara, uninvoiced,
                 rpm_goal) -> dict:
    """Pull the KPIs we want to detect trends on. Flat dict, JSON-safe."""
    snap: dict = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }

    # Alvys MTD (or rollover-substituted last month)
    mtd = (alvys or {}).get("mtd") or {}
    snap["mtd_revenue"]    = mtd.get("revenue")
    snap["mtd_cost"]       = mtd.get("cost")
    snap["mtd_margin"]     = mtd.get("margin")
    snap["mtd_margin_pct"] = mtd.get("margin_pct")
    snap["mtd_loads"]      = mtd.get("loads")
    snap["mtd_miles"]      = mtd.get("miles")
    snap["mtd_label"]      = (alvys or {}).get("mtd_label", "MTD")

    # QB AR buckets
    if qb_ar:
        totals = qb_ar.get("totals") or {}
        snap["qb_ar_total"]         = qb_ar.get("total_ar")
        snap["qb_ar_total_past_due"] = qb_ar.get("total_past_due")
        snap["qb_ar_total_31_plus"] = qb_ar.get("total31")
        snap["qb_ar_31_60"]         = totals.get("31&ndash;60") or totals.get("31-60")
        snap["qb_ar_61_90"]         = totals.get("61&ndash;90") or totals.get("61-90")
        snap["qb_ar_91_plus"]       = totals.get("91+")

    # Alvys AR
    if alvys_ar:
        snap["alvys_ar_total"]   = alvys_ar.get("total")
        snap["alvys_ar_overdue"] = alvys_ar.get("overdue")

    # Samsara fleet
    fleet = (samsara or {}).get("fleet") or {}
    snap["fleet_idle_hours"] = fleet.get("fleet_idle_hours")
    snap["fleet_mpg"]        = fleet.get("fleet_mpg")
    snap["fleet_score"]      = fleet.get("fleet_score")

    # Un-invoiced loads
    if uninvoiced:
        snap["uninvoiced_count"] = uninvoiced.get("count")
        snap["uninvoiced_amt"]   = uninvoiced.get("total_revenue")

    # RPM goal vs actual
    if rpm_goal:
        snap["rpm_actual"] = rpm_goal.get("actual_rpm")
        snap["rpm_goal"]   = rpm_goal.get("goal_rpm")

    # Drop None values to keep the file readable
    return {k: v for k, v in snap.items() if v is not None}


def write_snapshot(kpis: dict) -> str | None:
    """Write today's snapshot to disk. Overwrites if a run already wrote
    today; the last run of the day wins (which is fine — KPIs are
    cumulative within a day and we want the most recent close)."""
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        today = kpis.get("date") or date.today().isoformat()
        path = SNAPSHOT_DIR / f"{today}.json"
        path.write_text(json.dumps(kpis, indent=2, sort_keys=True))
        log.info("Snapshot written: %s (%d keys)", path, len(kpis))
        return str(path)
    except Exception as e:
        log.warning("Snapshot write failed: %s: %s", type(e).__name__, e)
        return None


def read_prior_snapshot(today: date | None = None) -> dict | None:
    """Return the most recent snapshot file whose date < today, or None.
    Used by action_items() to compute trend deltas."""
    today = today or date.today()
    if not SNAPSHOT_DIR.exists():
        return None
    today_str = today.isoformat()
    candidates = sorted(p for p in SNAPSHOT_DIR.glob("*.json")
                        if p.stem < today_str)
    if not candidates:
        return None
    try:
        return json.loads(candidates[-1].read_text())
    except Exception as e:
        log.warning("Prior snapshot read failed (%s): %s", candidates[-1], e)
        return None
