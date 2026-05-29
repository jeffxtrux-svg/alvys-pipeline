"""
Transform raw Alvys API responses into pandas DataFrames whose columns
match Alvys_Master.xlsx exactly.

Alvys API conventions observed in real responses:
  • PascalCase field names everywhere (LoadNumber, CustomerName, Stops, etc.)
  • Money values wrapped: {"Amount": 2000.0, "Currency": 840}
  • Distance values wrapped: {"Distance": {"Value": 1270.0, "UnitOfMeasure": "Miles"}, "Source": "..."}
  • Quantity values wrapped: {"Value": 174.11, "UnitOfMeasure": "Gallons"}
  • Stops are arrays — use "Stops.first.*" and "Stops.last.*"
  • Driver/Truck/Carrier appear as {Id, Fleet} only — names require separate
    lookup calls (handled in a future Phase 1.5 enrichment step)
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import pandas as pd

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Field path resolver
# ----------------------------------------------------------------------
def _ci_get(d: dict, key: str) -> Any:
    """Case-insensitive dict lookup."""
    if key in d:
        return d[key]
    key_lower = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == key_lower:
            return v
    return None


def _get_nested(obj: Any, path: str) -> Any:
    """
    Walk a dot-notation path through nested dicts/lists.
    Case-insensitive at every level. Supports 'Stops.first' and 'Stops.last'
    to grab the first/last element of a list. Returns None on any miss.
    """
    if obj is None or not path:
        return None
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        if part == "first" and isinstance(current, list):
            current = current[0] if current else None
            continue
        if part == "last" and isinstance(current, list):
            current = current[-1] if current else None
            continue
        if isinstance(current, dict):
            current = _ci_get(current, part)
        else:
            return None
    return current


# ----------------------------------------------------------------------
# Value unwrapping for Alvys-style nested-value blobs
# ----------------------------------------------------------------------
def _unwrap_value(v: Any) -> Any:
    """
    Alvys wraps money, distance, and quantity values in small dicts:
      {Amount: 643.22, Currency: 840}              → 643.22
      {Value: 174.11, UnitOfMeasure: "Gallons"}    → 174.11
      {Distance: {Value: 1270.0, ...}, Source:..}  → 1270.0
    """
    if not isinstance(v, dict):
        if isinstance(v, list):
            import json
            return json.dumps(v, default=str)
        return v

    keys = {k.lower(): k for k in v.keys() if isinstance(k, str)}

    # Money: {Amount, Currency} → Amount
    if "amount" in keys and len(v) <= 3:
        return v[keys["amount"]]
    # Distance wrapper: {Distance: {...}, Source, ProfileName} → inner Value
    if "distance" in keys:
        inner = v[keys["distance"]]
        if isinstance(inner, dict):
            inner_keys = {k.lower(): k for k in inner.keys() if isinstance(k, str)}
            if "value" in inner_keys:
                return inner[inner_keys["value"]]
        return inner
    # Quantity / generic value blob: {Value, UnitOfMeasure} → Value
    if "value" in keys and len(v) <= 3:
        return v[keys["value"]]

    # Unknown small dict — stringify so it lands in Excel as text
    import json
    return json.dumps(v, default=str)


# ----------------------------------------------------------------------
# Helper functions for computed columns
# ----------------------------------------------------------------------
def _first_stop_name(record: dict) -> Any:
    """Best-effort first stop name: CompanyName, Address.Street, or None."""
    stop = _get_nested(record, "Stops.first")
    if not isinstance(stop, dict):
        return None
    return _ci_get(stop, "CompanyName") or _get_nested(stop, "Address.Street")


def _last_stop_name(record: dict) -> Any:
    stop = _get_nested(record, "Stops.last")
    if not isinstance(stop, dict):
        return None
    return _ci_get(stop, "CompanyName") or _get_nested(stop, "Address.Street")


def _load_lane(record: dict) -> Any:
    """Format: 'City, ST → City, ST'"""
    pc = _get_nested(record, "Stops.first.Address.City")
    ps = _get_nested(record, "Stops.first.Address.State")
    dc = _get_nested(record, "Stops.last.Address.City")
    ds = _get_nested(record, "Stops.last.Address.State")
    if not (pc or dc):
        return None
    return f"{pc or '?'}, {ps or '?'} → {dc or '?'}, {ds or '?'}"


def _stop_fcfs(which: str, side: str):
    """Return a callable for FCFS window Begin/End on first/last stop."""
    def fn(record: dict) -> Any:
        stop = _get_nested(record, f"Stops.{which}")
        if not isinstance(stop, dict):
            return None
        if _ci_get(stop, "ScheduleType") != "FCFS":
            return None
        return _get_nested(stop, f"StopWindow.{side}")
    return fn


def _stop_appt(which: str):
    """Return a callable for AppointmentDate on first/last stop (APPT schedule type)."""
    def fn(record: dict) -> Any:
        stop = _get_nested(record, f"Stops.{which}")
        if not isinstance(stop, dict):
            return None
        if _ci_get(stop, "ScheduleType") != "APPT":
            return None
        return _ci_get(stop, "AppointmentDate")
    return fn


def _first_equipment(record: dict) -> Any:
    """RequiredEquipment is a list — take the first entry."""
    eq = _ci_get(record, "RequiredEquipment")
    if isinstance(eq, list) and eq:
        return eq[0]
    return None


# ----------------------------------------------------------------------
# Main transform
# ----------------------------------------------------------------------
def _resolve(record: dict, accessor: Any) -> Any:
    """
    Resolve a mapping accessor against a record. Accessor can be:
      - None         → returns None
      - str          → dot-notation path
      - callable     → called with the full record
    """
    if accessor is None:
        return None
    if callable(accessor):
        try:
            return accessor(record)
        except Exception as e:
            log.debug("Callable raised on accessor: %s", e)
            return None
    if isinstance(accessor, str):
        return _get_nested(record, accessor)
    return None


def transform_records(records: list[dict], column_map: list[tuple]) -> pd.DataFrame:
    """
    Apply column_map to a list of raw API records.
    column_map: list of (master_column_name, accessor) tuples.
    """
    cols = [name for name, _ in column_map]
    if not records:
        return pd.DataFrame(columns=cols)

    rows = []
    for record in records:
        row = {master_col: _resolve(record, accessor) for master_col, accessor in column_map}
        rows.append(row)

    df = pd.DataFrame(rows)[cols]
    df = df.map(_unwrap_value)
    log.info("  → produced %d rows × %d cols", len(df), len(df.columns))
    return df


def report_blank_columns(df: pd.DataFrame, sheet_name: str) -> None:
    if df.empty:
        return
    blank = [c for c in df.columns
             if df[c].isna().all() or (df[c].astype(str).str.strip() == "").all()]
    if blank:
        log.warning(
            "[%s] %d columns are entirely blank — check column_mappings.py:\n  %s",
            sheet_name, len(blank), ", ".join(blank)
        )


# ----------------------------------------------------------------------
# Schema drift detection for column_mappings.
# Catches the case where Alvys renames a JSON field: the column would
# silently go blank in Excel, but the *path* is wrong, not the data.
# report_blank_columns can't tell those apart — this can.
# ----------------------------------------------------------------------
def _ci_has(d: dict, key: str) -> bool:
    """Case-insensitive key-presence check (matches _ci_get's matching rules)."""
    if key in d:
        return True
    key_lower = key.lower()
    return any(isinstance(k, str) and k.lower() == key_lower for k in d.keys())


def _walk_with_trace(obj: Any, parts: list[str]) -> tuple:
    """Walk a dot-path part-by-part. Returns (resolved_value, break_idx,
    missing_key, parent_keys, reason).

    break_idx is -1 if the full path resolved. Otherwise it's the index in
    `parts` where the walk stopped. reason is one of:
      - "resolved"       — path fully resolved
      - "key_missing"    — parent is a dict and the requested key is absent
                           (this is the only "drift" signal)
      - "parent_is_none" — an intermediate step is None (legitimate empty data)
      - "non_dict"       — path expects a dict but a scalar was reached
      - "empty_list"     — `first`/`last` requested but the list is empty
    """
    current = obj
    for i, part in enumerate(parts):
        if current is None:
            return None, i, part, [], "parent_is_none"
        if part == "first" and isinstance(current, list):
            if not current:
                return None, i, part, [], "empty_list"
            current = current[0]
            continue
        if part == "last" and isinstance(current, list):
            if not current:
                return None, i, part, [], "empty_list"
            current = current[-1]
            continue
        if isinstance(current, dict):
            if not _ci_has(current, part):
                return None, i, part, list(current.keys()), "key_missing"
            current = _ci_get(current, part)
        else:
            return None, i, part, [], "non_dict"
    return current, -1, None, [], "resolved"


def find_drifted_paths(records: list[dict], column_map: list[tuple]) -> list[dict]:
    """Return the column_map entries whose string accessor points at a JSON
    key that no record actually has — i.e. Alvys renamed a field and the
    column would silently go blank.

    A path is flagged only when (a) zero records resolve it AND (b) at least
    one record's parent dict was reachable but the requested key was absent.
    Empty/None intermediates don't count: that's just empty data, not drift.
    Callable and None accessors are skipped (can't be statically validated).

    Each item: {column, path, broken_at, missing_key, siblings}.
    """
    if not records:
        return []
    out: list[dict] = []
    for col, accessor in column_map:
        if not isinstance(accessor, str) or not accessor:
            continue
        parts = accessor.split(".")
        any_resolved = False
        deepest_drift: dict | None = None
        for rec in records:
            _, break_idx, missing, parent_keys, reason = _walk_with_trace(rec, parts)
            if break_idx < 0:
                any_resolved = True
                break  # one good record clears the path
            if reason == "key_missing":
                if deepest_drift is None or break_idx > deepest_drift["break_idx"]:
                    deepest_drift = {
                        "break_idx": break_idx,
                        "missing": missing,
                        "siblings": sorted(str(k) for k in parent_keys),
                    }
        if not any_resolved and deepest_drift is not None:
            broken_at = ".".join(parts[: deepest_drift["break_idx"]]) or "(root)"
            out.append({
                "column": col,
                "path": accessor,
                "broken_at": broken_at,
                "missing_key": deepest_drift["missing"],
                "siblings": deepest_drift["siblings"],
            })
    return out


def report_schema_drift(records: list[dict], column_map: list[tuple], sheet_name: str) -> list[dict]:
    """Log a WARNING per drifted path. Returns the drift list (for tests /
    aggregation). Pair this with report_blank_columns: drift explains *why*
    a column is blank when nothing in the data should have made it blank."""
    drifts = find_drifted_paths(records, column_map)
    if not drifts:
        return drifts
    log.warning(
        "[%s] SCHEMA DRIFT — %d column path(s) point at keys that no records have. "
        "Alvys likely renamed a field:",
        sheet_name, len(drifts),
    )
    for d in drifts:
        sibs = d["siblings"]
        shown = ", ".join(sibs[:8]) or "(parent dict empty)"
        if len(sibs) > 8:
            shown += f", … (+{len(sibs) - 8} more)"
        log.warning(
            "  - column \"%s\" — path \"%s\" broke at \"%s\": key \"%s\" missing. "
            "Sibling keys present: %s",
            d["column"], d["path"], d["broken_at"], d["missing_key"], shown,
        )
    return drifts
