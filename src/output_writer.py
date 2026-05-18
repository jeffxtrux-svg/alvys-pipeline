"""
Write the three DataFrames (Loads, Trips, Fuel) into a single .xlsx file
with the same sheet structure as Alvys_Master.xlsx.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Matches ISO 8601-style date or datetime strings:
#   2024-08-01
#   2024-08-01T07:00:00
#   2024-08-01T07:00:00.123
#   2024-08-01T07:00:00-05:00
#   2024-08-01T07:00:00+00:00
#   2024-08-01 07:00:00
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?)?$")


def _convert_iso_date_columns(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    """
    Find columns whose string values look like ISO 8601 dates and convert
    them to pandas datetime, so openpyxl writes Excel datetime cells (not text).

    Power BI and Excel can then treat these columns as real dates for slicers,
    filters, and date-axis charts.

    Strategy:
      • Only consider object-dtype columns
      • Sample up to 50 non-null values
      • If at least 70% of sampled values match the ISO pattern, convert
      • Use UTC parsing then convert to America/Chicago and strip tz
        (matches the user's local time, which is how the manual file worked)
    """
    converted = []
    for col in df.columns:
        # Accept both legacy object dtype and newer str dtype in pandas 2.x
        if df[col].dtype.kind not in ("O",) and str(df[col].dtype) != "str":
            continue
        sample = df[col].dropna().astype(str).head(50)
        if len(sample) == 0:
            continue
        matches = sum(1 for v in sample if ISO_DATE_PATTERN.match(v))
        if matches < len(sample) * 0.7:
            continue
        try:
            parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
            # Convert to Central time, then drop tz info (Excel doesn't support tz)
            df[col] = parsed.dt.tz_convert("America/Chicago").dt.tz_localize(None)
            converted.append(col)
        except (TypeError, ValueError) as e:
            log.warning("  %s: couldn't convert column %r as dates: %s",
                        sheet_name, col, e)
    if converted:
        log.info("  %s: converted %d columns to datetime: %s",
                 sheet_name, len(converted), ", ".join(converted))
    return df


def write_master_xlsx(
    loads_df: pd.DataFrame,
    trips_df: pd.DataFrame,
    fuel_df: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Write Loads/Trips/Fuel sheets in the same order as the original
    Alvys_Master.xlsx (Fuel first, then Loads, then Trips — confirmed
    from inspection of the source file).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Writing %s", output_path)
    log.info("Converting ISO date strings to datetime cells…")
    fuel_df  = _convert_iso_date_columns(fuel_df,  "Fuel")
    loads_df = _convert_iso_date_columns(loads_df, "Loads")
    trips_df = _convert_iso_date_columns(trips_df, "Trips")

    # Apply explicit datetime format so Power Query / Power BI recognizes
    # these columns as Date/DateTime (not as raw numeric serial values).
    with pd.ExcelWriter(
        output_path,
        engine="openpyxl",
        datetime_format="mm/dd/yyyy hh:mm:ss",
        date_format="mm/dd/yyyy",
    ) as writer:
        fuel_df.to_excel(writer, sheet_name="Fuel", index=False)
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        trips_df.to_excel(writer, sheet_name="Trips", index=False)

    log.info("  Fuel : %d rows × %d cols", len(fuel_df), len(fuel_df.columns))
    log.info("  Loads: %d rows × %d cols", len(loads_df), len(loads_df.columns))
    log.info("  Trips: %d rows × %d cols", len(trips_df), len(trips_df.columns))
    log.info("Done.")
