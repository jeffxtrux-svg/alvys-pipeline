"""
Write the three DataFrames (Loads, Trips, Fuel) into a single .xlsx file
matching the EXACT formatting of the original Alvys_Master.xlsx.

The original file stores date columns in several different text formats —
not one consistent style. Power Query's existing "Changed Type" steps were
authored against those exact formats. So we replicate the manual file's
per-column format on a column-by-column basis (see COLUMN_DATE_FORMATS).

We also coerce specific text-numeric columns back to integers where they
parse cleanly, since the manual file has them as Excel number cells (Power
Query then leaves them as Whole Number).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Matches ISO 8601 timestamps the Alvys API returns:
#   2024-08-01
#   2024-08-01T07:00:00
#   2024-08-01T07:00:00.123
#   2024-08-01T07:00:00-05:00 / +00:00 / Z
ISO_DATE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?)?$"
)

# Matches "human-readable" Alvys dates we may also see in the source:
#   04-30-2026 / 04/30/2026
#   04-30-2026 13:00
#   04-29-2026 @ 17:02
HUMAN_DATE_PATTERN = re.compile(
    r"^\d{1,2}[-/]\d{1,2}[-/]\d{4}(\s+@?\s*\d{1,2}:\d{2})?$"
)


# ---------------------------------------------------------------------------
# Date format rule: ALL date columns are written as MM-DD-YYYY (date-only,
# no time component). Power Query's existing "Changed Type" step is
# configured as `type date` — passing "MM-DD-YYYY @ HH:MM" or any string
# with a time suffix causes per-row type-conversion errors. So we strip
# time uniformly. Date columns are detected automatically by sampling.
# ---------------------------------------------------------------------------

# Columns whose values are business numbers (Load #, Truck, etc.). They come
# back from Alvys / lookup tables as strings, but the manual master stores
# them as Excel number cells. We coerce each cell to int where it parses
# cleanly; otherwise we leave the original string intact.
INT_COERCE_COLUMNS: dict[str, list[str]] = {
    "Loads": ["Load #", "Order #", "Truck", "Trailer"],
    "Trips": ["Trip #", "Order #", "Truck", "Trailer"],
    "Fuel":  [],
}


def _parse_iso(value: str) -> pd.Timestamp | None:
    """Parse an ISO 8601 string from the Alvys API. Returns None on failure."""
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts


def _format_as_date_only(value):
    """Format one cell value as MM-DD-YYYY date-only text. Returns value
    unchanged if it isn't a string or isn't recognizably a date.
    """
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        return value

    # Alvys "human" formats — keep just the date portion.
    if HUMAN_DATE_PATTERN.match(value):
        date_part = value.split()[0].replace("/", "-")
        return date_part

    # ISO 8601 path: parse, convert to America/Chicago, emit MM-DD-YYYY.
    ts = _parse_iso(value)
    if ts is None:
        return value
    local = ts.tz_convert("America/Chicago")
    return local.strftime("%m-%d-%Y")


def _looks_like_date_column(series: pd.Series) -> bool:
    """Heuristic: at least 70% of non-empty values look like a date/datetime."""
    sample = series.dropna().astype(str)
    sample = sample[sample != ""].head(50)
    if len(sample) == 0:
        return False
    matches = sum(
        1 for v in sample
        if ISO_DATE_PATTERN.match(v) or HUMAN_DATE_PATTERN.match(v)
    )
    return matches >= len(sample) * 0.7


def _apply_date_formats(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    """Reformat every date-like column to MM-DD-YYYY text. Date columns
    are detected by sampling — at least 70% of non-empty values must
    match an ISO 8601 or Alvys human date pattern."""
    reformatted: list[str] = []

    for col in df.columns:
        if df[col].dtype.kind != "O" and str(df[col].dtype) != "str":
            continue
        if not _looks_like_date_column(df[col]):
            continue
        df[col] = df[col].apply(
            lambda v: _format_as_date_only(v) if isinstance(v, str) else v
        )
        reformatted.append(col)

    if reformatted:
        log.info(
            "  %s: reformatted %d date columns → MM-DD-YYYY",
            sheet_name, len(reformatted),
        )
        log.debug("    columns: %s", ", ".join(reformatted))
    return df


def _coerce_int_columns(df: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    """For columns that are business numbers in the manual, convert each cell
    to int where it parses cleanly. Non-numeric values stay as their original
    string (matches manual where e.g. 'Order #' has both ints and strings)."""
    cols = INT_COERCE_COLUMNS.get(sheet_name, [])
    for col in cols:
        if col not in df.columns:
            continue
        def _cell_to_int(v):
            if v is None or v == "" or (isinstance(v, float) and pd.isna(v)):
                return v
            if isinstance(v, bool):
                return v
            if isinstance(v, int):
                return v
            if isinstance(v, float):
                return int(v) if v.is_integer() else v
            s = str(v).strip()
            if s.lstrip("-").isdigit():
                try:
                    return int(s)
                except ValueError:
                    return v
            return v
        df[col] = df[col].apply(_cell_to_int)
    return df


def write_master_xlsx(
    loads_df: pd.DataFrame,
    trips_df: pd.DataFrame,
    fuel_df: pd.DataFrame,
    output_path: Path,
    drivers_df: pd.DataFrame | None = None,
) -> None:
    """Write Loads/Trips/Fuel sheets matching the manual Alvys_Master.xlsx
    exactly: sheet order (Fuel, Loads, Trips), per-column date formats, and
    integer coercion for the business-number columns.

    `drivers_df` is optional — when provided, a fourth ``Drivers`` sheet
    is appended with CDL + medical-card expiration data for the
    scorecard's driver-compliance page. Schema is small (~30 rows × 10
    cols) so it does not affect the existing tabs or their Power BI
    queries."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Writing %s", output_path)
    log.info("Applying per-column date formats…")
    fuel_df  = _apply_date_formats(fuel_df,  "Fuel")
    loads_df = _apply_date_formats(loads_df, "Loads")
    trips_df = _apply_date_formats(trips_df, "Trips")

    log.info("Coercing business-number columns to int…")
    fuel_df  = _coerce_int_columns(fuel_df,  "Fuel")
    loads_df = _coerce_int_columns(loads_df, "Loads")
    trips_df = _coerce_int_columns(trips_df, "Trips")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        fuel_df.to_excel(writer,  sheet_name="Fuel",  index=False)
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        trips_df.to_excel(writer, sheet_name="Trips", index=False)
        if drivers_df is not None and not drivers_df.empty:
            drivers_df.to_excel(writer, sheet_name="Drivers", index=False)

    log.info("  Fuel : %d rows × %d cols", len(fuel_df),  len(fuel_df.columns))
    log.info("  Loads: %d rows × %d cols", len(loads_df), len(loads_df.columns))
    log.info("  Trips: %d rows × %d cols", len(trips_df), len(trips_df.columns))
    if drivers_df is not None and not drivers_df.empty:
        log.info("  Drivers: %d rows × %d cols", len(drivers_df), len(drivers_df.columns))
    log.info("Done.")
