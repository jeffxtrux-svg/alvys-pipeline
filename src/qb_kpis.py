"""Compute financial KPIs from QuickBooks report JSON.

Reads raw report responses (P&L, Balance Sheet, Cash Flow, AR/AP Aging) and
extracts the canonical totals, then derives standard financial ratios used in
trucking/logistics dashboards.

Output is long-format (Company, Period, Category, Metric, Value, Unit) so each
KPI is one row — easy to slice in Power BI.

A consolidated "XFreight (Consolidated)" row set is appended that sums absolute
totals across all 5 entities and recomputes derived ratios on the consolidated
basis. Ratios are NOT averaged across companies (that would be misleading).
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

log = logging.getLogger("qb_kpis")

CONSOLIDATED_LABEL = "XFreight (Consolidated)"


# ---------------------------------------------------------------------------
# Raw extractors — pull canonical totals out of QB report JSON
# ---------------------------------------------------------------------------

def _summary_value(row: dict) -> float:
    """Return the numeric value in the rightmost summary column of a section row."""
    cd = row.get("Summary", {}).get("ColData", [])
    for col in reversed(cd):
        v = col.get("value", "")
        if v in ("", None):
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _find_section(rows: list[dict], group: str) -> dict | None:
    """Walk top-level rows looking for a Section with the given `group` attribute."""
    for row in rows:
        if row.get("type") == "Section" and row.get("group") == group:
            return row
        nested = row.get("Rows", {}).get("Row", [])
        if nested:
            found = _find_section(nested, group)
            if found:
                return found
    return None


def _group_total(report: dict, group: str) -> float:
    rows = report.get("Rows", {}).get("Row", [])
    sect = _find_section(rows, group)
    return _summary_value(sect) if sect else 0.0


def _period_label(report: dict) -> str:
    h = report.get("Header", {})
    start, end = h.get("StartPeriod", ""), h.get("EndPeriod", "")
    if start and end:
        return f"{start} to {end}"
    return end or start or ""


def extract_pl(report: dict | None) -> dict[str, float]:
    """Extract income statement totals. Returns zeros if report is missing."""
    if not report:
        return {"Income": 0.0, "COGS": 0.0, "GrossProfit": 0.0, "Expenses": 0.0,
                "NetOperatingIncome": 0.0, "OtherIncome": 0.0, "OtherExpenses": 0.0,
                "NetOtherIncome": 0.0, "NetIncome": 0.0}
    return {
        "Income":             _group_total(report, "Income"),
        "COGS":               _group_total(report, "COGS"),
        "GrossProfit":        _group_total(report, "GrossProfit"),
        "Expenses":           _group_total(report, "Expenses"),
        "NetOperatingIncome": _group_total(report, "NetOperatingIncome"),
        "OtherIncome":        _group_total(report, "OtherIncome"),
        "OtherExpenses":      _group_total(report, "OtherExpenses"),
        "NetOtherIncome":     _group_total(report, "NetOtherIncome"),
        "NetIncome":          _group_total(report, "NetIncome"),
    }


def extract_bs(report: dict | None) -> dict[str, float]:
    if not report:
        return {k: 0.0 for k in (
            "BankAccounts", "AR", "OtherCurrentAssets", "TotalCurrentAssets",
            "FixedAssets", "OtherAssets", "TotalAssets",
            "AP", "CreditCards", "OtherCurrentLiabilities", "TotalCurrentLiabilities",
            "LongTermLiabilities", "TotalLiabilities", "Equity",
            "TotalLiabilitiesAndEquity",
        )}
    return {
        "BankAccounts":              _group_total(report, "BankAccounts"),
        "AR":                        _group_total(report, "AR"),
        "OtherCurrentAssets":        _group_total(report, "OtherCurrentAssets"),
        "TotalCurrentAssets":        _group_total(report, "TotalCurrentAssets"),
        "FixedAssets":               _group_total(report, "FixedAssets"),
        "OtherAssets":               _group_total(report, "OtherAssets"),
        "TotalAssets":               _group_total(report, "TotalAssets"),
        "AP":                        _group_total(report, "AP"),
        "CreditCards":               _group_total(report, "CreditCards"),
        "OtherCurrentLiabilities":   _group_total(report, "OtherCurrentLiabilities"),
        "TotalCurrentLiabilities":   _group_total(report, "TotalCurrentLiabilities"),
        "LongTermLiabilities":       _group_total(report, "LongTermLiabilities"),
        "TotalLiabilities":          _group_total(report, "TotalLiabilities"),
        "Equity":                    _group_total(report, "Equity"),
        "TotalLiabilitiesAndEquity": _group_total(report, "TotalLiabilitiesAndEquity"),
    }


def extract_cashflow(report: dict | None) -> dict[str, float]:
    if not report:
        return {k: 0.0 for k in ("OperatingActivities", "InvestingActivities",
                                  "FinancingActivities", "NetCashIncrease",
                                  "CashAtEnd")}
    return {
        "OperatingActivities": _group_total(report, "OperatingActivities"),
        "InvestingActivities": _group_total(report, "InvestingActivities"),
        "FinancingActivities": _group_total(report, "FinancingActivities"),
        "NetCashIncrease":     _group_total(report, "NetCashIncrease"),
        "CashAtEnd":           _group_total(report, "CashAtEnd"),
    }


def _aging_grand_total(report: dict | None) -> dict[str, float]:
    """Aging detail reports have one grand-total Summary row at the bottom with
    a single column of money. Returns {"Total": amount}."""
    if not report:
        return {"Total": 0.0}
    rows = report.get("Rows", {}).get("Row", [])
    total = 0.0
    # Walk to find a TotalRow at the top level
    for r in rows:
        if r.get("type") == "Section" and "Summary" in r:
            v = _summary_value(r)
            if v:
                total = v
    return {"Total": total}


# ---------------------------------------------------------------------------
# Derived ratio computation
# ---------------------------------------------------------------------------

def _safe_div(num: float, den: float) -> float | None:
    if den is None or den == 0:
        return None
    return num / den


def _pct(num: float, den: float) -> float | None:
    r = _safe_div(num, den)
    return None if r is None else round(r * 100, 2)


def compute_kpis(pl: dict, bs: dict, cf: dict, ar: dict, ap: dict) -> dict[str, dict[str, Any]]:
    """Return KPIs grouped by Category. Values are (number, unit)."""
    revenue        = pl["Income"]
    gross_profit   = pl["GrossProfit"] or (revenue - pl["COGS"])
    op_income      = pl["NetOperatingIncome"]
    op_expense     = pl["Expenses"]
    net_income     = pl["NetIncome"]

    total_assets   = bs["TotalAssets"]
    current_assets = bs["TotalCurrentAssets"]
    cash           = bs["BankAccounts"]
    ar_balance     = bs["AR"]
    fixed_assets   = bs["FixedAssets"]

    total_liab     = bs["TotalLiabilities"]
    current_liab   = bs["TotalCurrentLiabilities"]
    long_term_liab = bs["LongTermLiabilities"]
    equity         = bs["Equity"]
    ap_balance     = bs["AP"]

    return {
        "Revenue & Profitability": {
            "Total Revenue":             (revenue,        "USD"),
            "COGS":                      (pl["COGS"],     "USD"),
            "Gross Profit":              (gross_profit,   "USD"),
            "Gross Margin %":            (_pct(gross_profit, revenue), "%"),
            "Operating Expenses":        (op_expense,     "USD"),
            "Net Operating Income":      (op_income,      "USD"),
            "Operating Margin %":        (_pct(op_income, revenue),    "%"),
            # Trucking operating ratio = (COGS + OpEx) / Revenue. Lower is better.
            "Operating Ratio %":         (_pct(pl["COGS"] + op_expense, revenue), "%"),
            "Other Income":              (pl["OtherIncome"],   "USD"),
            "Other Expenses":            (pl["OtherExpenses"], "USD"),
            "Net Income":                (net_income,     "USD"),
            "Net Profit Margin %":       (_pct(net_income, revenue),   "%"),
        },
        "Balance Sheet": {
            "Cash & Bank":               (cash,           "USD"),
            "Accounts Receivable":       (ar_balance,     "USD"),
            "Total Current Assets":      (current_assets, "USD"),
            "Fixed Assets (Net)":        (fixed_assets,   "USD"),
            "Total Assets":              (total_assets,   "USD"),
            "Accounts Payable":          (ap_balance,     "USD"),
            "Total Current Liabilities": (current_liab,   "USD"),
            "Long-Term Liabilities":     (long_term_liab, "USD"),
            "Total Liabilities":         (total_liab,     "USD"),
            "Total Equity":              (equity,         "USD"),
        },
        "Liquidity & Leverage": {
            "Working Capital":           (current_assets - current_liab, "USD"),
            "Current Ratio":             (_safe_div(current_assets, current_liab),       "ratio"),
            "Quick Ratio":               (_safe_div(cash + ar_balance, current_liab),    "ratio"),
            "Cash Ratio":                (_safe_div(cash, current_liab),                 "ratio"),
            "Debt-to-Equity":            (_safe_div(total_liab, equity),                 "ratio"),
            "Debt-to-Assets":            (_safe_div(total_liab, total_assets),           "ratio"),
            "Equity Ratio":              (_safe_div(equity, total_assets),               "ratio"),
            "Return on Assets %":        (_pct(net_income, total_assets), "%"),
            "Return on Equity %":        (_pct(net_income, equity),       "%"),
        },
        "Cash Flow": {
            "Operating Cash Flow":       (cf["OperatingActivities"], "USD"),
            "Investing Cash Flow":       (cf["InvestingActivities"], "USD"),
            "Financing Cash Flow":       (cf["FinancingActivities"], "USD"),
            "Net Change in Cash":        (cf["NetCashIncrease"],     "USD"),
            "Cash at End of Period":     (cf["CashAtEnd"],           "USD"),
            "Op Cash Flow / Revenue %":  (_pct(cf["OperatingActivities"], revenue), "%"),
        },
        "AR / AP": {
            "AR Aging Total":            (ar["Total"], "USD"),
            "AP Aging Total":            (ap["Total"], "USD"),
            # DSO assumes the AR aging total ≈ outstanding AR. Annualized basis.
            "Days Sales Outstanding":    (_safe_div(ar_balance * 365, revenue), "days"),
            "Days Payable Outstanding":  (_safe_div(ap_balance * 365, pl["COGS"] + op_expense), "days"),
        },
    }


# ---------------------------------------------------------------------------
# Per-company + consolidated assembly
# ---------------------------------------------------------------------------

def kpi_rows_for_company(
    company: str,
    period: str,
    pl: dict,
    bs: dict,
    cf: dict,
    ar: dict,
    ap: dict,
) -> list[dict]:
    """Return one row per KPI for a single company."""
    kpis = compute_kpis(pl, bs, cf, ar, ap)
    rows: list[dict] = []
    for category, metrics in kpis.items():
        for metric, (value, unit) in metrics.items():
            rows.append({
                "Company":  company,
                "Period":   period,
                "Category": category,
                "Metric":   metric,
                "Value":    None if value is None else round(value, 2),
                "Unit":     unit,
            })
    return rows


def build_kpi_dataframe(company_extractions: list[dict]) -> pd.DataFrame:
    """Assemble the final KPI DataFrame.

    company_extractions: list of dicts shaped like
        {"company": str, "period": str, "pl": {...}, "bs": {...},
         "cf": {...}, "ar": {...}, "ap": {...}}

    Produces one row per (Company, Metric) plus a consolidated XFreight
    row set computed from summed absolute totals.
    """
    all_rows: list[dict] = []
    if not company_extractions:
        return pd.DataFrame(columns=["Company", "Period", "Category", "Metric", "Value", "Unit"])

    for ext in company_extractions:
        all_rows.extend(kpi_rows_for_company(
            ext["company"], ext["period"],
            ext["pl"], ext["bs"], ext["cf"], ext["ar"], ext["ap"],
        ))

    # Consolidated XFreight roll-up: sum absolute totals, recompute ratios
    keys_pl = company_extractions[0]["pl"].keys()
    keys_bs = company_extractions[0]["bs"].keys()
    keys_cf = company_extractions[0]["cf"].keys()
    cons_pl = {k: sum(e["pl"].get(k, 0.0) for e in company_extractions) for k in keys_pl}
    cons_bs = {k: sum(e["bs"].get(k, 0.0) for e in company_extractions) for k in keys_bs}
    cons_cf = {k: sum(e["cf"].get(k, 0.0) for e in company_extractions) for k in keys_cf}
    cons_ar = {"Total": sum(e["ar"].get("Total", 0.0) for e in company_extractions)}
    cons_ap = {"Total": sum(e["ap"].get("Total", 0.0) for e in company_extractions)}
    # Use the latest non-empty period label
    periods = [e["period"] for e in company_extractions if e.get("period")]
    cons_period = periods[-1] if periods else ""

    all_rows.extend(kpi_rows_for_company(
        CONSOLIDATED_LABEL, cons_period, cons_pl, cons_bs, cons_cf, cons_ar, cons_ap,
    ))

    return pd.DataFrame(all_rows)
