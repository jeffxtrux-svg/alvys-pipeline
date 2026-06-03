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

import datetime
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

def fetch_report(client: QBClient, report_name: str, company_name: str) -> pd.DataFrame | None:
    config = REPORT_CONFIGS.get(report_name)
    if not config:
        log.warning("Unknown report: %s", report_name)
        return None

    log.info("  %-25s %s", report_name, company_name)
    try:
        data = client.get(config["path"], config["params"])
    except Exception as exc:
        log.error("  FAILED %s / %s: %s", report_name, company_name, exc)
        return None

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


# ---------------------------------------------------------------------------
# AR month-end history (for the scorecard's 6-month receivables trend)
# ---------------------------------------------------------------------------

def _month_end_dates(n: int = 6) -> list[tuple[str, str, str]]:
    """Last ``n`` months as (label, as_of YYYY-MM-DD, ym YYYY-MM), oldest first.

    Completed months use the last calendar day; the current month uses today
    (an as-of / month-to-date snapshot).
    """
    today = datetime.date.today()
    months: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()

    out: list[tuple[str, str, str]] = []
    for yy, mm in months:
        if yy == today.year and mm == today.month:
            as_of = today
        else:
            nxt = datetime.date(yy + 1, 1, 1) if mm == 12 else datetime.date(yy, mm + 1, 1)
            as_of = nxt - datetime.timedelta(days=1)
        out.append((as_of.strftime("%b"), as_of.isoformat(), f"{yy}-{mm:02d}"))
    return out


def _name_col(col_titles: list[str]) -> str | None:
    """Find the customer/vendor name column in a QB aging detail report.

    QB aging reports lead with the entity name — the column title is often blank
    (ColTitle=""), so we look for 'name', 'customer', or 'vendor' first, then
    fall back to the first column.
    """
    for t in col_titles:
        if any(k in t.strip().lower() for k in ("name", "customer", "vendor")):
            return t
    return col_titles[0] if col_titles else None


# Names excluded from AR/AP history totals (internal entities, intercompany
# balances, or companies whose numbers would distort the scorecard trend).
_AR_AP_EXCLUDE: frozenset[str] = frozenset({"jw logistics"})


def _sum_open_balance(records: list[dict], col_titles: list[str]) -> float:
    """Sum the open-balance column across all Data rows in a Detail aging report.

    Tries columns named 'open balance' first, then falls back to the last
    column.  Works for both AgedReceivableDetail and AgedPayableDetail.
    Names in ``_AR_AP_EXCLUDE`` (case-insensitive) are skipped.
    """
    amt_col = next(
        (t for t in col_titles if "open balance" in t.strip().lower()), None
    )
    if amt_col is None:
        amt_col = col_titles[-1] if col_titles else None
    if not amt_col:
        return 0.0

    name_col = _name_col(col_titles)

    def _include(r: dict) -> bool:
        if r.get("Row_Type") != "Data":
            return False
        if name_col and _AR_AP_EXCLUDE:
            entity = str(r.get(name_col, "")).strip().lower()
            if any(entity.startswith(excl) for excl in _AR_AP_EXCLUDE):
                return False
        return True

    values = pd.to_numeric(
        pd.Series([r.get(amt_col) for r in records if _include(r)]),
        errors="coerce",
    ).dropna()
    return float(values.sum()) if len(values) else 0.0


def fetch_ar_history(client: QBClient, company_name: str, months: int = 6) -> pd.DataFrame | None:
    """Total open AR as of each of the last ``months`` month-ends, one row each.

    Uses AgedReceivableDetail (not the summary) so the open-balance column is
    always present and parseable.
    """
    log.info("  %-25s %s", "AR history", company_name)
    rows: list[dict] = []
    for label, as_of, ym in _month_end_dates(months):
        try:
            data = client.get("reports/AgedReceivableDetail",
                              {"report_date": as_of, "minorversion": 75})
        except Exception as exc:
            log.warning("    AR history %s %s failed: %s", company_name, ym, exc)
            continue
        col_titles = _col_titles(data)
        recs = _parse_rows(data.get("Rows", {}).get("Row", []), col_titles, company_name)
        rows.append({
            "Company": company_name,
            "AsOf": ym,
            "AsOfDate": as_of,
            "Month": label,
            "Total_AR": _sum_open_balance(recs, col_titles),
        })
    return pd.DataFrame(rows) if rows else None


def fetch_dso_history(client: QBClient, company_name: str, months: int = 6) -> pd.DataFrame | None:
    """Average days invoice-to-payment per calendar month, for the last ``months`` months.

    Queries Payment entities for the window, links each payment to its source
    Invoice via LinkedTxn, fetches the invoice TxnDate in batches, then
    computes avg(payment.TxnDate - invoice.TxnDate) grouped by the payment month.

    Returns a DataFrame with columns:
        Company, AsOf (YYYY-MM), Month (label), AvgDays, InvoiceCount
    Returns None if no payment data is available.
    """
    log.info("  %-25s %s", "DSO history", company_name)

    # Date window: first of (months) ago through today.
    today = datetime.date.today()
    first_day = today.replace(day=1)
    for _ in range(months - 1):
        first_day = (first_day - datetime.timedelta(days=1)).replace(day=1)
    start_str = first_day.isoformat()
    end_str = today.isoformat()

    # Step 1 — fetch all Payments in the window (MAXRESULTS 1000 covers most
    # small fleets; the QB tool counted 1,041 over 6 months so a single page
    # is sufficient; add pagination if needed).
    try:
        result = client.get("query", {
            "query": (f"SELECT * FROM Payment "
                      f"WHERE TxnDate >= '{start_str}' AND TxnDate <= '{end_str}' "
                      f"MAXRESULTS 1000"),
            "minorversion": 75,
        })
    except Exception as exc:
        log.warning("    DSO: Payment query failed for %s: %s", company_name, exc)
        return None

    payments = result.get("QueryResponse", {}).get("Payment", [])
    if not payments:
        log.info("    DSO: no payments for %s in window", company_name)
        return None

    # Step 2 — map each linked Invoice ID → payment date(s).
    inv_id_to_pay_dates: dict[str, list[datetime.date]] = {}
    for p in payments:
        try:
            pay_date = datetime.date.fromisoformat(str(p.get("TxnDate", ""))[:10])
        except ValueError:
            continue
        for lt in p.get("LinkedTxn", []):
            if lt.get("TxnType") == "Invoice":
                inv_id = lt.get("TxnId")
                if inv_id:
                    inv_id_to_pay_dates.setdefault(inv_id, []).append(pay_date)

    if not inv_id_to_pay_dates:
        return None

    # Step 3 — fetch invoice TxnDates in batches of 50.
    BATCH = 50
    inv_ids = list(inv_id_to_pay_dates.keys())
    inv_dates: dict[str, datetime.date] = {}
    for i in range(0, len(inv_ids), BATCH):
        batch = inv_ids[i : i + BATCH]
        id_list = ", ".join(f"'{x}'" for x in batch)
        try:
            r2 = client.get("query", {
                "query": f"SELECT Id, TxnDate FROM Invoice WHERE Id IN ({id_list})",
                "minorversion": 75,
            })
            for inv in r2.get("QueryResponse", {}).get("Invoice", []):
                try:
                    inv_dates[inv["Id"]] = datetime.date.fromisoformat(str(inv["TxnDate"])[:10])
                except (KeyError, ValueError):
                    pass
        except Exception as exc:
            log.warning("    DSO: Invoice batch query failed: %s", exc)

    # Step 4 — compute avg days per payment month.
    from collections import defaultdict
    month_days: dict[str, list[int]] = defaultdict(list)
    for inv_id, pay_dates in inv_id_to_pay_dates.items():
        inv_date = inv_dates.get(inv_id)
        if inv_date is None:
            continue
        for pay_date in pay_dates:
            days = (pay_date - inv_date).days
            if 0 <= days <= 365:
                ym = pay_date.strftime("%Y-%m")
                month_days[ym].append(days)

    if not month_days:
        return None

    rows = []
    for ym, days_list in sorted(month_days.items()):
        dt = datetime.date.fromisoformat(ym + "-01")
        rows.append({
            "Company":      company_name,
            "AsOf":         ym,
            "Month":        dt.strftime("%b"),
            "AvgDays":      round(sum(days_list) / len(days_list), 1),
            "InvoiceCount": len(days_list),
        })

    log.info("    DSO: %s — %d month(s), %d invoice-payment pairs",
             company_name, len(rows), sum(r["InvoiceCount"] for r in rows))
    return pd.DataFrame(rows)


def fetch_ap_history(client: QBClient, company_name: str, months: int = 6) -> pd.DataFrame | None:
    """Total open AP as of each of the last ``months`` month-ends, one row each.

    Uses AgedPayableDetail (not the summary) so the open-balance column is
    always present and parseable.
    """
    log.info("  %-25s %s", "AP history", company_name)
    rows: list[dict] = []
    for label, as_of, ym in _month_end_dates(months):
        try:
            data = client.get("reports/AgedPayableDetail",
                              {"report_date": as_of, "minorversion": 75})
        except Exception as exc:
            log.warning("    AP history %s %s failed: %s", company_name, ym, exc)
            continue
        col_titles = _col_titles(data)
        recs = _parse_rows(data.get("Rows", {}).get("Row", []), col_titles, company_name)
        rows.append({
            "Company": company_name,
            "AsOf": ym,
            "AsOfDate": as_of,
            "Month": label,
            "Total_AP": _sum_open_balance(recs, col_titles),
        })
    return pd.DataFrame(rows) if rows else None
