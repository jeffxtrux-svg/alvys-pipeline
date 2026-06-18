"""Per-category suppression registry for safety accountability items.

Stored as Safety/suppression-registry.json in OneDrive.  The morning brief
loads this registry before building today's accountability JSON and skips any
item whose suppression window has not yet expired.

Suppression windows (days) by category — all lowercase to match item["category"]:
  1 day   — standard "acknowledge and remove" items (license, med card, CDL,
             MVR violation, DOT inspection, HOS violation per occurrence).
  7 days  — behavioral coaching items (DVIR compliance, speeding, low safety score).
 180 days — SambaSafety high-risk leaderboard (action plan filed; 6-month hold).
  none    — Samsara-data-driven items (coaching events, DVIR defects, prior-day
             log certification) are never suppressed here; Samsara's own
             coached/dismissed status removes them naturally.
"""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_FOLDER   = "Safety"
_FILENAME = "suppression-registry.json"
_OD_PATH  = f"{_FOLDER}/{_FILENAME}"

# Maps lowercase category name → suppression window in days.
# Categories absent from this dict are never suppressed via the registry.
SUPPRESSION_DAYS: dict[str, int] = {
    "cdl disqualified":          1,
    "driver license expiring":   1,
    "dot medical card":          1,
    "mvr violation":             1,
    "dot inspection — tractor":  1,
    "dot inspection — trailer":  1,
    "hos violation":             1,    # per-occurrence; dispositioned → gone tomorrow
    "dvir compliance":           7,    # coached; 7-day grace before refire
    "speeding":                  7,    # coached; 7-day grace before refire
    "low safety score":          7,    # coaching plan started; 7-day grace
    "sambasafety risk flag":   180,    # action plan filed; 6-month hold
}


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


def add_suppression(
    registry: dict,
    category: str,
    subject: str,
    today: datetime.date,
) -> None:
    """Add or refresh a suppression for (category, subject).

    No-ops if the category has no entry in SUPPRESSION_DAYS.
    subject is the driver name OR unit string, lowercased.
    """
    cat_norm  = (category or "").lower().strip()
    subj_norm = (subject  or "").lower().strip()
    days = SUPPRESSION_DAYS.get(cat_norm)
    if not days:
        return  # category is not suppression-eligible

    until = (today + datetime.timedelta(days=days)).isoformat()
    for s in registry.get("suppressions", []):
        if s.get("category") == cat_norm and s.get("subject") == subj_norm:
            s["suppressed_until"] = until
            s["suppressed_on"]    = today.isoformat()
            log.info("Suppression refreshed: [%s / %s] → until %s", cat_norm, subj_norm, until)
            return

    registry.setdefault("suppressions", []).append({
        "category":         cat_norm,
        "subject":          subj_norm,
        "suppressed_until": until,
        "suppressed_on":    today.isoformat(),
    })
    log.info("Suppression added: [%s / %s] → until %s", cat_norm, subj_norm, until)


def apply_resolved_to_registry(
    registry: dict,
    resolved_tokens: "set[str]",
    all_items: "list[dict]",
    today: datetime.date,
) -> None:
    """For each accountability item matched by resolved_tokens, add a suppression.

    resolved_tokens is the flat set from _load_accountability_log or
    _load_resolved_today: contains lowercased category names and
    "driver:<name>" strings.

    all_items is the combined audra + ops list from the accountability JSON
    (used to get the canonical category for driver-matched items, since the
    form often submits "Other" as the category but fills in the driver name).
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
                add_suppression(registry, cat_norm, subj_norm, today)
