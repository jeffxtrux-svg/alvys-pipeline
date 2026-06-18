"""Per-category suppression registry for safety accountability items.

Stored as Safety/suppression-registry.json in OneDrive.  The morning brief
loads this registry before building today's accountability JSON and skips any
item whose suppression window has not yet expired.

Smart suppression windows by category:
  Driver License Expiring / DOT Medical Card
      → Suppress until 3 days before the expiration date (using _expires_iso
        stored on the item).  Within the 3-day window the item stays on
        every day until the license/card is renewed in the source system.
  CDL Disqualified
      → Suppress until the reinstatement date entered in the form's Action
        Taken / Notes field (parsed by _load_accountability_log).  Falls back
        to 1 day if no date was found.
  DOT Inspection — Tractor / Trailer
      → 7-day suppression when an appointment is scheduled.  No suppression
        at all when the unit is federally out of service (365 days since last
        inspection, flagged by _federal_oos=True on the item).
  MVR Violation
      → 1 day (actioned / challenged; recheck tomorrow vs. live SambaSafety).
  HOS Violation
      → 1 day per occurrence; a new violation the next day is a new item.
  DVIR Compliance / Speeding / Low Safety Score
      → 7-day coaching grace period before the item refires.
  SambaSafety Risk Flag (high-risk leaderboard)
      → 180 days (6-month hold after action plan is filed).
  Safety Event Coaching / DVIR Defects / Prior-Day Log Certification
      → Never suppressed here; Samsara data drives their removal naturally.
"""
from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_FOLDER   = "Safety"
_FILENAME = "suppression-registry.json"
_OD_PATH  = f"{_FOLDER}/{_FILENAME}"

# Fallback window (days) for categories without smart logic.
# Categories absent from this dict AND not handled by add_suppression_smart
# are never suppressed via the registry.
_FALLBACK_DAYS: dict[str, int] = {
    "cdl disqualified":          1,    # overridden by reinstatement date if provided
    "driver license expiring":   1,    # overridden by expiry-date logic
    "dot medical card":          1,    # overridden by expiry-date logic
    "mvr violation":             1,
    "dot inspection — tractor":  7,    # overridden; blocked when federal OOS
    "dot inspection — trailer":  7,    # overridden; blocked when federal OOS
    "hos violation":             1,
    "dvir compliance":           7,
    "speeding":                  7,
    "low safety score":          7,
    "sambasafety risk flag":   180,
}

# Days before expiry at which License / Med Card items reappear and stay on.
_LICENSE_REFIRE_DAYS = 3


def load_registry(tok: str, upn: str) -> dict:
    """Load from OneDrive. Returns an empty registry dict on any failure."""
    try:
        from src.onedrive_upload import download_file
        data = json.loads(download_file(tok, upn, _OD_PATH))
        data.setdefault("suppressions", [])
        return data
    except Exception as exc:
        log.info("Suppression registry not found or unreadable (%s) — starting fresh.", exc)
        return {"suppressions": []}


def save_registry(tok: str, upn: str, registry: dict) -> None:
    """Save registry to OneDrive. Fails soft — logs warning on error."""
    try:
        from src.onedrive_upload import ensure_folder, upload_file
        tmp = Path("output") / _FILENAME
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(registry, indent=2, default=str))
        ensure_folder(tok, upn, _FOLDER)
        upload_file(tok, upn, folder_path=_FOLDER, filename=_FILENAME, file_path=tmp)
        log.info("Suppression registry saved (%d active entries).",
                 len(registry.get("suppressions", [])))
    except Exception as exc:
        log.warning("Could not save suppression registry: %s", exc)


def prune(registry: dict, today: datetime.date) -> None:
    """Remove entries whose window has expired (suppressed_until <= today)."""
    before = len(registry.get("suppressions", []))
    registry["suppressions"] = [
        s for s in registry.get("suppressions", [])
        if datetime.date.fromisoformat(s["suppressed_until"]) > today
    ]
    removed = before - len(registry["suppressions"])
    if removed:
        log.info("Pruned %d expired suppression entries.", removed)


def is_suppressed(
    registry: dict,
    category: str,
    subject: str,
    today: datetime.date,
) -> bool:
    """Return True if this (category, subject) pair is actively suppressed.

    subject is the driver name OR unit string, lowercased.  Pass "" for
    aggregate items (e.g. HOS Violation with no specific driver attached).
    """
    cat_norm  = (category or "").lower().strip()
    subj_norm = (subject  or "").lower().strip()
    for s in registry.get("suppressions", []):
        if s.get("category") == cat_norm and s.get("subject") == subj_norm:
            try:
                until = datetime.date.fromisoformat(s["suppressed_until"])
            except Exception:
                continue
            if today < until:
                return True
    return False


def _set_suppression(
    registry: dict,
    cat_norm: str,
    subj_norm: str,
    until_iso: str,
    today: datetime.date,
) -> None:
    """Insert or update a suppression entry with an explicit until date."""
    for s in registry.get("suppressions", []):
        if s.get("category") == cat_norm and s.get("subject") == subj_norm:
            s["suppressed_until"] = until_iso
            s["suppressed_on"]    = today.isoformat()
            log.info("Suppression refreshed: [%s / %s] → until %s",
                     cat_norm, subj_norm, until_iso)
            return
    registry.setdefault("suppressions", []).append({
        "category":         cat_norm,
        "subject":          subj_norm,
        "suppressed_until": until_iso,
        "suppressed_on":    today.isoformat(),
    })
    log.info("Suppression added: [%s / %s] → until %s", cat_norm, subj_norm, until_iso)


def add_suppression(
    registry: dict,
    category: str,
    subject: str,
    today: datetime.date,
) -> None:
    """Add or refresh a suppression using the standard fallback window.

    No-ops if the category has no entry in _FALLBACK_DAYS.
    """
    cat_norm  = (category or "").lower().strip()
    subj_norm = (subject  or "").lower().strip()
    days = _FALLBACK_DAYS.get(cat_norm)
    if not days:
        return
    until = (today + datetime.timedelta(days=days)).isoformat()
    _set_suppression(registry, cat_norm, subj_norm, until, today)


def extract_date_from_text(text: str) -> "datetime.date | None":
    """Parse the first date found in free text (M/D/YY, MM/DD/YYYY, YYYY-MM-DD)."""
    if not text:
        return None
    # ISO date first (unambiguous)
    m = re.search(r'\b(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})\b', text)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    # MM/DD/YY or MM/DD/YYYY
    m = re.search(r'\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b', text)
    if m:
        try:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000
            return datetime.date(y, mo, d)
        except Exception:
            pass
    return None


def add_suppression_smart(
    registry: dict,
    item: dict,
    today: datetime.date,
    cdl_dates: "dict[str, datetime.date] | None" = None,
) -> None:
    """Add suppression using per-category smart windows.

    item must be a dict from the accountability JSON with at minimum a
    "category" key and optionally "driver", "unit", "_expires_iso",
    "_federal_oos".

    cdl_dates maps drv_norm → reinstatement_date parsed from form notes.
    """
    cat_norm  = (item.get("category") or "").lower().strip()
    subj_norm = (item.get("driver") or item.get("unit") or "").lower().strip()

    if cat_norm in ("driver license expiring", "dot medical card"):
        # Suppress until _LICENSE_REFIRE_DAYS before expiry so the item stays
        # quiet while the appointment is pending, then reappears as the deadline
        # approaches and remains until the source system shows renewal.
        expires_iso = item.get("_expires_iso")
        if expires_iso:
            try:
                expiry = datetime.date.fromisoformat(expires_iso)
                until  = expiry - datetime.timedelta(days=_LICENSE_REFIRE_DAYS)
                if until > today:
                    _set_suppression(registry, cat_norm, subj_norm,
                                     until.isoformat(), today)
                    return
                # Already inside the 3-day window — don't suppress so it
                # appears every day until renewed.
                log.info("Within %dd of expiry — no suppression for [%s / %s].",
                         _LICENSE_REFIRE_DAYS, cat_norm, subj_norm)
                return
            except Exception:
                pass
        # No expiry date in item data — fall back to 1 day
        add_suppression(registry, cat_norm, subj_norm, today)

    elif cat_norm == "cdl disqualified":
        # Use the reinstatement date entered in the form's Action / Notes field
        # if it was found and is in the future; otherwise 1-day recheck.
        reinstate = (cdl_dates or {}).get(subj_norm)
        if reinstate and isinstance(reinstate, datetime.date) and reinstate > today:
            _set_suppression(registry, cat_norm, subj_norm,
                             reinstate.isoformat(), today)
        else:
            add_suppression(registry, cat_norm, subj_norm, today)  # 1-day fallback

    elif cat_norm in ("dot inspection — tractor", "dot inspection — trailer"):
        # Federally OOS units (365 days since last inspection) cannot be
        # suppressed — they stay on the card until the inspection is done.
        if item.get("_federal_oos"):
            log.info("DOT Inspection [%s / %s] is federal OOS — not suppressible.",
                     cat_norm, subj_norm)
            return
        # Appointment scheduled: 7-day grace before refiring.
        until = (today + datetime.timedelta(days=7)).isoformat()
        _set_suppression(registry, cat_norm, subj_norm, until, today)

    else:
        add_suppression(registry, cat_norm, subj_norm, today)


def apply_resolved_to_registry(
    registry: dict,
    resolved_tokens: "set[str]",
    all_items: "list[dict]",
    today: datetime.date,
    cdl_dates: "dict[str, datetime.date] | None" = None,
) -> None:
    """For each accountability item matched by resolved_tokens, add a suppression.

    resolved_tokens — flat set from _load_accountability_log / _load_resolved_today:
        lowercased category names and "driver:<name>" strings.
    all_items — combined audra + ops list from the accountability JSON.
        Items carry _expires_iso / _federal_oos metadata set by
        _build_accountability_structured.
    cdl_dates — drv_norm → reinstatement date parsed from form notes.
    """
    if not resolved_tokens:
        return
    seen: set[tuple[str, str]] = set()
    for item in all_items:
        cat_norm  = (item.get("category") or "").lower().strip()
        subj_norm = (item.get("driver") or item.get("unit") or "").lower().strip()
        matched = (
            cat_norm in resolved_tokens
            or (subj_norm and f"driver:{subj_norm}" in resolved_tokens)
        )
        if matched:
            key = (cat_norm, subj_norm)
            if key not in seen:
                seen.add(key)
                add_suppression_smart(registry, item, today, cdl_dates=cdl_dates)
