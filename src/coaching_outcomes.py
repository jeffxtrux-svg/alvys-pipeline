"""Coaching outcome tracker — closes the coaching loop.

Persists as Safety/coaching-outcomes.json on OneDrive. Tracks how long each
driver has been on the "coaching needed" list. A driver who remains on the
list 30+ days after first appearing is flagged as PERSISTENT — coaching
happened but the behavior hasn't changed.

Usage in the safety brief:
    tracker = load_tracker(tok, upn)
    update_tracker(tracker, current_coaching_drivers, today)
    persistent = get_persistent_drivers(tracker, today, threshold_days=30)
    save_tracker(tok, upn, tracker)
    # Render persistent list in the brief alongside the normal coaching table.

Schema per driver entry (keyed by normalized driver name):
    {
      "first_seen":   "YYYY-MM-DD",   # first date driver appeared on coaching list
      "last_seen":    "YYYY-MM-DD",   # most recent date they were still on the list
      "days_on_list": 0,              # calendar days since first_seen (resets on graduation)
    }

Graduation: when a driver leaves the coaching list, their entry is removed.
Re-appearance starts a fresh first_seen clock.
"""
from __future__ import annotations

import datetime
import json
import logging
import tempfile
from pathlib import Path

log = logging.getLogger("coaching_outcomes")

_FOLDER = "Safety"
_FNAME = "coaching-outcomes.json"
_PERSISTENT_DAYS = 30


# ---------------------------------------------------------------------------
# OneDrive persistence  (mirrors suppression_registry.py pattern)
# ---------------------------------------------------------------------------

def load_tracker(tok: str, upn: str) -> dict:
    """Download tracker from OneDrive. Returns {} on 404 or any error."""
    try:
        from src.onedrive_upload import download_file
        raw = download_file(tok, upn, f"{_FOLDER}/{_FNAME}")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            log.warning("coaching_outcomes: unexpected format — resetting.")
            return {}
        return data
    except Exception as exc:
        log.debug("coaching_outcomes: not loaded (%s) — starting empty.", exc)
        return {}


def save_tracker(tok: str, upn: str, tracker: dict) -> None:
    """Upload tracker to OneDrive."""
    try:
        from src.onedrive_upload import ensure_folder, upload_file
        ensure_folder(tok, upn, _FOLDER)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(tracker, tf, indent=2, sort_keys=True)
            tmp = Path(tf.name)
        upload_file(tok, upn, folder_path=_FOLDER, filename=_FNAME, file_path=tmp)
        tmp.unlink(missing_ok=True)
        log.info("coaching_outcomes: saved (%d drivers tracked).", len(tracker))
    except Exception as exc:
        log.warning("coaching_outcomes: could not save: %s", exc)


# ---------------------------------------------------------------------------
# Tracker operations
# ---------------------------------------------------------------------------

def _norm_name(name: str) -> str:
    return (name or "").strip().lower()


def update_tracker(
    tracker: dict,
    current_drivers: list[str],
    today: datetime.date,
) -> None:
    """Reconcile tracker against today's coaching-needed list.

    - Drivers present today: update last_seen, recalculate days_on_list.
    - Drivers absent today: remove their entry (coaching resolved).

    Modifies tracker in-place.
    """
    today_str = today.isoformat()
    current_normed = {_norm_name(d) for d in current_drivers if d}

    # Remove drivers no longer on the list.
    graduated = [k for k in list(tracker) if k not in current_normed]
    for k in graduated:
        log.info("coaching_outcomes: %s graduated (no longer on coaching list).", k)
        del tracker[k]

    # Add / update drivers still on the list.
    for norm_name in current_normed:
        if norm_name not in tracker:
            tracker[norm_name] = {
                "first_seen": today_str,
                "last_seen": today_str,
                "days_on_list": 0,
            }
            log.info("coaching_outcomes: new entry for %s.", norm_name)
        else:
            entry = tracker[norm_name]
            entry["last_seen"] = today_str
            try:
                first = datetime.date.fromisoformat(entry["first_seen"])
                entry["days_on_list"] = (today - first).days
            except Exception:
                entry["days_on_list"] = 0


def get_persistent_drivers(
    tracker: dict,
    today: datetime.date,
    threshold_days: int = _PERSISTENT_DAYS,
) -> list[dict]:
    """Return drivers who've been on the coaching list >= threshold_days.

    Each entry: {"name": <norm_name>, "first_seen": ..., "days_on_list": N}
    Sorted by days_on_list descending (longest-standing first).
    """
    out = []
    for norm_name, entry in tracker.items():
        days = entry.get("days_on_list", 0)
        if days >= threshold_days:
            out.append({
                "name": norm_name,
                "first_seen": entry.get("first_seen"),
                "days_on_list": days,
            })
    out.sort(key=lambda x: x["days_on_list"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_persistent_html(
    persistent: list[dict],
    *,
    red: str = "#c41e2a",
    mute: str = "#6b6b6b",
    line: str = "#ececec",
) -> str:
    """Compact warning panel listing drivers with 30+ days on coaching list.
    Returns "" when no persistent drivers exist (panel hidden, no clutter).
    """
    if not persistent:
        return ""

    rows = "".join(
        f"<tr>"
        f"<td style='padding:4px 12px 4px 0;font-size:12px;color:{red};font-weight:700;'>"
        f"{p['name'].title()}</td>"
        f"<td style='padding:4px 0;font-size:12px;color:{mute};'>"
        f"{p['days_on_list']}d on list (since {p['first_seen']})</td>"
        f"</tr>"
        for p in persistent
    )

    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fff8f8;"
        f"border:1px solid #f5c2c2;border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{red};text-transform:uppercase;margin-bottom:6px;'>"
        f"&#9888; Persistent Coaching Concern"
        f"</div>"
        f"<div style='font-size:11px;color:{mute};margin-bottom:8px;'>"
        f"These drivers have been on the coaching-needed list for 30+ days "
        f"&mdash; coaching occurred but behavior has not changed."
        f"</div>"
        f"<table style='border-collapse:collapse;'>{rows}</table>"
        f"</div>"
    )
