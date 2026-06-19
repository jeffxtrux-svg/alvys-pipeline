"""90-day recurrence tracking for accountability items.

Stored as Safety/recurrence-registry.json on OneDrive. Each entry is a
single dated appearance of a (category, subject) pair. When the same pair
appears 3+ times in 90 days the item is flagged for formal progressive
discipline — this complements the 30-day occurrence counter (which drives
verbal/written warnings within a calendar month) by catching patterns that
span months.

Chronology of escalation levels (both systems work together):
  1st–2nd in 30d   → coaching conversation (from 30-day occurrence counter)
  3rd in 30d       → written warning (from 30-day counter)
  3rd+ in 90d      → formal progressive discipline flag (this module)
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_FOLDER      = "Safety"
_FILENAME    = "recurrence-registry.json"
_OD_PATH     = f"{_FOLDER}/{_FILENAME}"
WINDOW_DAYS  = 90
THRESHOLD    = 3


def load_registry(tok: str, upn: str) -> dict:
    """Load from OneDrive. Returns empty registry on any failure."""
    try:
        from src.onedrive_upload import download_file
        data = json.loads(download_file(tok, upn, _OD_PATH))
        data.setdefault("occurrences", [])
        return data
    except Exception as exc:
        log.info("Recurrence registry not found (%s) — starting fresh.", exc)
        return {"occurrences": []}


def save_registry(tok: str, upn: str, registry: dict) -> None:
    """Save to OneDrive. Fails soft."""
    try:
        from src.onedrive_upload import ensure_folder, upload_file
        tmp = Path("output") / _FILENAME
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(registry, indent=2, default=str))
        ensure_folder(tok, upn, _FOLDER)
        upload_file(tok, upn, folder_path=_FOLDER, filename=_FILENAME, file_path=tmp)
        log.info("Recurrence registry saved (%d entries).", len(registry.get("occurrences", [])))
    except Exception as exc:
        log.warning("Could not save recurrence registry: %s", exc)


def prune(registry: dict, today: datetime.date) -> None:
    """Drop entries older than WINDOW_DAYS."""
    cutoff = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    before = len(registry.get("occurrences", []))
    registry["occurrences"] = [
        o for o in registry.get("occurrences", [])
        if o.get("date", "") >= cutoff
    ]
    removed = before - len(registry["occurrences"])
    if removed:
        log.info("Pruned %d expired recurrence entries.", removed)


def _norm(s: str) -> str:
    return (s or "").lower().strip()


def record_appearances(
    registry: dict,
    items: "list[dict]",
    today: datetime.date,
) -> None:
    """Record today's accountability items (idempotent — won't double-count same day)."""
    today_iso = today.isoformat()
    already = {
        (o["category"], o["subject"])
        for o in registry.get("occurrences", [])
        if o.get("date") == today_iso
    }
    new_entries = []
    for item in items:
        cat  = _norm(item.get("category"))
        subj = _norm(item.get("driver") or item.get("unit") or "")
        if (cat, subj) not in already:
            already.add((cat, subj))
            new_entries.append({"category": cat, "subject": subj, "date": today_iso})
    registry.setdefault("occurrences", []).extend(new_entries)
    if new_entries:
        log.info("Recorded %d new recurrence appearances for %s.", len(new_entries), today_iso)


def get_count(
    registry: dict,
    category: str,
    subject: str,
    since: datetime.date,
) -> int:
    """Count appearances of (category, subject) on or after since."""
    cat_n     = _norm(category)
    subj_n    = _norm(subject)
    since_iso = since.isoformat()
    return sum(
        1 for o in registry.get("occurrences", [])
        if o.get("category") == cat_n
        and o.get("subject") == subj_n
        and o.get("date", "") >= since_iso
    )


def get_first_seen(
    registry: dict,
    category: str,
    subject: str,
) -> "datetime.date | None":
    """Earliest date this (category, subject) appears in the registry."""
    cat_n  = _norm(category)
    subj_n = _norm(subject)
    dates = [
        o["date"] for o in registry.get("occurrences", [])
        if o.get("category") == cat_n and o.get("subject") == subj_n
    ]
    if not dates:
        return None
    try:
        return datetime.date.fromisoformat(min(dates))
    except Exception:
        return None


def flag_recurring_items(
    registry: dict,
    items: "list[dict]",
    today: datetime.date,
) -> "list[dict]":
    """Annotate items with _recurring, _recurrence_count, _first_seen_days.

    _recurring         True when count >= THRESHOLD in the 90-day window.
    _recurrence_count  Raw 90-day count (always set).
    _first_seen_days   Days since first appearance in the registry (for
                       coaching escalation timer — set on all items).

    Mutates items in place and returns the list.
    """
    since = today - datetime.timedelta(days=WINDOW_DAYS)
    for item in items:
        cat   = item.get("category", "")
        subj  = item.get("driver") or item.get("unit") or ""
        count = get_count(registry, cat, subj, since)
        first = get_first_seen(registry, cat, subj)
        item["_recurrence_count"] = count
        item["_first_seen_days"]  = (today - first).days if first else 0
        if count >= THRESHOLD:
            item["_recurring"] = True
            log.info("Recurring flag: [%s / %s] — %d appearances in 90d", cat, subj, count)
    return items
