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

    Strategy:
      1. Fetch all Payments whose TxnDate falls in the window.
      2. From each Payment's LinkedTxn list collect linked Invoice IDs.
      3. Pre-load invoice TxnDates by querying ALL invoices in a broader window
         (avoids the QBO SQL IN-clause, which can be unreliable for large batches).
      4. Compute avg(payment.TxnDate - invoice.TxnDate) grouped by payment month.

    Returns a DataFrame: Company, AsOf (YYYY-MM), Month (label), AvgDays, InvoiceCount.
    Returns None when data is unavailable or queries fail.
    """
    log.info("  %-25s %s", "DSO history", company_name)

    today = datetime.date.today()
    # Payment window: first of `months` months ago → today.
    first_day = today.replace(day=1)
    for _ in range(months - 1):
        first_day = (first_day - datetime.timedelta(days=1)).replace(day=1)
    pay_start = first_day.isoformat()
    pay_end   = today.isoformat()
    # Invoice window: look back 24 months to capture slow-pay invoices issued before the payment window.
    inv_start = (first_day - datetime.timedelta(days=730)).isoformat()

    log.info("    DSO: payment window %s→%s  invoice window %s→%s",
             pay_start, pay_end, inv_start, pay_end)

    # Step 1 — fetch ALL Payments in the window (paginated; QB cap is 1000/page).
    payments: list[dict] = []
    pay_start_pos = 1
    try:
        while True:
            r = client.get("query", {
                "query": (f"SELECT * FROM Payment "
                          f"WHERE TxnDate >= '{pay_start}' AND TxnDate <= '{pay_end}' "
                          f"STARTPOSITION {pay_start_pos} MAXRESULTS 1000"),
                "minorversion": 75,
            })
            batch = r.get("QueryResponse", {}).get("Payment", [])
            payments.extend(batch)
            if len(batch) < 1000:
                break
            pay_start_pos += 1000
    except Exception as exc:
        log.warning("    DSO: Payment query failed for %s: %s", company_name, exc)
        return None

    log.info("    DSO: %d payments returned for %s", len(payments), company_name)
    if not payments:
        return None

    # Step 2 — map linked Invoice IDs → list of payment dates.
    # QB Online Payment structure: invoice links are in Line[].LinkedTxn, not top-level LinkedTxn.
    # (Top-level LinkedTxn on a Payment refers to bank deposit groupings, not invoices.)
    inv_id_to_pay_dates: dict[str, list[datetime.date]] = {}
    txn_type_counts: dict[str, int] = {}
    skipped_no_linked = 0
    for p in payments:
        try:
            pay_date = datetime.date.fromisoformat(str(p.get("TxnDate", ""))[:10])
        except ValueError:
            continue
        found_any = False
        # Primary: Line[].LinkedTxn (where invoice references live in QBO)
        for line in p.get("Line", []):
            for lt in line.get("LinkedTxn", []):
                txn_type = str(lt.get("TxnType", "")).strip()
                txn_type_counts[txn_type] = txn_type_counts.get(txn_type, 0) + 1
                if txn_type == "Invoice":
                    inv_id = str(lt.get("TxnId", "")).strip()
                    if inv_id:
                        inv_id_to_pay_dates.setdefault(inv_id, []).append(pay_date)
                        found_any = True
        # Fallback: top-level LinkedTxn (some QB versions surface it both places)
        for lt in p.get("LinkedTxn", []):
            txn_type = str(lt.get("TxnType", "")).strip()
            txn_type_counts[txn_type] = txn_type_counts.get(txn_type, 0) + 1
            if txn_type == "Invoice":
                inv_id = str(lt.get("TxnId", "")).strip()
                if inv_id and inv_id not in inv_id_to_pay_dates:
                    inv_id_to_pay_dates.setdefault(inv_id, []).append(pay_date)
                    found_any = True
        if not found_any:
            skipped_no_linked += 1

    log.info("    DSO: %d unique invoice IDs linked  (%d payments had no Invoice link)",
             len(inv_id_to_pay_dates), skipped_no_linked)
    log.info("    DSO: TxnType breakdown across all LinkedTxn entries: %s",
             ", ".join(f"{k}={v}" for k, v in sorted(txn_type_counts.items())))
    if not inv_id_to_pay_dates:
        return None

    # Step 3 — pre-load invoice dates using paginated date-range queries (QB cap is 1000/page).
    inv_dates: dict[str, datetime.date] = {}
    inv_start_pos = 1
    try:
        while True:
            ri = client.get("query", {
                "query": (f"SELECT Id, TxnDate FROM Invoice "
                          f"WHERE TxnDate >= '{inv_start}' AND TxnDate <= '{pay_end}' "
                          f"STARTPOSITION {inv_start_pos} MAXRESULTS 1000"),
                "minorversion": 75,
            })
            batch_inv = ri.get("QueryResponse", {}).get("Invoice", [])
            for inv in batch_inv:
                try:
                    inv_dates[str(inv["Id"])] = datetime.date.fromisoformat(str(inv["TxnDate"])[:10])
                except (KeyError, ValueError):
                    pass
            if len(batch_inv) < 1000:
                break
            inv_start_pos += 1000
        log.info("    DSO: %d invoice dates loaded from QB (paginated, window %s→%s)",
                 len(inv_dates), inv_start, pay_end)
    except Exception as exc:
        log.warning("    DSO: Invoice date query failed for %s: %s", company_name, exc)
        return None

    # Step 4 — compute avg days per payment month.
    from collections import defaultdict
    month_days: dict[str, list[int]] = defaultdict(list)
    unmatched = 0
    for inv_id, pay_dates in inv_id_to_pay_dates.items():
        inv_date = inv_dates.get(inv_id)
        if inv_date is None:
            unmatched += 1
            continue
        for pay_date in pay_dates:
            days = (pay_date - inv_date).days
            if 0 <= days <= 365:
                ym = pay_date.strftime("%Y-%m")
                month_days[ym].append(days)

    total_pairs = sum(len(v) for v in month_days.values())
    log.info("    DSO: %d invoice IDs unmatched  %d valid pairs across %d months",
             unmatched, total_pairs, len(month_days))

    if not month_days:
        log.warning("    DSO: no valid invoice-payment pairs for %s — "
                    "check invoice window (%s → %s) and payment links", company_name, inv_start, pay_end)
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
        log.info("    DSO: %s %s  avg=%.1f days  n=%d",
                 company_name, ym, rows[-1]["AvgDays"], len(days_list))

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
