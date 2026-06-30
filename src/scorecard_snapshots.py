"""Daily KPI snapshots for trend-aware insights.

Writes one JSON file per day to `Karpathy-Wiki/raw/snapshots/YYYY-MM-DD.json`
at the end of each scorecard run, capturing the day's key KPIs. The next
morning's run reads the most recent prior snapshot and feeds it to
`scorecard_insights.action_items()` so trend labels like "CLIMBING" /
"GROWING" can be verified rather than asserted.

Storage cost: ~1 KB per day, ~365 KB/year.

`Karpathy-Wiki/.gitignore` deliberately keeps `raw/*` (business data) out of
git, so the local file below never survives past the GitHub Actions runner
it was written on — a fresh checkout the next morning starts with an empty
SNAPSHOT_DIR. To actually carry yesterday's snapshot forward (and to give
the Slack/Teams digest something to read), write_snapshot() also mirrors
the file to OneDrive (Scorecard/snapshot-latest.json), and
read_prior_snapshot() falls back to that mirror when local disk is empty.

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
_ONEDRIVE_FOLDER = "Scorecard"
_ONEDRIVE_FILENAME = "snapshot-latest.json"


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
    cumulative within a day and we want the most recent close).

    Also best-effort mirrors the file to OneDrive (Scorecard/snapshot-latest.json)
    so it survives past this runner — see module docstring."""
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        today = kpis.get("date") or date.today().isoformat()
        path = SNAPSHOT_DIR / f"{today}.json"
        path.write_text(json.dumps(kpis, indent=2, sort_keys=True))
        log.info("Snapshot written: %s (%d keys)", path, len(kpis))
    except Exception as e:
        log.warning("Snapshot write failed: %s: %s", type(e).__name__, e)
        return None
    _mirror_to_onedrive(path)
    return str(path)


def _mirror_to_onedrive(path: Path) -> None:
    from src.onedrive_upload import ensure_folder, get_token_from_env, upload_file
    token, upn = get_token_from_env()
    if not token:
        return
    try:
        ensure_folder(token, upn, _ONEDRIVE_FOLDER)
        upload_file(token=token, user_upn=upn, folder_path=_ONEDRIVE_FOLDER,
                   filename=_ONEDRIVE_FILENAME, file_path=path)
        log.info("Snapshot mirrored to OneDrive: %s/%s", _ONEDRIVE_FOLDER, _ONEDRIVE_FILENAME)
    except Exception as e:
        log.warning("Snapshot OneDrive mirror failed: %s: %s", type(e).__name__, e)


def read_prior_snapshot(today: date | None = None) -> dict | None:
    """Return the most recent snapshot whose date < today, or None.
    Used by action_items() to compute trend deltas.

    Checks local disk first (same-process / local-dev reruns), then falls
    back to the OneDrive mirror — a fresh GitHub Actions checkout starts
    with an empty SNAPSHOT_DIR every morning, so OneDrive is what actually
    carries yesterday's numbers forward in CI."""
    today = today or date.today()
    today_str = today.isoformat()
    if SNAPSHOT_DIR.exists():
        candidates = sorted(p for p in SNAPSHOT_DIR.glob("*.json")
                            if p.stem < today_str)
        if candidates:
            try:
                return json.loads(candidates[-1].read_text())
            except Exception as e:
                log.warning("Prior snapshot read failed (%s): %s", candidates[-1], e)
    from src.onedrive_upload import download_file, get_token_from_env
    token, upn = get_token_from_env()
    if not token:
        return None
    try:
        raw = download_file(token, upn, f"{_ONEDRIVE_FOLDER}/{_ONEDRIVE_FILENAME}")
        snap = json.loads(raw)
        if (snap.get("date") or "") < today_str:
            return snap
        return None  # only today's own snapshot mirrored so far — not "prior"
    except Exception as e:
        log.info("No OneDrive prior snapshot available: %s", e)
        return None
