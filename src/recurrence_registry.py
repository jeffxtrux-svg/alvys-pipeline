"""Recurrence registry for safety accountability items.

Persists as Safety/recurrence-registry.json on OneDrive. Tracks each
category::driver item's appearance dates so flag_recurring_items can mark items
that have appeared 3+ times in the last 90 days.
"""
from __future__ import annotations

import datetime
import json
import logging
import tempfile
from pathlib import Path

log = logging.getLogger("recurrence_registry")

_FOLDER    = "Safety"
_FNAME     = "recurrence-registry.json"
_WINDOW    = 90
_THRESHOLD = 3


def load_registry(tok: str, upn: str) -> dict:
    try:
        from src.onedrive_upload import download_file
        raw = download_file(tok, upn, f"{_FOLDER}/{_FNAME}")
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        log.debug("Recurrence registry not loaded (%s) — starting empty.", exc)
        return {}


def save_registry(tok: str, upn: str, registry: dict) -> None:
    try:
        from src.onedrive_upload import ensure_folder, upload_file
        ensure_folder(tok, upn, _FOLDER)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(registry, tf, indent=2)
            tmp = Path(tf.name)
        upload_file(tok, upn, folder_path=_FOLDER, filename=_FNAME, file_path=tmp)
        tmp.unlink(missing_ok=True)
        log.info("Recurrence registry saved (%d entries).", len(registry))
    except Exception as exc:
        log.warning("Could not save recurrence registry: %s", exc)


def prune(registry: dict, today: datetime.date) -> None:
    """Remove appearance dates older than _WINDOW days; drop empty keys."""
    cutoff = (today - datetime.timedelta(days=_WINDOW)).isoformat()
    to_delete = []
    for k, v in registry.items():
        dates = [d for d in v.get("dates", []) if d >= cutoff]
        if dates:
            v["dates"] = dates
        else:
            to_delete.append(k)
    for k in to_delete:
        del registry[k]


def _key(item: dict) -> str:
    cat = (item.get("category") or "").lower().strip()
    drv = (item.get("driver") or item.get("unit") or "").lower().strip()
    return f"{cat}::{drv}"


def record_appearances(registry: dict, items: list, today: datetime.date) -> None:
    """Record that each item appeared today (idempotent — dedupes by date)."""
    date_str = today.isoformat()
    for item in items:
        k = _key(item)
        if k not in registry:
            registry[k] = {"dates": [], "first_seen": date_str}
        entry = registry[k]
        if date_str not in entry["dates"]:
            entry["dates"].append(date_str)


def flag_recurring_items(registry: dict, items: list, today: datetime.date) -> None:
    """Set item['_recurring'] = True for items with >= _THRESHOLD appearances in _WINDOW days."""
    cutoff = (today - datetime.timedelta(days=_WINDOW)).isoformat()
    for item in items:
        k = _key(item)
        entry = registry.get(k, {})
        count = sum(1 for d in entry.get("dates", []) if d >= cutoff)
        if count >= _THRESHOLD:
            item["_recurring"] = True
