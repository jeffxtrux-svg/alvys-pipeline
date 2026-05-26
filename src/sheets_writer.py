"""Google Sheets writer — writes DataFrames to named tabs in the XFreight KPI sheet.

Auth: Service account JSON key (path set via GCP_SERVICE_ACCOUNT_JSON env var).
The service account must have Editor access on the target sheet.

Usage:
    writer = SheetsWriter(sheet_id="1JxtdAex...", creds_path="/path/to/key.json")
    writer.write_tab("QB_PnL", df)
"""
from __future__ import annotations

import logging
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsWriter:
    def __init__(self, sheet_id: str, creds_path: str | Path):
        creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._sheet = self._gc.open_by_key(sheet_id)
        log.info("Connected to sheet: %s", self._sheet.title)

    def write_tab(self, tab_name: str, df: pd.DataFrame) -> None:
        """Clear and rewrite a worksheet tab with df contents (header + rows)."""
        if df is None or df.empty:
            log.warning("Skipping tab '%s' — DataFrame is empty.", tab_name)
            return

        # Get or create the worksheet
        try:
            ws = self._sheet.worksheet(tab_name)
            ws.clear()
            log.info("Cleared existing tab: %s", tab_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = self._sheet.add_worksheet(title=tab_name, rows=1, cols=1)
            log.info("Created new tab: %s", tab_name)

        # Convert all values to strings to avoid gspread type issues
        df_out = df.copy()
        for col in df_out.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns:
            df_out[col] = df_out[col].astype(str)

        rows = [df_out.columns.tolist()] + df_out.fillna("").values.tolist()
        ws.update(rows, value_input_option="USER_ENTERED")
        log.info("Wrote %d rows to tab '%s'", len(df_out), tab_name)
