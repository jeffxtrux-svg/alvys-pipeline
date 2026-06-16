"""X-Linx & X-Trux daily cash-flow report — AR (QuickBooks) + AP (Ramp).

Sends one HTML email per Central calendar day at 7am CT via GitHub Actions.

Data sources:
  QuickBooks OneDrive files (staged by the 4am QB pull):
    QuickBooks/QB_AgedReceivableDetail.xlsx  — AR aging by entity
    QuickBooks/QB_AgedPayableDetail.xlsx     — QB-side AP aging by entity
  Ramp API (live, per-entity credentials):
    Open bills for X-Trux Inc + X-Linx Inc

Truk-Way and N&J entities are excluded throughout.

Required env:
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
    ONEDRIVE_USER_UPN
    CASHFLOW_TO_EMAILS          comma-separated (default: ONEDRIVE_USER_UPN)

    QB_CLIENT_ID / QB_CLIENT_SECRET
    QB_XTRUX_REFRESH_TOKEN
    QB_XLINX_REFRESH_TOKEN

    RAMP_XTRUX_CLIENT_ID / RAMP_XTRUX_CLIENT_SECRET
    RAMP_XLINX_CLIENT_ID / RAMP_XLINX_CLIENT_SECRET

Optional:
    CASHFLOW_SKIP_IDEMPOTENCY   set to 1 to force-resend
    SCORECARD_QB_DIR            OneDrive subfolder for QB files (default "QuickBooks")
"""
from __future__ import annotations

import datetime
import io
import logging
import os
import sys
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

from src.onedrive_upload import download_file, ensure_folder, get_token, upload_file
from src.qb_client import QBClient
from src.qb_reports import fetch_report
from src.ramp_client import RampClient
from src.scorecard_email import XFREIGHT_RED, INK, MUTE, LINE, GOOD, GOODBG, BAD, BADBG, WARN, WARNBG, send_email

load_dotenv()
log = logging.getLogger("cashflow_email")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_CT = ZoneInfo("America/Chicago")

# Idempotency marker stored in OneDrive.
_MARKER_FOLDER = "Cashflow"
_MARKER_TPL = "sent-{}.txt"

# QB company config for cashflow scope (X-Trux + X-Linx only).
_QB_COMPANIES = [
    {
        "name": "X-Trux Inc",
        "realm_id": "9341454573269252",
        "token_env": "QB_XTRUX_REFRESH_TOKEN",
    },
    {
        "name": "X-Linx Inc",
        "realm_id": "9341454574046601",
        "token_env": "QB_XLINX_REFRESH_TOKEN",
    },
]

# Bills with an invoice date before this are flagged as "suspect" —
# likely already paid in QuickBooks but not yet reconciled in Ramp.
_SUSPECT_BEFORE = datetime.date(2026, 1, 1)


# ---------------------------------------------------------------------------
# Styling helpers (self-contained so we don't need to import the large
# scorecard_email render helpers).
# ---------------------------------------------------------------------------

def _money(v: float | None) -> str:
    if v is None:
        return "—"
    return f"${v:,.0f}"


def _pill(label: str, color: str, bg: str) -> str:
    return (
        f'<span style="background:{bg};color:{color};padding:2px 8px;'
        f'border-radius:12px;font-size:11px;font-weight:600;">{label}</span>'
    )


def _tile(label: str, value: str, *, color: str = INK, note: str = "") -> str:
    note_html = f'<div style="font-size:11px;color:{MUTE};margin-top:4px;">{note}</div>' if note else ""
    return (
        f'<td style="padding:12px 18px;text-align:center;min-width:130px;">'
        f'<div style="font-size:11px;color:{MUTE};text-transform:uppercase;letter-spacing:.05em;">{label}</div>'
        f'<div style="font-size:22px;font-weight:700;color:{color};margin-top:4px;">{value}</div>'
        f'{note_html}</td>'
    )


def _th(label: str) -> str:
    return (
        f'<th style="padding:6px 10px;text-align:left;font-size:11px;'
        f'text-transform:uppercase;letter-spacing:.05em;color:{MUTE};'
        f'border-bottom:2px solid {LINE};white-space:nowrap;">{label}</th>'
    )


def _td(val: str, *, right: bool = False, bold: bool = False, color: str = INK) -> str:
    align = "right" if right else "left"
    weight = "font-weight:700;" if bold else ""
    return (
        f'<td style="padding:5px 10px;text-align:{align};font-size:13px;'
        f'color:{color};{weight}border-bottom:1px solid {LINE};">{val}</td>'
    )


# ---------------------------------------------------------------------------
# QuickBooks AR aging
# ---------------------------------------------------------------------------

def _qb_aging_bucket(section: str) -> str | None:
    """Map an AgedReceivableDetail section label to an aging bucket."""
    s = section.strip().lower()
    if "current" in s:
        return "Current"
    if "1 - 30" in s or "1-30" in s:
        return "1–30"
    if "31 - 60" in s or "31-60" in s:
        return "31–60"
    if "61 - 90" in s or "61-90" in s:
        return "61–90"
    if "91" in s or "over 90" in s:
        return "91+"
    return None


def compute_ar_aging(ar_df: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Parse QB AgedReceivableDetail DataFrame → {entity: {bucket: amount}}.

    Filters to X-Trux Inc and X-Linx Inc only.
    """
    _TARGET_COMPANIES = {"x-trux inc", "x-linx inc"}
    BUCKETS = ["Current", "1–30", "31–60", "61–90", "91+"]

    result: dict[str, dict[str, float]] = {}
    if ar_df is None or ar_df.empty:
        return result

    data = ar_df[ar_df.get("Row_Type", pd.Series(dtype=str)).astype(str) == "Data"] \
        if "Row_Type" in ar_df.columns else ar_df

    company_col = next(
        (c for c in data.columns if "company" in c.lower()), None
    )
    amt_col = next(
        (c for c in data.columns
         if any(k in c.lower() for k in ("open balance", "amount", "balance"))),
        data.columns[-1] if len(data.columns) else None,
    )

    if amt_col is None:
        return result

    for _, row in data.iterrows():
        company_raw = str(row.get(company_col, "")).strip() if company_col else ""
        if company_raw.lower() not in _TARGET_COMPANIES:
            continue
        bucket = _qb_aging_bucket(str(row.get("Section", "")))
        if bucket is None:
            continue
        amt = pd.to_numeric(pd.Series([row.get(amt_col)]), errors="coerce").iloc[0]
        if not isinstance(amt, float) or amt != amt:  # NaN check
            continue
        if abs(amt) < 1.0:
            continue
        company = company_raw
        if company not in result:
            result[company] = {b: 0.0 for b in BUCKETS}
        result[company][bucket] = result[company].get(bucket, 0.0) + float(amt)

    return result


# ---------------------------------------------------------------------------
# Ramp AP aggregation
# ---------------------------------------------------------------------------

def _ramp_due_days(bill: dict) -> int | None:
    """Days past due (positive = overdue, negative = not yet due)."""
    due_raw = bill.get("due_date") or bill.get("invoice_due_date")
    if not due_raw:
        return None
    try:
        due = datetime.date.fromisoformat(str(due_raw)[:10])
        return (datetime.date.today() - due).days
    except ValueError:
        return None


def _ramp_invoice_date(bill: dict) -> datetime.date | None:
    raw = bill.get("invoice_date") or bill.get("created_at")
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _ramp_amount(bill: dict) -> float:
    """Extract bill total amount in USD."""
    # Ramp stores amounts in cents or as a float depending on API version.
    amt = bill.get("amount") or bill.get("total_amount") or {}
    if isinstance(amt, dict):
        # {"amount": 12345, "currency_code": "USD"} — amount in cents
        raw = float(amt.get("amount", 0))
        # Ramp v1 amounts are in cents; divide by 100 for dollars.
        return raw / 100.0 if raw > 100 else raw
    try:
        return float(amt)
    except (TypeError, ValueError):
        return 0.0


def _ramp_vendor_name(bill: dict) -> str:
    vendor = bill.get("vendor")
    if isinstance(vendor, dict):
        return vendor.get("name") or vendor.get("remote_name") or "Unknown"
    return str(bill.get("vendor_name") or bill.get("counterparty_name") or "Unknown")


def aggregate_ramp_ap(bills: list[dict], entity_name: str) -> dict:
    """Aggregate open Ramp bills into a summary dict for one entity."""
    confirmed_total = 0.0
    suspect_total = 0.0
    vendor_totals: dict[str, dict] = {}

    for bill in bills:
        amt = _ramp_amount(bill)
        inv_date = _ramp_invoice_date(bill)
        is_suspect = inv_date is not None and inv_date < _SUSPECT_BEFORE
        vendor = _ramp_vendor_name(bill)

        if is_suspect:
            suspect_total += amt
        else:
            confirmed_total += amt

        if vendor not in vendor_totals:
            vendor_totals[vendor] = {"confirmed": 0.0, "suspect": 0.0, "count": 0}
        vendor_totals[vendor]["count"] += 1
        if is_suspect:
            vendor_totals[vendor]["suspect"] += amt
        else:
            vendor_totals[vendor]["confirmed"] += amt

    vendors_sorted = sorted(
        [{"vendor": v, **d} for v, d in vendor_totals.items()],
        key=lambda x: -(x["confirmed"] + x["suspect"]),
    )

    return {
        "entity": entity_name,
        "confirmed_total": confirmed_total,
        "suspect_total": suspect_total,
        "total": confirmed_total + suspect_total,
        "count": len(bills),
        "vendors": vendors_sorted,
    }


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _section_header(title: str) -> str:
    return (
        f'<tr><td colspan="99" style="padding:18px 10px 6px;">'
        f'<div style="font-size:13px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:.08em;color:{XFREIGHT_RED};border-bottom:2px solid {XFREIGHT_RED};'
        f'padding-bottom:4px;">{title}</div></td></tr>'
    )


def build_html(
    run_dt: datetime.datetime,
    ar_by_company: dict[str, dict[str, float]],
    ramp_xtrux: dict,
    ramp_xlinx: dict,
) -> str:
    today_label = run_dt.strftime("%-m/%-d/%Y")

    # --- Summary totals ---
    BUCKETS = ["Current", "1–30", "31–60", "61–90", "91+"]

    def _ar_total(company_data: dict[str, float]) -> float:
        return sum(company_data.values())

    ar_combined = 0.0
    for co_data in ar_by_company.values():
        ar_combined += _ar_total(co_data)

    ap_confirmed = ramp_xtrux["confirmed_total"] + ramp_xlinx["confirmed_total"]
    ap_suspect = ramp_xtrux["suspect_total"] + ramp_xlinx["suspect_total"]
    ap_combined = ap_confirmed + ap_suspect  # full Ramp open balance
    net_position = ar_combined - ap_confirmed  # net = AR minus confirmed AP

    net_color = GOOD if net_position >= 0 else BAD
    net_bg = GOODBG if net_position >= 0 else BADBG

    # --- AR aging table rows ---
    def _ar_rows() -> str:
        rows = ""
        combined: dict[str, float] = {b: 0.0 for b in BUCKETS}
        for company, buckets in sorted(ar_by_company.items()):
            total = _ar_total(buckets)
            rows += "<tr>"
            rows += _td(company, bold=True)
            for b in BUCKETS:
                rows += _td(_money(buckets.get(b, 0.0)), right=True)
            rows += _td(_money(total), right=True, bold=True)
            rows += "</tr>"
            for b in BUCKETS:
                combined[b] = combined.get(b, 0.0) + buckets.get(b, 0.0)
        if ar_by_company:
            rows += '<tr style="background:#f8f8f8;">'
            rows += _td("Combined", bold=True)
            for b in BUCKETS:
                rows += _td(_money(combined.get(b, 0.0)), right=True, bold=True)
            rows += _td(_money(sum(combined.values())), right=True, bold=True, color=XFREIGHT_RED)
            rows += "</tr>"
        return rows

    # --- Ramp AP table rows ---
    def _ap_entity_row(data: dict) -> str:
        confirmed = data["confirmed_total"]
        suspect = data["suspect_total"]
        total = data["total"]
        suspect_note = (
            f' {_pill("incl. suspect", WARN, WARNBG)}' if suspect > 0 else ""
        )
        row = "<tr>"
        row += _td(data["entity"], bold=True)
        row += _td(str(data["count"]), right=True)
        row += _td(_money(confirmed), right=True)
        row += _td(_money(suspect) + suspect_note, right=True)
        row += _td(_money(total), right=True, bold=True)
        row += "</tr>"
        return row

    def _vendor_table(vendors: list[dict], *, max_rows: int = 10) -> str:
        rows = ""
        for v in vendors[:max_rows]:
            total = v["confirmed"] + v["suspect"]
            suspect_note = f' {_pill("suspect", WARN, WARNBG)}' if v["suspect"] > 0 else ""
            rows += "<tr>"
            rows += _td(v["vendor"])
            rows += _td(str(v["count"]), right=True)
            rows += _td(_money(v["confirmed"]), right=True)
            rows += _td(_money(v["suspect"]) + suspect_note, right=True)
            rows += _td(_money(total), right=True, bold=True)
            rows += "</tr>"
        return rows

    suspect_note_html = ""
    if ap_suspect > 0:
        suspect_note_html = (
            f'<tr><td colspan="99" style="padding:4px 10px 10px;">'
            f'<div style="font-size:11px;color:{WARN};background:{WARNBG};'
            f'padding:6px 10px;border-radius:4px;">'
            f'<strong>Suspect bills ({_money(ap_suspect)}):</strong> '
            f'Invoice dates before Jan 2026 — likely already paid in QuickBooks '
            f'but not yet reconciled in Ramp. Audra to verify.'
            f'</div></td></tr>'
        )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ font-family: Arial, sans-serif; color: {INK}; background: #fff; margin: 0; padding: 0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  a {{ color: {XFREIGHT_RED}; }}
</style>
</head>
<body>
<div style="max-width:720px;margin:0 auto;padding:20px;">

<!-- Header -->
<table style="margin-bottom:18px;">
  <tr>
    <td>
      <div style="font-size:22px;font-weight:700;color:{XFREIGHT_RED};">
        X-Linx &amp; X-Trux Cash Flow
      </div>
      <div style="font-size:13px;color:{MUTE};margin-top:2px;">{today_label} &mdash; as of {run_dt.strftime("%-I:%M %p")} CT</div>
    </td>
  </tr>
</table>

<!-- Summary tiles -->
<table style="margin-bottom:22px;background:#f8f8f8;border-radius:8px;">
  <tr>
    {_tile("Total AR (QB)", _money(ar_combined), note="QuickBooks open balance")}
    <td style="width:1px;background:{LINE};">&nbsp;</td>
    {_tile("Open AP (Ramp)", _money(ap_confirmed), note=f"confirmed 2026+ ({_money(ap_suspect)} suspect)")}
    <td style="width:1px;background:{LINE};">&nbsp;</td>
    {_tile("Net Position", _money(net_position), color=net_color, note="AR − confirmed AP")}
  </tr>
</table>

<!-- AR Aging -->
<table style="margin-bottom:22px;">
  {_section_header("Accounts Receivable — QuickBooks")}
  <tr>
    {_th("Entity")}
    {_th("Current")}
    {_th("1–30 days")}
    {_th("31–60 days")}
    {_th("61–90 days")}
    {_th("91+ days")}
    {_th("Total")}
  </tr>
  {"".join(['<tr><td colspan="99" style="padding:20px;text-align:center;color:' + MUTE + ';font-size:13px;">No AR data — QB pull may not have run yet.</td></tr>']) if not ar_by_company else _ar_rows()}
</table>

<!-- AP Entity summary -->
<table style="margin-bottom:10px;">
  {_section_header("Accounts Payable — Ramp (Open Bills)")}
  <tr>
    {_th("Entity")}
    {_th("# Bills")}
    {_th("Confirmed (2026+)")}
    {_th("Suspect (pre-2026)")}
    {_th("Total Open")}
  </tr>
  {_ap_entity_row(ramp_xtrux)}
  {_ap_entity_row(ramp_xlinx)}
  <tr style="background:#f8f8f8;">
    {_td("Combined", bold=True)}
    {_td(str(ramp_xtrux["count"] + ramp_xlinx["count"]), right=True, bold=True)}
    {_td(_money(ap_confirmed), right=True, bold=True)}
    {_td(_money(ap_suspect), right=True, bold=True)}
    {_td(_money(ap_combined), right=True, bold=True, color=XFREIGHT_RED)}
  </tr>
  {suspect_note_html}
</table>

<!-- AP vendor breakdown — X-Trux -->
<table style="margin-bottom:22px;">
  {_section_header("Top AP Vendors — X-Trux")}
  <tr>{_th("Vendor")}{_th("Bills")}{_th("Confirmed")}{_th("Suspect")}{_th("Total")}</tr>
  {"".join(['<tr><td colspan="99" style="padding:12px 10px;color:' + MUTE + ';font-size:13px;">No open Ramp bills for X-Trux.</td></tr>']) if not ramp_xtrux["vendors"] else _vendor_table(ramp_xtrux["vendors"])}
</table>

<!-- AP vendor breakdown — X-Linx -->
<table style="margin-bottom:22px;">
  {_section_header("Top AP Vendors — X-Linx")}
  <tr>{_th("Vendor")}{_th("Bills")}{_th("Confirmed")}{_th("Suspect")}{_th("Total")}</tr>
  {"".join(['<tr><td colspan="99" style="padding:12px 10px;color:' + MUTE + ';font-size:13px;">No open Ramp bills for X-Linx.</td></tr>']) if not ramp_xlinx["vendors"] else _vendor_table(ramp_xlinx["vendors"])}
</table>

<!-- Footer -->
<div style="font-size:11px;color:{MUTE};border-top:1px solid {LINE};padding-top:10px;margin-top:8px;">
  AR data from QuickBooks via OneDrive (staged at 4am CT). AP data from Ramp API (live).
  Truk-Way and N&amp;J entities excluded. Suspect bills = invoice date before Jan 1, 2026.
</div>

</div>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def _marker_path(date: datetime.date) -> str:
    return f"{_MARKER_FOLDER}/{_MARKER_TPL.format(date.isoformat())}"


def _marker_exists(token: str, upn: str, date: datetime.date) -> bool:
    try:
        download_file(token, upn, _marker_path(date))
        return True
    except Exception:
        return False


def _write_marker(token: str, upn: str, date: datetime.date) -> None:
    try:
        ensure_folder(token, upn, _MARKER_FOLDER)
        upload_file(
            token, upn,
            io.BytesIO(f"sent {date.isoformat()}".encode()),
            _MARKER_FOLDER,
            _MARKER_TPL.format(date.isoformat()),
        )
    except Exception as exc:
        log.warning("Could not write cashflow idempotency marker: %s", exc)


# ---------------------------------------------------------------------------
# QB AR data load
# ---------------------------------------------------------------------------

def _load_ar_from_onedrive(token: str, upn: str, qb_dir: str) -> pd.DataFrame | None:
    path = f"{qb_dir}/QB_AgedReceivableDetail.xlsx"
    try:
        raw = download_file(token, upn, path)
        sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None)
        if not sheets:
            return None
        return next(iter(sheets.values()))
    except Exception as exc:
        log.warning("Could not read QB AR aging from OneDrive (%s): %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()

    tenant = os.environ["AZURE_TENANT_ID"]
    client_id = os.environ["AZURE_CLIENT_ID"]
    client_secret = os.environ["AZURE_CLIENT_SECRET"]
    upn = os.environ["ONEDRIVE_USER_UPN"]
    to_raw = os.environ.get("CASHFLOW_TO_EMAILS") or upn
    to_emails = [e.strip() for e in to_raw.split(",") if e.strip()]
    skip_idempotency = os.environ.get("CASHFLOW_SKIP_IDEMPOTENCY", "").strip() == "1"
    qb_dir = os.environ.get("SCORECARD_QB_DIR", "QuickBooks").strip("/")

    now_ct = datetime.datetime.now(tz=_CT)
    today = now_ct.date()

    log.info("=== X-Linx & X-Trux Cash Flow email — %s ===", today.isoformat())

    tok = get_token(tenant, client_id, client_secret)

    # Idempotency check.
    if not skip_idempotency and _marker_exists(tok, upn, today):
        log.info("Marker exists for %s — skipping (set CASHFLOW_SKIP_IDEMPOTENCY=1 to override).", today)
        return

    # --- AR from OneDrive (QuickBooks staged files) ---
    log.info("Reading QB AR aging from OneDrive…")
    ar_df = _load_ar_from_onedrive(tok, upn, qb_dir)
    ar_by_company = compute_ar_aging(ar_df) if ar_df is not None else {}
    if not ar_by_company:
        log.warning("No QB AR data available — AR section will be empty.")

    # --- AP from Ramp (live API) ---
    ramp_results: dict[str, dict] = {}
    ramp_configs = [
        ("X-Trux Inc",  "RAMP_XTRUX_CLIENT_ID",  "RAMP_XTRUX_CLIENT_SECRET"),
        ("X-Linx Inc",  "RAMP_XLINX_CLIENT_ID",  "RAMP_XLINX_CLIENT_SECRET"),
    ]
    for entity_name, id_env, secret_env in ramp_configs:
        r_id = os.environ.get(id_env, "").strip()
        r_secret = os.environ.get(secret_env, "").strip()
        if not r_id or not r_secret:
            log.warning("%s Ramp credentials not set (%s / %s) — AP will be empty for this entity.",
                        entity_name, id_env, secret_env)
            ramp_results[entity_name] = aggregate_ramp_ap([], entity_name)
            continue
        try:
            client = RampClient(r_id, r_secret, entity_name)
            bills = client.fetch_open_bills()
            ramp_results[entity_name] = aggregate_ramp_ap(bills, entity_name)
        except Exception as exc:
            log.error("Ramp fetch failed for %s: %s", entity_name, exc)
            ramp_results[entity_name] = aggregate_ramp_ap([], entity_name)

    ramp_xtrux = ramp_results.get("X-Trux Inc", aggregate_ramp_ap([], "X-Trux Inc"))
    ramp_xlinx = ramp_results.get("X-Linx Inc", aggregate_ramp_ap([], "X-Linx Inc"))

    # --- Build and send ---
    log.info("Building HTML…")
    html = build_html(now_ct, ar_by_company, ramp_xtrux, ramp_xlinx)

    subject = f"X-Linx & X-Trux Cash Flow — {today.strftime('%-m/%-d/%Y')}"
    log.info("Sending to %s…", ", ".join(to_emails))
    send_email(tok, upn, to_emails, subject, html)

    _write_marker(tok, upn, today)
    log.info("Cash-flow email sent. Done.")


if __name__ == "__main__":
    main()
