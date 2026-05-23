"""Fetch and parse QuickBooks Online reports and entity lists into DataFrames.

Reports pulled (per company):
  Financial statements : ProfitAndLoss, ProfitAndLossDetail, BalanceSheet,
                         BalanceSheetDetail, CashFlow
  Ledger / detail      : GeneralLedger, TrialBalance, TransactionList
  Aging                : AgedReceivableDetail, AgedPayableDetail
  Lists (entity query) : Customer, Vendor, Account (chart of accounts)

Each DataFrame gets a leading "Company" column so all 5 entities can be
stacked into a single file per report type for Power BI.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .qb_client import QBClient

log = logging.getLogger("qb_reports")

# Map report_name -> (API path, extra query params)
REPORT_CONFIGS: dict[str, dict] = {
    "ProfitAndLoss": {
        "path": "reports/ProfitAndLoss",
        "params": {"date_macro": "This Fiscal Year", "minorversion": 75},
    },
    "ProfitAndLossDetail": {
        "path": "reports/ProfitAndLossDetail",
        "params": {"date_macro": "This Fiscal Year", "minorversion": 75},
    },
    "BalanceSheet": {
        "path": "reports/BalanceSheet",
        "params": {"date_macro": "Today", "minorversion": 75},
    },
    "BalanceSheetDetail": {
        "path": "reports/BalanceSheetDetail",
        "params": {"date_macro": "Today", "minorversion": 75},
    },
    "CashFlow": {
        "path": "reports/CashFlow",
        "params": {"date_macro": "This Fiscal Year", "minorversion": 75},
    },
    "GeneralLedger": {
        "path": "reports/GeneralLedger",
        "params": {"date_macro": "This Fiscal Year", "minorversion": 75},
    },
    "TrialBalance": {
        "path": "reports/TrialBalance",
        "params": {"date_macro": "This Fiscal Year", "minorversion": 75},
    },
    "AgedReceivableDetail": {
        "path": "reports/AgedReceivableDetail",
        "params": {"minorversion": 75},
    },
    "AgedPayableDetail": {
        "path": "reports/AgedPayableDetail",
        "params": {"minorversion": 75},
    },
    "TransactionList": {
        "path": "reports/TransactionList",
        "params": {"date_macro": "This Fiscal Year", "minorversion": 75},
    },
}

ENTITY_QUERIES: dict[str, str] = {
    "Customer": "SELECT * FROM Customer MAXRESULTS 1000",
    "Vendor":   "SELECT * FROM Vendor MAXRESULTS 1000",
    "Account":  "SELECT * FROM Account MAXRESULTS 1000",
}


# ---------------------------------------------------------------------------
# Report row parser
# ---------------------------------------------------------------------------

def _col_titles(report_data: dict) -> list[str]:
    cols = report_data.get("Columns", {}).get("Column", [])
    seen: dict[str, int] = {}
    titles: list[str] = []
    for col in cols:
        raw = col.get("ColTitle") or col.get("ColType", "Col")
        if raw in seen:
            seen[raw] += 1
            raw = f"{raw}_{seen[raw]}"
        else:
            seen[raw] = 0
        titles.append(raw)
    return titles


def _parse_rows(
    rows: list[dict],
    col_titles: list[str],
    company: str,
    section: str = "",
) -> list[dict]:
    """Recursively flatten QB report rows into a list of flat dicts."""
    records: list[dict] = []

    for row in rows:
        row_type = row.get("type", "")

        if row_type == "Section":
            header_data = row.get("Header", {}).get("ColData", [])
            section_name = header_data[0].get("value", section) if header_data else section

            nested = row.get("Rows", {}).get("Row", [])
            if nested:
                records.extend(_parse_rows(nested, col_titles, company, section_name))

            summary = row.get("Summary")
            if summary:
                cd = summary.get("ColData", [])
                rec = {"Company": company, "Section": section_name, "Row_Type": "Total"}
                for i, title in enumerate(col_titles):
                    rec[title] = cd[i].get("value", "") if i < len(cd) else ""
                records.append(rec)

        elif row_type == "Data":
            cd = row.get("ColData", [])
            rec = {"Company": company, "Section": section, "Row_Type": "Data"}
            for i, title in enumerate(col_titles):
                rec[title] = cd[i].get("value", "") if i < len(cd) else ""
            records.append(rec)

    return records


# ---------------------------------------------------------------------------
# Public fetch functions
# ---------------------------------------------------------------------------

def fetch_report_raw(client: QBClient, report_name: str, company_name: str) -> dict | None:
    """Fetch a report and return the raw JSON. Used by both DataFrame parser and KPI extractor."""
    config = REPORT_CONFIGS.get(report_name)
    if not config:
        log.warning("Unknown report: %s", report_name)
        return None

    log.info("  %-25s %s", report_name, company_name)
    try:
        return client.get(config["path"], config["params"])
    except Exception as exc:
        log.error("  FAILED %s / %s: %s", report_name, company_name, exc)
        return None


def parse_report(data: dict, company_name: str) -> pd.DataFrame:
    """Flatten a raw report JSON into a DataFrame with Company/Report_Period/Report_Basis columns."""
    col_titles = _col_titles(data)
    rows = data.get("Rows", {}).get("Row", [])
    records = _parse_rows(rows, col_titles, company_name)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    header = data.get("Header", {})
    df.insert(1, "Report_Period",
              f"{header.get('StartPeriod', '')} – {header.get('EndPeriod', '')}")
    df.insert(2, "Report_Basis", header.get("ReportBasis", ""))
    return df


def fetch_report(client: QBClient, report_name: str, company_name: str) -> pd.DataFrame | None:
    data = fetch_report_raw(client, report_name, company_name)
    if data is None:
        return None
    return parse_report(data, company_name)


def fetch_entity(client: QBClient, entity: str, company_name: str) -> pd.DataFrame | None:
    query = ENTITY_QUERIES.get(entity)
    if not query:
        return None

    log.info("  %-25s %s", entity, company_name)
    try:
        data = client.get("query", {"query": query, "minorversion": 75})
    except Exception as exc:
        log.error("  FAILED %s / %s: %s", entity, company_name, exc)
        return None

    items = data.get("QueryResponse", {}).get(entity, [])
    if not items:
        return pd.DataFrame()

    df = pd.json_normalize(items)
    df.insert(0, "Company", company_name)
    return df
