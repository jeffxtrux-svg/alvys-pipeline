"""
Write the three DataFrames (Loads, Trips, Fuel) into a single .xlsx file
matching the schema (and column data formats) of the original Alvys_Master.xlsx.
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
#   2024-08-01T07:00:00Z
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?)?$")


def _reformat_iso_date_columns(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    """
    Find columns whose string values are ISO 8601 dates and reformat them
    to MM-DD-YYYY HH:MM text (matching the original Alvys_Master.xlsx format),
    or MM-DD-YYYY if the time component is exactly midnight.

    The original Power BI Power Query is built around this text format and
    handles the text-to-date conversion internally.

    Strategy:
      • Only consider object/str dtype columns
      • Sample up to 50 non-null values
      • If at least 70% match ISO pattern, convert
      • Parse as Central time, output as text
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
            local = parsed.dt.tz_convert("America/Chicago")

            # If every non-null value has midnight time, use date-only format.
            # Otherwise include HH:MM. (Matches original Alvys export quirk.)
            non_null = local.dropna()
            if len(non_null) > 0 and (
                (non_null.dt.hour == 0).all() and (non_null.dt.minute == 0).all()
            ):
                df[col] = local.dt.strftime("%m-%d-%Y").where(local.notna(), None)
                fmt = "date-only"
            else:
                df[col] = local.dt.strftime("%m-%d-%Y %H:%M").where(local.notna(), None)
                fmt = "date+time"
            converted.append(f"{col} ({fmt})")
        except (TypeError, ValueError) as e:
            log.warning("  %s: couldn't reformat column %r as dates: %s",
                        sheet_name, col, e)
    if converted:
        log.info("  %s: reformatted %d date columns: %s",
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
    Alvys_Master.xlsx (Fuel first, then Loads, then Trips).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Writing %s", output_path)
    log.info("Reformatting ISO date strings to MM-DD-YYYY text…")
    fuel_df  = _reformat_iso_date_columns(fuel_df,  "Fuel")
    loads_df = _reformat_iso_date_columns(loads_df, "Loads")
    trips_df = _reformat_iso_date_columns(trips_df, "Trips")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        fuel_df.to_excel(writer, sheet_name="Fuel", index=False)
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        trips_df.to_excel(writer, sheet_name="Trips", index=False)

    log.info("  Fuel : %d rows × %d cols", len(fuel_df), len(fuel_df.columns))
    log.info("  Loads: %d rows × %d cols", len(loads_df), len(loads_df.columns))
    log.info("  Trips: %d rows × %d cols", len(trips_df), len(trips_df.columns))
    log.info("Done.")
