"""XFreight KPI → Google Sheets pipeline.

Pulls from all three sources (Alvys, QuickBooks, Samsara) and writes to the
XFreight KPI Dashboard Google Sheet, one tab per dataset.

Historical range: SHEETS_START_DATE env var (default 2022-01-01) → today.

Run locally:
    python -m src.sheets_main

Required env vars:
    GCP_SERVICE_ACCOUNT_JSON     — path to the service account JSON key
    GSHEET_ID                    — target Google Sheet ID
    ALVYS_CLIENT_ID              — Alvys OAuth client ID
    ALVYS_CLIENT_SECRET          — Alvys OAuth client secret
    SAMSARA_API_TOKEN            — Samsara API token
    QB_CLIENT_ID                 — Intuit app Client ID
    QB_CLIENT_SECRET             — Intuit app Client Secret
    QB_XTRUX_REFRESH_TOKEN
    QB_TRUKWAY_REFRESH_TOKEN
    QB_XLINX_REFRESH_TOKEN
    QB_NJ_TRAILERS_REFRESH_TOKEN (optional — skip if not yet set up)
    QB_NJ_PROPERTIES_REFRESH_TOKEN (optional)

Optional:
    SHEETS_START_DATE            — history start date (default: 2022-01-01)
    GH_TOKEN / GH_PAT            — for QB refresh token rotation back to GitHub
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# ── helpers ──────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def get_required(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        sys.exit(f"ERROR: required env var {key!r} not set. Check your .env file.")
    return val


def sanitize(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].apply(
            lambda v: _ILLEGAL_CHARS.sub("", v) if isinstance(v, str) else v
        )
    return df


def flatten(records: list[dict], label: str = "") -> pd.DataFrame:
    log = logging.getLogger("sheets_main")
    if not records:
        log.info("  %s: no records", label)
        return pd.DataFrame()
    try:
        df = pd.json_normalize(records, max_level=4)
        log.info("  %s: %d rows × %d cols", label, len(df), len(df.columns))
        return df
    except Exception as e:
        log.warning("json_normalize failed for %s (%s)", label, e)
        return pd.DataFrame(records)


# ── Truk-Way per-truck P&L ─────────────────────────────────────────────────────
# Truk-Way is an Alvys *Fleet* ("Truk-Way Leasing LLC", invoice prefix "T") — an
# owner-operator that runs ~10 trucks under X-Trux. This tab is Truk-Way's own
# per-truck economics, per the chosen definition:
#   Revenue = the settlement X-Trux pays the truck  (Driver Rate + accessorials)
#   Cost    = Truk-Way's all-in QB Total Expenses, allocated to the truck by miles
#   Profit  = Settlement Revenue − Allocated QB Cost
# The QB cost is all-in (includes fuel), so the per-truck Alvys Fuel Cost is shown
# as a reference column only and is NOT subtracted again. Without QB expenses the
# tab degrades to contribution (Rev − Fuel). See docs/knowledge-base/trukway-per-truck.md.
TRUKWAY_FLEET_MATCH = "truk-way"  # case-insensitive substring of the load's Fleet.Name


def _num(series: pd.Series) -> pd.Series:
    """Coerce a column to float, treating blanks/non-numeric as 0."""
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def trukway_total_expenses(qb_pnl: pd.DataFrame | None) -> float | None:
    """Truk-Way Leasing's all-in Total Expenses from the flattened QB
    ProfitAndLoss frame (Company / RowLabel / Col1… as produced by
    ``_flatten_qb_report``). Returns None when it can't be found.

    The amount is taken from the right-most numeric ``Col*`` column on the
    'Total Expenses' row (P&L date-range reports have a single total column).
    """
    if qb_pnl is None or qb_pnl.empty:
        return None
    cols = {c.lower(): c for c in qb_pnl.columns}
    company_col = cols.get("company")
    label_col = cols.get("rowlabel") or cols.get("row_label")
    if not label_col:
        return None

    df = qb_pnl
    if company_col:
        norm = df[company_col].astype(str).map(lambda s: re.sub(r"[^a-z0-9]+", "", s.lower()))
        df = df[norm.str.contains("trukway", na=False)]
    if df.empty:
        return None

    label = df[label_col].astype(str).str.strip().str.lower()
    # Match the operating 'Total Expenses' line; avoid 'Total Other Expenses' / COGS.
    is_total_exp = label.str.replace(r"\s+", " ", regex=True).isin(
        ["total expenses", "total expense"]
    )
    rows = df[is_total_exp]
    if rows.empty:
        return None

    amount_cols = [c for c in df.columns if str(c).lower().startswith("col")]
    for _, r in rows.iterrows():
        for c in reversed(amount_cols):
            val = pd.to_numeric(pd.Series([r.get(c)]), errors="coerce").iloc[0]
            if pd.notna(val) and val != 0:
                return abs(float(val))
    return None


def build_trukway_per_truck(
    df_loads: pd.DataFrame,
    df_fuel: pd.DataFrame,
    qb_total_expenses: float | None = None,
) -> pd.DataFrame:
    """Revenue / fuel / contribution — and, when QB expenses are supplied, true
    net profit — by truck for the Truk-Way fleet.

    When `qb_total_expenses` (Truk-Way Leasing's QuickBooks Total Expenses, an
    all-in figure that already includes fuel) is given, it is allocated across the
    trucks by each truck's share of total miles, and Net Profit = Settlement
    Revenue − Allocated QB Cost. The Alvys per-truck Fuel Cost stays as a
    reference column only (it is *not* subtracted again — the allocated QB cost
    already covers fuel). Without it, the tab stops at contribution (Rev − Fuel).

    Fail-soft: returns an empty frame (skipping the tab) when the loads frame is
    missing, lacks a 'Load Fleet' column, or has no Truk-Way rows.
    """
    log = logging.getLogger("sheets_main.trukway")
    if df_loads is None or df_loads.empty or "Load Fleet" not in df_loads.columns:
        log.info("  Truk-Way: no loads / no 'Load Fleet' column — skipping per-truck tab")
        return pd.DataFrame()

    fleet = df_loads["Load Fleet"].astype(str).str.strip().str.lower()
    tw = df_loads[fleet.str.contains(TRUKWAY_FLEET_MATCH, na=False)].copy()
    if tw.empty:
        log.info("  Truk-Way: no loads matched fleet ~ %r — skipping", TRUKWAY_FLEET_MATCH)
        return pd.DataFrame()

    # Cancelled loads carry no settlement — drop them so they don't dilute $/mi.
    if "Load Status" in tw.columns:
        tw = tw[~tw["Load Status"].astype(str).str.contains("cancel", case=False, na=False)]

    tw["Truck"] = tw.get("Truck", "").astype(str).str.strip()
    tw = tw[(tw["Truck"] != "") & (tw["Truck"].str.lower() != "none")]
    if tw.empty:
        log.info("  Truk-Way: matched loads but none carry a Truck — skipping")
        return pd.DataFrame()

    work = pd.DataFrame({
        "Truck":            tw["Truck"].values,
        "Driver":           tw.get("Driver 1", "").astype(str).values,
        "Linehaul Pay":     _num(tw.get("Driver Rate", 0)).values,
        "Accessorials":     (
            _num(tw.get("Carrier Detention", 0))
            + _num(tw.get("Carrier Lumper", 0))
            + _num(tw.get("Carrier Other Accessorials", 0))
        ).values,
        "Advances":         _num(tw.get("Carrier Advances", 0)).values,
        "Loaded Miles":     _num(tw.get("Loaded Miles", 0)).values,
        "Empty Miles":      _num(tw.get("Empty Miles", 0)).values,
        "Customer Revenue": _num(tw.get("Customer Revenue", 0)).values,
    })
    work["Settlement Revenue"] = work["Linehaul Pay"] + work["Accessorials"]
    work["Total Miles"] = work["Loaded Miles"] + work["Empty Miles"]

    sums = work.groupby("Truck", as_index=False)[[
        "Linehaul Pay", "Accessorials", "Settlement Revenue", "Advances",
        "Loaded Miles", "Empty Miles", "Total Miles", "Customer Revenue",
    ]].sum()
    sums = sums.merge(
        work.groupby("Truck").size().rename("Loads").reset_index(),
        on="Truck", how="left",
    )
    # Most-frequent non-blank driver per truck (helps identify the unit).
    named = work[work["Driver"].str.strip().str.lower().isin(["", "none"]) == False]
    if not named.empty:
        drivers = (
            named.groupby("Truck")["Driver"]
            .agg(lambda s: s.value_counts().idxmax())
            .reset_index()
        )
        sums = sums.merge(drivers, on="Truck", how="left")
    else:
        sums["Driver"] = ""
    sums["Driver"] = sums["Driver"].fillna("")

    # Fuel cost per truck, matched on truck number (Alvys fuel card "Truck").
    fuel_by_truck: dict[str, float] = {}
    if df_fuel is not None and not df_fuel.empty and "Truck" in df_fuel.columns:
        cost_col = next((c for c in ("Total Due", "Net Total") if c in df_fuel.columns), None)
        if cost_col:
            f = df_fuel.copy()
            f["_tk"] = f["Truck"].astype(str).str.strip().str.upper()
            fuel_by_truck = _num(f[cost_col]).groupby(f["_tk"]).sum().to_dict()
    if not fuel_by_truck:
        log.info("  Truk-Way: no fuel matched by truck — Fuel Cost left at 0 (owner-op may self-fuel)")
    sums["Fuel Cost"] = (
        sums["Truck"].astype(str).str.strip().str.upper().map(fuel_by_truck).fillna(0.0)
    )

    sums["Rev - Fuel"] = sums["Settlement Revenue"] - sums["Fuel Cost"]
    miles = sums["Total Miles"]
    sums["Rev / Mile"] = (sums["Settlement Revenue"] / miles).where(miles > 0, 0.0)
    sums["Fuel / Mile"] = (sums["Fuel Cost"] / miles).where(miles > 0, 0.0)

    # True net profit: allocate Truk-Way's all-in QB Total Expenses by mile share.
    fleet_miles = float(sums["Total Miles"].sum())
    allocate = (
        qb_total_expenses is not None
        and float(qb_total_expenses) > 0
        and fleet_miles > 0
    )
    if allocate:
        share = sums["Total Miles"] / fleet_miles
        sums["Allocated QB Cost"] = share * float(qb_total_expenses)
        sums["Net Profit"] = sums["Settlement Revenue"] - sums["Allocated QB Cost"]
        sums["Net / Mile"] = (sums["Net Profit"] / miles).where(miles > 0, 0.0)
    elif qb_total_expenses is not None:
        log.info("  Truk-Way: QB expenses present but not allocatable (no miles) — net profit skipped")

    cols = [
        "Truck", "Driver", "Loads", "Loaded Miles", "Empty Miles", "Total Miles",
        "Linehaul Pay", "Accessorials", "Settlement Revenue", "Fuel Cost", "Rev - Fuel",
    ]
    if allocate:
        cols += ["Allocated QB Cost", "Net Profit", "Net / Mile"]
    cols += ["Rev / Mile", "Fuel / Mile", "Advances", "Customer Revenue"]
    out = sums[cols].sort_values("Settlement Revenue", ascending=False).reset_index(drop=True)

    # TOTAL row (rates recomputed from the totals, not averaged).
    tot_miles = float(out["Total Miles"].sum())
    additive = ["Loads", "Loaded Miles", "Empty Miles", "Total Miles", "Linehaul Pay",
                "Accessorials", "Settlement Revenue", "Fuel Cost", "Rev - Fuel",
                "Advances", "Customer Revenue"]
    if allocate:
        additive += ["Allocated QB Cost", "Net Profit"]
    total = {c: "" for c in cols}
    total["Truck"] = "TOTAL"
    for c in additive:
        total[c] = out[c].sum()
    total["Rev / Mile"] = (total["Settlement Revenue"] / tot_miles) if tot_miles else 0.0
    total["Fuel / Mile"] = (total["Fuel Cost"] / tot_miles) if tot_miles else 0.0
    if allocate:
        total["Net / Mile"] = (total["Net Profit"] / tot_miles) if tot_miles else 0.0
    out = pd.concat([out, pd.DataFrame([total])], ignore_index=True)

    money = ["Linehaul Pay", "Accessorials", "Settlement Revenue", "Fuel Cost",
             "Rev - Fuel", "Advances", "Customer Revenue"]
    rates = ["Rev / Mile", "Fuel / Mile"]
    if allocate:
        money += ["Allocated QB Cost", "Net Profit"]
        rates += ["Net / Mile"]
    for c in money:
        out[c] = _num(out[c]).round(2)
    for c in rates:
        out[c] = _num(out[c]).round(3)
    for c in ("Loads", "Loaded Miles", "Empty Miles", "Total Miles"):
        out[c] = _num(out[c]).round(0).astype("int64")

    if allocate:
        log.info("  Truk-Way: %d trucks, %d loads, $%.0f settlement, $%.0f allocated QB cost, $%.0f net",
                 len(out) - 1, int(total["Loads"]), total["Settlement Revenue"],
                 total["Allocated QB Cost"], total["Net Profit"])
    else:
        log.info("  Truk-Way: %d trucks, %d loads, $%.0f settlement, $%.0f fuel (contribution only)",
                 len(out) - 1, int(total["Loads"]), total["Settlement Revenue"], total["Fuel Cost"])
    return out


# ── Alvys pull ────────────────────────────────────────────────────────────────

def pull_alvys(start_date: str) -> dict[str, pd.DataFrame]:
    from src.alvys_client import AlvysClient
    from src.column_mappings import LOADS_COLUMNS, TRIPS_COLUMNS, FUEL_COLUMNS
    from src.transformers import transform_records
    from src import lookups

    log = logging.getLogger("sheets_main.alvys")
    client_id = get_required("ALVYS_CLIENT_ID")
    client_secret = get_required("ALVYS_CLIENT_SECRET")

    log.info("Connecting to Alvys (start: %s)", start_date)
    client = AlvysClient(client_id, client_secret)
    lookups.build_lookups(client)

    log.info("Fetching loads…")
    raw_loads = client.fetch_loads(start_date=start_date)
    df_loads = pd.DataFrame(transform_records(raw_loads, LOADS_COLUMNS)) if raw_loads else pd.DataFrame()

    log.info("Fetching trips…")
    raw_trips = client.fetch_trips(start_date=start_date)
    df_trips = pd.DataFrame(transform_records(raw_trips, TRIPS_COLUMNS)) if raw_trips else pd.DataFrame()

    log.info("Fetching fuel…")
    raw_fuel = client.fetch_fuel(start_date=start_date)
    df_fuel = pd.DataFrame(transform_records(raw_fuel, FUEL_COLUMNS)) if raw_fuel else pd.DataFrame()

    return {
        "Alvys_Loads": sanitize(df_loads),
        "Alvys_Trips": sanitize(df_trips),
        "Alvys_Fuel":  sanitize(df_fuel),
    }


# ── QuickBooks pull ───────────────────────────────────────────────────────────

def _qb_companies() -> list[dict]:
    return [
        {"name": "X-Trux Inc",       "realm_id": "9341454573269252", "token_env": "QB_XTRUX_REFRESH_TOKEN"},
        {"name": "Truk-Way Leasing",  "realm_id": "9341454569556134", "token_env": "QB_TRUKWAY_REFRESH_TOKEN"},
        {"name": "X-Linx Inc",        "realm_id": "9341454574046601", "token_env": "QB_XLINX_REFRESH_TOKEN"},
        {"name": "N&J Trailers",      "realm_id": os.environ.get("QB_NJ_TRAILERS_REALM_ID", ""),    "token_env": "QB_NJ_TRAILERS_REFRESH_TOKEN"},
        {"name": "N&J Properties",    "realm_id": os.environ.get("QB_NJ_PROPERTIES_REALM_ID", ""),  "token_env": "QB_NJ_PROPERTIES_REFRESH_TOKEN"},
    ]


def pull_quickbooks(start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    from src.qb_client import QBClient
    from src.qb_reports import fetch_report, fetch_entity, ENTITY_QUERIES

    log = logging.getLogger("sheets_main.qb")
    client_id = get_required("QB_CLIENT_ID")
    client_secret = get_required("QB_CLIENT_SECRET")

    # Reports we want — keyed by QB API path segment
    REPORTS = {
        "ProfitAndLoss": {"path": "reports/ProfitAndLoss"},
        "BalanceSheet":  {"path": "reports/BalanceSheet"},
        "CashFlow":      {"path": "reports/CashFlow"},
        "GeneralLedger": {"path": "reports/GeneralLedger"},
        "TrialBalance":  {"path": "reports/TrialBalance"},
    }

    # Override params to use explicit date range instead of date_macro
    date_params = {
        "start_date": start_date,
        "end_date":   end_date,
        "minorversion": 75,
    }

    report_dfs: dict[str, list[pd.DataFrame]] = {r: [] for r in REPORTS}
    entity_dfs: dict[str, list[pd.DataFrame]] = {e: [] for e in ENTITY_QUERIES}

    for company in _qb_companies():
        refresh_token = os.environ.get(company["token_env"], "")
        realm_id = company["realm_id"]
        if not refresh_token or not realm_id:
            log.info("Skipping %-20s (no credentials)", company["name"])
            continue

        log.info("Pulling QB data for: %s", company["name"])
        client = QBClient(client_id, client_secret, realm_id, refresh_token)

        for report_name, cfg in REPORTS.items():
            try:
                # Temporarily override params on the existing fetch_report helper
                import src.qb_reports as qbr
                orig_params = qbr.REPORT_CONFIGS.get(report_name, {}).get("params", {})
                # Call directly via client to pass custom date params
                data = client.get(cfg["path"], params=date_params)
                if data:
                    df = _flatten_qb_report(data, company["name"])
                    if df is not None:
                        report_dfs[report_name].append(df)
            except Exception as e:
                log.warning("  %s / %s failed: %s", company["name"], report_name, e)

        for entity in ENTITY_QUERIES:
            try:
                df = fetch_entity(client, entity, company["name"])
                if df is not None:
                    entity_dfs[entity].append(df)
            except Exception as e:
                log.warning("  %s / %s failed: %s", company["name"], entity, e)

    # Stack all companies together
    result: dict[str, pd.DataFrame] = {}
    for report_name, dfs in report_dfs.items():
        if dfs:
            result[f"QB_{report_name}"] = sanitize(pd.concat(dfs, ignore_index=True))
    for entity, dfs in entity_dfs.items():
        if dfs:
            result[f"QB_{entity}"] = sanitize(pd.concat(dfs, ignore_index=True))

    return result


def _flatten_qb_report(data: dict, company_name: str) -> pd.DataFrame | None:
    """Flatten a QB report JSON response into a tidy DataFrame."""
    log = logging.getLogger("sheets_main.qb")
    try:
        rows = data.get("Rows", {}).get("Row", [])
        if not rows:
            return None
        records = []
        _walk_rows(rows, records, path=[])
        if not records:
            return None
        df = pd.DataFrame(records)
        df.insert(0, "Company", company_name)
        return df
    except Exception as e:
        log.warning("Failed to flatten QB report for %s: %s", company_name, e)
        return None


def _walk_rows(rows: list, out: list, path: list[str]) -> None:
    """Recursively walk QB report rows and emit leaf-level ColData rows."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_type = row.get("type", "")
        header = row.get("Header", {})
        col_data = row.get("ColData", [])
        sub_rows = row.get("Rows", {}).get("Row", [])
        summary = row.get("Summary", {})

        label = ""
        if header and "ColData" in header:
            label = header["ColData"][0].get("value", "") if header["ColData"] else ""

        if col_data and not sub_rows:
            # Leaf row — emit
            values = [c.get("value", "") for c in col_data]
            record = {"RowLabel": label or (values[0] if values else ""), "RowType": row_type}
            for i, v in enumerate(values[1:], 1):
                record[f"Col{i}"] = v
            out.append(record)

        if sub_rows:
            _walk_rows(sub_rows, out, path + [label])

        if summary and "ColData" in summary:
            vals = [c.get("value", "") for c in summary["ColData"]]
            record = {"RowLabel": f"TOTAL {label}", "RowType": "Summary"}
            for i, v in enumerate(vals[1:], 1):
                record[f"Col{i}"] = v
            out.append(record)


# ── Samsara pull ──────────────────────────────────────────────────────────────

def pull_samsara(start_dt: datetime.datetime, end_dt: datetime.datetime) -> dict[str, pd.DataFrame]:
    from src.samsara_client import SamsaraClient

    log = logging.getLogger("sheets_main.samsara")
    api_token = get_required("SAMSARA_API_TOKEN")
    client = SamsaraClient(api_token)

    log.info("Fetching Samsara data (%s → %s)", start_dt.date(), end_dt.date())

    raw_vehicles  = client.fetch_vehicles()
    raw_drivers   = client.fetch_drivers()
    raw_stats     = client.fetch_vehicle_stats()
    raw_locations = client.fetch_locations()

    vehicle_ids = [v["id"] for v in raw_vehicles if "id" in v]
    log.info("Fetching trips for %d vehicles…", len(vehicle_ids))
    raw_trips = client.fetch_trips(start_dt, end_dt, vehicle_ids)

    log.info("Fetching safety events…")
    raw_safety = client.fetch_safety_events(start_dt, end_dt)

    # HOS limited to 30 days max by Samsara API
    hos_start = max(start_dt, end_dt - datetime.timedelta(days=30))
    log.info("Fetching HOS logs (capped at 30 days)…")
    raw_hos = client.fetch_hos_logs(hos_start, end_dt)

    log.info("Fetching DVIRs…")
    raw_dvirs = client.fetch_dvirs(start_dt, end_dt)

    # IFTA — pull available months
    log.info("Fetching IFTA data…")
    ifta_frames = []
    cursor = start_dt.replace(day=1)
    while cursor <= end_dt:
        raw_ifta = client.fetch_ifta(cursor.year, cursor.month)
        if raw_ifta:
            df = flatten(raw_ifta, f"IFTA {cursor.year}-{cursor.month:02d}")
            df.insert(0, "Period", f"{cursor.year}-{cursor.month:02d}")
            ifta_frames.append(df)
        # Advance one month
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)

    sheets = {
        "Samsara_Vehicles":     sanitize(flatten(raw_vehicles,  "Vehicles")),
        "Samsara_Drivers":      sanitize(flatten(raw_drivers,   "Drivers")),
        "Samsara_VehicleStats": sanitize(flatten(raw_stats,     "VehicleStats")),
        "Samsara_Locations":    sanitize(flatten(raw_locations, "Locations")),
        "Samsara_Trips":        sanitize(flatten(raw_trips,     "Trips")),
        "Samsara_Safety":       sanitize(flatten(raw_safety,    "SafetyEvents")),
        "Samsara_HOS":          sanitize(flatten(raw_hos,       "HOS_Logs")),
        "Samsara_DVIRs":        sanitize(flatten(raw_dvirs,     "DVIRs")),
    }
    if ifta_frames:
        sheets["Samsara_IFTA"] = sanitize(pd.concat(ifta_frames, ignore_index=True))

    return sheets


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    setup_logging()
    load_dotenv()
    log = logging.getLogger("sheets_main")

    creds_path = get_required("GCP_SERVICE_ACCOUNT_JSON")
    sheet_id   = get_required("GSHEET_ID")

    start_date_str = os.environ.get("SHEETS_START_DATE", "2022-01-01")
    end_date_str   = datetime.date.today().strftime("%Y-%m-%d")
    start_dt = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
    end_dt   = datetime.datetime.utcnow()

    log.info("=" * 60)
    log.info("XFreight KPI → Google Sheets pipeline")
    log.info("Historical range: %s → %s", start_date_str, end_date_str)
    log.info("Target sheet ID:  %s", sheet_id)
    log.info("=" * 60)

    from src.sheets_writer import SheetsWriter
    writer = SheetsWriter(sheet_id=sheet_id, creds_path=creds_path)

    alvys_sheets: dict[str, pd.DataFrame] = {}
    qb_sheets: dict[str, pd.DataFrame] = {}

    # ── Alvys ──────────────────────────────────────────────────────────────
    log.info("PHASE 1/3: Alvys")
    try:
        alvys_sheets = pull_alvys(start_date_str)
        for tab, df in alvys_sheets.items():
            writer.write_tab(tab, df)
    except Exception as e:
        log.error("Alvys pull failed: %s", e)

    # ── QuickBooks ─────────────────────────────────────────────────────────
    log.info("PHASE 2/3: QuickBooks (all 5 companies)")
    try:
        qb_sheets = pull_quickbooks(start_date_str, end_date_str)
        for tab, df in qb_sheets.items():
            writer.write_tab(tab, df)
    except Exception as e:
        log.error("QuickBooks pull failed: %s", e)

    # ── Truk-Way per-truck P&L (needs Alvys loads/fuel + Truk-Way QB expenses) ──
    try:
        qb_expenses = trukway_total_expenses(qb_sheets.get("QB_ProfitAndLoss"))
        trukway = build_trukway_per_truck(
            alvys_sheets.get("Alvys_Loads"), alvys_sheets.get("Alvys_Fuel"), qb_expenses,
        )
        if not trukway.empty:
            writer.write_tab("Truk-Way Trucks", sanitize(trukway))
        else:
            log.info("Truk-Way per-truck tab skipped (no Truk-Way loads).")
    except Exception as e:
        log.error("Truk-Way per-truck tab failed: %s", e)

    # ── Samsara ────────────────────────────────────────────────────────────
    log.info("PHASE 3/3: Samsara")
    try:
        samsara_sheets = pull_samsara(start_dt, end_dt)
        for tab, df in samsara_sheets.items():
            writer.write_tab(tab, df)
    except Exception as e:
        log.error("Samsara pull failed: %s", e)

    log.info("=" * 60)
    log.info("DONE — data written to Google Sheet")
    log.info("https://docs.google.com/spreadsheets/d/%s", sheet_id)
    log.info("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
