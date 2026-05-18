"""
Write the three DataFrames (Loads, Trips, Fuel) into a single .xlsx file
with the same sheet structure as Alvys_Master.xlsx.

Date columns are written as proper Excel datetime cells (not text), so Power BI
auto-detects them as Date type — enabling "between" slicers and date math.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# ISO 8601-style date or datetime strings:
#   2024-08-01
#   2024-08-01T07:00:00
#   2024-08-01T07:00:00.123
#   2024-08-01T07:00:00-05:00 / +00:00 / Z
#   2024-08-01 07:00:00
ISO_DATE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?)?$"
)


def _convert_iso_date_columns(
    df: pd.DataFrame, sheet_name: str
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Find columns whose string values are ISO 8601 dates and convert them
    to pandas datetime so openpyxl writes proper Excel datetime cells.

    Returns (dataframe, date_only_cols, datetime_cols). The column lists
    are used afterwards to apply explicit Excel number formats so Power BI
    recognizes them as dates.
    """
    date_only_cols: list[str] = []
    datetime_cols: list[str] = []

    for col in df.columns:
        # Accept both legacy object dtype and pandas 2.x str dtype
        if df[col].dtype.kind != "O" and str(df[col].dtype) != "str":
            continue
        sample = df[col].dropna().astype(str).head(50)
        if len(sample) == 0:
            continue
        matches = sum(1 for v in sample if ISO_DATE_PATTERN.match(v))
        if matches < len(sample) * 0.7:
            continue

        try:
            parsed_utc = pd.to_datetime(df[col], errors="coerce", utc=True)
            non_null_utc = parsed_utc.dropna()

            # If every UTC value is at midnight, this is a date-only column
            # (Alvys serializes dates as "YYYY-MM-DDT00:00:00Z"). Treat as a
            # calendar date — do NOT tz-convert, or "2025-08-15" becomes
            # "2025-08-14 19:00" in Central.
            is_date_only = (
                len(non_null_utc) > 0
                and (non_null_utc.dt.hour == 0).all()
                and (non_null_utc.dt.minute == 0).all()
                and (non_null_utc.dt.second == 0).all()
            )

            if is_date_only:
                df[col] = parsed_utc.dt.tz_localize(None)
                date_only_cols.append(col)
            else:
                df[col] = parsed_utc.dt.tz_convert("America/Chicago").dt.tz_localize(None)
                datetime_cols.append(col)
        except (TypeError, ValueError) as e:
            log.warning(
                "  %s: couldn't convert column %r as dates: %s",
                sheet_name, col, e,
            )

    if date_only_cols or datetime_cols:
        log.info(
            "  %s: %d date-only, %d datetime cols",
            sheet_name, len(date_only_cols), len(datetime_cols),
        )
        if date_only_cols:
            log.info("    date-only: %s", ", ".join(date_only_cols))
        if datetime_cols:
            log.info("    datetime : %s", ", ".join(datetime_cols))

    return df, date_only_cols, datetime_cols


def _apply_date_formats(
    writer,
    sheet_name: str,
    df: pd.DataFrame,
    date_only_cols: list[str],
    datetime_cols: list[str],
) -> None:
    """
    Apply explicit Excel number formats to the date columns we converted.
    These are standard Excel date formats that Power BI auto-detects as Date.
    """
    ws = writer.sheets[sheet_name]
    columns = list(df.columns)
    n_rows = len(df) + 1  # +1 for header row

    def _format_column(col_name: str, number_format: str) -> None:
        col_idx = columns.index(col_name) + 1  # openpyxl is 1-indexed
        for row in ws.iter_rows(
            min_row=2, max_row=n_rows, min_col=col_idx, max_col=col_idx
        ):
            for cell in row:
                cell.number_format = number_format

    for col_name in date_only_cols:
        _format_column(col_name, "mm/dd/yyyy")
    for col_name in datetime_cols:
        _format_column(col_name, "mm/dd/yyyy hh:mm")


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
    log.info("Converting ISO date strings to Excel datetime cells…")
    fuel_df, fuel_date_only, fuel_dt = _convert_iso_date_columns(fuel_df, "Fuel")
    loads_df, loads_date_only, loads_dt = _convert_iso_date_columns(loads_df, "Loads")
    trips_df, trips_date_only, trips_dt = _convert_iso_date_columns(trips_df, "Trips")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        fuel_df.to_excel(writer, sheet_name="Fuel", index=False)
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        trips_df.to_excel(writer, sheet_name="Trips", index=False)

        # Apply explicit date number formats so Power BI auto-detects as Date.
        _apply_date_formats(writer, "Fuel", fuel_df, fuel_date_only, fuel_dt)
        _apply_date_formats(writer, "Loads", loads_df, loads_date_only, loads_dt)
        _apply_date_formats(writer, "Trips", trips_df, trips_date_only, trips_dt)

    log.info("  Fuel : %d rows × %d cols", len(fuel_df), len(fuel_df.columns))
    log.info("  Loads: %d rows × %d cols", len(loads_df), len(loads_df.columns))
    log.info("  Trips: %d rows × %d cols", len(trips_df), len(trips_df.columns))
    log.info("Done.")
