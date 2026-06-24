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
_DEFAULT_DAYS = 1  # hide for today, re-fires tomorrow unless re-actioned


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
    """Download registry from OneDrive. Returns {} on 404 or any error."""
    try:
        from src.onedrive_upload import download_file
        raw = download_file(tok, upn, f"{_FOLDER}/{_FNAME}")
        return json.loads(raw.decode("utf-8"))
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
    """Return True if the category+driver combo is suppressed on *today*."""
    entry = registry.get(_key(cat_norm, drv_norm))
    if not entry:
        return False
    try:
        return today < datetime.date.fromisoformat(entry["until"])
    except Exception:
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


def apply_resolved_to_registry(
    registry: dict,
    resolved_cats: set,
    all_items: list,
    today: datetime.date,
    cdl_dates: "dict | None" = None,
) -> None:
    """Suppress every item whose category or driver appears in *resolved_cats*.

    CDL Disqualified items use the reinstatement date from *cdl_dates* when
    available; all others are suppressed for _DEFAULT_DAYS.
    """
    cdl_dates = cdl_dates or {}
    for item in all_items:
        cat_norm = (item.get("category") or "").lower().strip()
        drv_norm = (item.get("driver") or item.get("unit") or "").lower().strip()
        actioned = (
            cat_norm in resolved_cats
            or (drv_norm and f"driver:{drv_norm}" in resolved_cats)
        )
        if not actioned:
            continue
        is_cdl = "cdl" in cat_norm or "disqualif" in cat_norm
        if is_cdl and drv_norm and drv_norm in cdl_dates:
            until = cdl_dates[drv_norm]
        else:
            until = today + datetime.timedelta(days=_DEFAULT_DAYS)
        add_suppression(registry, cat_norm, drv_norm, until, today=today)
