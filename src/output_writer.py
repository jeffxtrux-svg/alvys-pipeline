"""
Write the three DataFrames (Loads, Trips, Fuel) into a single .xlsx file
matching the EXACT formatting of the original Alvys_Master.xlsx.

The original file (before this pipeline existed) stored date columns as TEXT
strings in MM-DD-YYYY format (e.g., "04-30-2026") or MM-DD-YYYY HH:MM format
(e.g., "04-30-2026 07:00"). The user's existing Power BI report has Power
Query "Changed Type" steps that convert those text strings into proper Date
type internally — which is what makes the between-slicers work.

If we write datetimes as native Excel datetime cells, Power BI's auto-detect
reads them as decimal numbers (the underlying Excel date serial), which
breaks all the existing visuals. So we mirror the original file's approach:
text dates that Power Query can convert.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Matches ISO 8601-style date / datetime strings:
#   2024-08-01
#   2024-08-01T07:00:00
#   2024-08-01T07:00:00.123
#   2024-08-01T07:00:00-05:00 / +00:00 / Z
#   2024-08-01 07:00:00
ISO_DATE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?)?$"
)


def _format_iso_as_text(value: str) -> str:
    """
    Convert one ISO date/datetime string to MM-DD-YYYY date-only text.

    The original Alvys_Master.xlsx wrote date columns as date-only strings
    (e.g., "04-30-2026"), and Power Query's "Changed Type" step is configured
    to parse them as Date — NOT DateTime. If we leave a time component on the
    string (e.g., "04-30-2026 13:00"), Power Query fails to convert the cell
    and marks it as an error. So we always strip the time, regardless of
    whether the source value had one.
    """
    if value is None or value == "":
        return value
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    except (TypeError, ValueError):
        return value
    if pd.isna(ts):
        return value
    # Always return date-only. If the source had a non-midnight UTC time,
    # we just take the calendar date (interpreted as the date in UTC for
    # midnight values, or in Central time for real timestamps).
    if ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%m-%d-%Y")
    local = ts.tz_convert("America/Chicago")
    return local.strftime("%m-%d-%Y")


def _reformat_iso_columns(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    """
    Find every column whose string values are mostly ISO 8601 timestamps,
    and reformat them as MM-DD-YYYY / MM-DD-YYYY HH:MM text strings —
    matching the original Alvys_Master.xlsx file.
    """
    reformatted: list[str] = []

    for col in df.columns:
        # Only consider object/string columns
        if df[col].dtype.kind != "O" and str(df[col].dtype) != "str":
            continue
        sample = df[col].dropna().astype(str).head(50)
        if len(sample) == 0:
            continue
        matches = sum(1 for v in sample if ISO_DATE_PATTERN.match(v))
        if matches < len(sample) * 0.7:
            continue

        df[col] = df[col].apply(
            lambda v: _format_iso_as_text(v) if isinstance(v, str) else v
        )
        reformatted.append(col)

    if reformatted:
        log.info(
            "  %s: reformatted %d ISO date columns → MM-DD-YYYY text",
            sheet_name, len(reformatted),
        )
        log.info("    columns: %s", ", ".join(reformatted))
    return df


def write_master_xlsx(
    loads_df: pd.DataFrame,
    trips_df: pd.DataFrame,
    fuel_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Write Loads/Trips/Fuel sheets in the same order as the original
    Alvys_Master.xlsx (Fuel first, then Loads, then Trips).

    Date columns are written as text in MM-DD-YYYY (or MM-DD-YYYY HH:MM)
    format — exactly like the original file. Power BI's existing Changed
    Type steps will convert these to Date type internally.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Writing %s", output_path)
    log.info("Reformatting ISO date strings to match original file format…")
    fuel_df  = _reformat_iso_columns(fuel_df,  "Fuel")
    loads_df = _reformat_iso_columns(loads_df, "Loads")
    trips_df = _reformat_iso_columns(trips_df, "Trips")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        fuel_df.to_excel(writer,  sheet_name="Fuel",  index=False)
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        trips_df.to_excel(writer, sheet_name="Trips", index=False)

    log.info("  Fuel : %d rows × %d cols", len(fuel_df),  len(fuel_df.columns))
    log.info("  Loads: %d rows × %d cols", len(loads_df), len(loads_df.columns))
    log.info("  Trips: %d rows × %d cols", len(trips_df), len(trips_df.columns))
    log.info("Done.")
