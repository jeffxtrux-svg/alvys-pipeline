"""Suppression registry for safety accountability items.

Persists as Safety/suppression-registry.json on OneDrive. Each entry maps a
category::driver key to an ISO-date 'until' field — is_suppressed returns True
while today < until, so the item is hidden from Teams cards and not counted as
open in the brief.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
import tempfile
from pathlib import Path

log = logging.getLogger("suppression_registry")

_FOLDER       = "Safety"
_FNAME        = "suppression-registry.json"
_DEFAULT_DAYS = 30  # once actioned, suppress for 30 days (matches history window)


# ---------------------------------------------------------------------------
# Date extraction from free text
# ---------------------------------------------------------------------------

_DATE_PATTERNS = [
    r"\b(\d{4}-\d{2}-\d{2})\b",
    r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
    r"\b(\d{1,2}-\d{1,2}-\d{4})\b",
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},?\s+\d{4})\b",
]
_DATE_FMTS = [
    "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y",
    "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
]


def extract_date_from_text(text: str) -> datetime.date | None:
    """Return the first recognisable date found in *text*, or None."""
    if not text:
        return None
    for pat in _DATE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1)
        for fmt in _DATE_FMTS:
            try:
                return datetime.datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# OneDrive persistence
# ---------------------------------------------------------------------------

def load_registry(tok: str, upn: str) -> dict:
    """Download registry from OneDrive. Returns {} on 404 or any error.

    Validates that every value is a dict with an 'until' key. If the file
    exists but contains an old/incompatible format (e.g. list values from a
    prior implementation), discards it and starts fresh — old entries would
    have expired anyway.
    """
    try:
        from src.onedrive_upload import download_file
        raw = download_file(tok, upn, f"{_FOLDER}/{_FNAME}")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            log.warning("Suppression registry has unexpected type %s — resetting.", type(data).__name__)
            return {}
        # Discard entries that don't have the expected {"until": ..., "added": ...} shape.
        valid = {
            k: v for k, v in data.items()
            if isinstance(v, dict) and "until" in v
        }
        if len(valid) != len(data):
            log.warning(
                "Suppression registry: %d/%d entries had old format — discarded.",
                len(data) - len(valid), len(data),
            )
        return valid
    except Exception as exc:
        log.debug("Suppression registry not loaded (%s) — starting empty.", exc)
        return {}


def save_registry(tok: str, upn: str, registry: dict) -> None:
    """Upload registry to OneDrive."""
    try:
        from src.onedrive_upload import ensure_folder, upload_file
        ensure_folder(tok, upn, _FOLDER)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
            json.dump(registry, tf, indent=2)
            tmp = Path(tf.name)
        upload_file(tok, upn, folder_path=_FOLDER, filename=_FNAME, file_path=tmp)
        tmp.unlink(missing_ok=True)
        log.info("Suppression registry saved (%d entries).", len(registry))
    except Exception as exc:
        log.warning("Could not save suppression registry: %s", exc)


# ---------------------------------------------------------------------------
# Registry operations
# ---------------------------------------------------------------------------

def prune(registry: dict, today: datetime.date) -> None:
    """Remove entries whose window has expired (until <= today)."""
    expired = [
        k for k, v in registry.items()
        if datetime.date.fromisoformat(v["until"]) <= today
    ]
    for k in expired:
        del registry[k]
    if expired:
        log.info("Pruned %d expired suppression entries.", len(expired))


def _key(cat_norm: str, drv_norm: str) -> str:
    return f"{cat_norm}::{drv_norm}"


def is_suppressed(
    registry: dict,
    cat_norm: str,
    drv_norm: str,
    today: datetime.date,
) -> bool:
    """Return True if the category+driver combo is suppressed on *today*.

    Checks the specific cat::drv key first; falls back to the category-only
    wildcard key (cat::) so a category-level resolution suppresses all drivers
    in that category even when the log's driver field didn't match exactly.
    """
    for k in (_key(cat_norm, drv_norm), _key(cat_norm, "")):
        entry = registry.get(k)
        if not entry:
            continue
        try:
            if today < datetime.date.fromisoformat(entry["until"]):
                return True
        except Exception:
            continue
    return False


def add_suppression(
    registry: dict,
    cat_norm: str,
    drv_norm: str,
    until: datetime.date,
    today: datetime.date | None = None,
) -> None:
    """Add or extend a suppression window. No-op if already suppressed longer."""
    k = _key(cat_norm, drv_norm)
    existing = registry.get(k)
    if existing:
        try:
            if datetime.date.fromisoformat(existing["until"]) >= until:
                return
        except Exception:
            pass
    registry[k] = {
        "until": until.isoformat(),
        "added": (today or datetime.date.today()).isoformat(),
    }
    log.info("Suppression added: [%s / %s] until %s", cat_norm, drv_norm, until.isoformat())


def rebuild_from_accountability_log(
    registry: dict,
    tok: str,
    upn: str,
    today: datetime.date,
    acc_folder: str = "Safety",
    acc_filename: str = "Accountability Log.xlsx",
    suppress_days: int = _DEFAULT_DAYS,
) -> int:
    """Backfill suppressions from the full Accountability Log history.

    Called when the registry is empty (first run or after a reset) so that
    items actioned in previous weeks don't flood back. Reads every row in
    Accountability Log.xlsx and adds a suppression for any action within the
    last suppress_days days, setting until = action_date + suppress_days.
    Returns the number of suppressions added.
    """
    try:
        import io
        import pandas as pd
        from src.onedrive_upload import download_file
        raw = download_file(tok, upn, f"{acc_folder}/{acc_filename}")
        xl  = pd.ExcelFile(io.BytesIO(raw))
        df  = xl.parse(xl.sheet_names[0])
        df.columns = [str(c).strip().lower() for c in df.columns]
        date_col = next((c for c in df.columns if "date" in c), None)
        cat_col  = next((c for c in df.columns if "category" in c), None)
        drv_col  = next((c for c in df.columns if "driver" in c or "unit" in c), None)
        if date_col is None:
            log.warning("rebuild_from_accountability_log: date column not found — skipping.")
            return 0
        cutoff = today - datetime.timedelta(days=suppress_days)
        added = 0
        for _, row in df.iterrows():
            try:
                row_date = pd.Timestamp(row[date_col]).date()
            except Exception:
                continue
            if row_date < cutoff or row_date > today:
                continue
            cat_norm = (str(row[cat_col]).strip().lower() if cat_col else "")
            drv_norm = (str(row[drv_col]).strip().lower() if drv_col else "")
            if cat_norm in ("", "nan") and drv_norm in ("", "nan"):
                continue
            until = row_date + datetime.timedelta(days=suppress_days)
            if until <= today:
                continue
            # Always write category-only wildcard so is_suppressed can match even
            # when the log's driver field (ID, blank, etc.) differs from the
            # item's actual driver name.
            if cat_norm not in ("", "nan"):
                add_suppression(registry, cat_norm, "", until, today=row_date)
            # Also write specific cat::drv entry when driver is available.
            if drv_norm not in ("", "nan"):
                add_suppression(registry, cat_norm, drv_norm, until, today=row_date)
            added += 1
        log.info("Rebuilt %d suppression(s) from accountability log history.", added)
        return added
    except Exception as exc:
        log.warning("Could not rebuild suppressions from log: %s", exc)
        return 0


def apply_resolved_to_registry(
    registry: dict,
    resolved_cats: set,
    all_items: list,
    today: datetime.date,
    cdl_dates: "dict | None" = None,
    dot_dates: "dict | None" = None,
) -> None:
    """Suppress every item whose category or driver appears in *resolved_cats*.

    CDL Disqualified items use the reinstatement date from *cdl_dates* when
    available.  DOT Inspection items are suppressed for 7 days past the
    scheduled inspection date in *dot_dates* (or 7 days from today if no date
    was recorded).  All others are suppressed for _DEFAULT_DAYS.
    """
    cdl_dates = cdl_dates or {}
    dot_dates = dot_dates or {}
    # Track which categories we've already written a wildcard for this run.
    _cat_wildcard_written: set = set()
    for item in all_items:
        cat_norm = (item.get("category") or "").lower().strip()
        drv_norm = (item.get("driver") or item.get("unit") or "").lower().strip()
        cat_actioned = cat_norm in resolved_cats
        drv_actioned = drv_norm and f"driver:{drv_norm}" in resolved_cats
        if not (cat_actioned or drv_actioned):
            continue
        is_cdl = "cdl" in cat_norm or "disqualif" in cat_norm
        is_dot = "dot inspection" in cat_norm
        if is_cdl and drv_norm and drv_norm in cdl_dates:
            until = cdl_dates[drv_norm]
        elif is_dot:
            # Use the scheduled inspection date + 7 days when the log captured one;
            # otherwise suppress for 7 days from today as a safe fallback.
            sched = dot_dates.get(drv_norm)
            until = (sched + datetime.timedelta(days=7)) if sched else (today + datetime.timedelta(days=7))
        else:
            until = today + datetime.timedelta(days=_DEFAULT_DAYS)
        add_suppression(registry, cat_norm, drv_norm, until, today=today)
        # When the log resolved this category explicitly, also write a wildcard
        # (cat::"") so tomorrow's is_suppressed catches any driver in the same
        # category even if the log driver field didn't match exactly.
        # CDL and DOT Inspection are excluded — each unit/driver has its own
        # schedule and actioning one must not suppress others in the category.
        if cat_actioned and not is_cdl and not is_dot and cat_norm not in _cat_wildcard_written:
            add_suppression(registry, cat_norm, "", until, today=today)
            _cat_wildcard_written.add(cat_norm)
