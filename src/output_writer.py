"""
Write the three DataFrames (Loads, Trips, Fuel) into a single .xlsx file
with the same sheet structure as Alvys_Master.xlsx.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows

log = logging.getLogger(__name__)


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
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        fuel_df.to_excel(writer, sheet_name="Fuel", index=False)
        loads_df.to_excel(writer, sheet_name="Loads", index=False)
        trips_df.to_excel(writer, sheet_name="Trips", index=False)

    log.info("  Fuel : %d rows × %d cols", len(fuel_df), len(fuel_df.columns))
    log.info("  Loads: %d rows × %d cols", len(loads_df), len(loads_df.columns))
    log.info("  Trips: %d rows × %d cols", len(trips_df), len(trips_df.columns))
    log.info("Done.")
