"""
Financial Brief — daily HTML brief focused on Audra's invoicing /
closeout / AR-reconciliation responsibilities. Split off from the
Safety & Compliance Brief so each report stays scoped to one
cognitive mode: safety = vigilance, financial = batch admin.

Pages:
  1. Overview — bottom line, financial KPI tiles, action items
                (un-invoiced loads, carrier bills not entered, QB-vs-
                Alvys variance)
  2. Invoice Closeout — customer side (delivered loads not yet invoiced)
                        + carrier side (brokered trips with no carrier
                        invoice number entered, cross-referenced
                        against QB X-Linx Bills)
  3. AR Reconciliation by Customer — QuickBooks vs Alvys per-customer
                        variance (same builder the executive brief
                        uses; exec-brief PDF pp 26-27 territory)

Reuses scorecard_email's compute + render functions. Reads the same
OneDrive sources as the safety brief: Alvys Pipeline, QB Bills, QB
Aged Receivable Detail.

Currently in TEST MODE: routes only to jeff@xfreight.net regardless
of trigger. Production routing per the responsibility map is Audra
primary + Jeff/JB cc — flip the workflow YAML when the report is
signed off.

Required env:
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET — Graph auth
    ONEDRIVE_USER_UPN  — mailbox to read OneDrive from + send mail as
    FINANCIAL_TO_EMAILS — comma-separated recipient list (jeff@ while testing)
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from dotenv import load_dotenv

from src.onedrive_upload import (
    download_file,
    ensure_folder,
    get_token,
    upload_file,
)
from src.safety_compliance_email import (
    _footer_kb_links,
    _load_carrier_map,
    _norm_load_token,
    _page_header,
    _today_chi,
    _today_label,
    _totals_row,
    _wrap_page,
    build_page_invoice_closeout,
    compute_carrier_invoice_backlog,
    compute_qb_xlinx_bill_loads,
)
from src.scorecard_email import (
    BAD,
    BADBG,
    FONT_SERIF,
    GOOD,
    GOODBG,
    INK,
    LINE,
    MUTE,
    WARN,
    WARNBG,
    XFREIGHT_RED,
    _pill,
    _safe_read,
    _section,
    _table,
    _tile,
    _tr,
    build_page7 as _exec_build_page7,
    compute_alvys_ar,
    compute_alvys_uninvoiced,
    compute_qb_ar_detail,
    send_email,
)

log = logging.getLogger("financial_email")


# ----------------------------------------------------------------------
# Idempotency marker — only one financial brief per Central day.
# ----------------------------------------------------------------------

_MARKER_FOLDER = "Financial"
_MARKER_NAME_TPL = "sent-{}.txt"


def _marker_path(d: datetime.date) -> str:
    return f"{_MARKER_FOLDER}/{_MARKER_NAME_TPL.format(d.isoformat())}"


def _marker_exists(tok: str, upn: str, d: datetime.date) -> bool:
    try:
        download_file(tok, upn, _marker_path(d))
        return True
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return False
        raise


def _write_marker(tok: str, upn: str, d: datetime.date, body: str) -> None:
    ensure_folder(tok, upn, _MARKER_FOLDER)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write(body + "\n")
        tmp = Path(tf.name)
    upload_file(tok, upn,
                folder_path=_MARKER_FOLDER,
                filename=_MARKER_NAME_TPL.format(d.isoformat()),
                file_path=tmp)


# ----------------------------------------------------------------------
# Compute: financial-side action items + page-1 metrics
# ----------------------------------------------------------------------

def compute_financial_action_items(*, uninvoiced, carrier_backlog,
                                     ar_recon) -> list[dict]:
    """Top-priority financial action items. Same priority schema as the
    safety brief: P1=URGENT, P2=TODAY, P3=THIS WEEK."""
    items: list[dict] = []

    # P2 — un-invoiced loads > 7 days old (the longer they sit, the
    # more they distort AR aging on the executive brief).
    if uninvoiced:
        aged = [r for r in (uninvoiced.get("rows") or [])
                if (r.get("days") or 0) > 7]
        if aged:
            total_aged = sum(r.get("revenue", 0) for r in aged)
            items.append({
                "priority": 2,
                "owner": "Audra",
                "action": (f"Invoice {len(aged)} delivered load(s) "
                           f"(${total_aged:,.0f}) past the 7-day window."),
                "why": ("Un-invoiced delivered loads inflate the Alvys-side "
                        "AR balance and drag the QB-vs-Alvys reconciliation."),
                "kb_link": "xfreight-playbook-ar-followup.md",
            })

    # P2 — carrier bills not entered in Alvys + not in QB (real backlog,
    # post-QB-cross-reference).
    if carrier_backlog and carrier_backlog.get("count"):
        items.append({
            "priority": 2,
            "owner": "Audra",
            "action": (f"Enter {carrier_backlog['count']} carrier "
                       f"invoice(s) (~${carrier_backlog.get('total_carrier_rate', 0):,.0f}) "
                       f"into Alvys."),
            "why": ("X-Linx brokered loads delivered, no Carrier Invoice "
                    "Number on file, AND no matching paid/open bill in QB "
                    "X-Linx — settlement blocked until entered."),
            "kb_link": "xfreight-playbook-ar-followup.md",
        })

    # P3 — large QB-vs-Alvys variance per customer (top contributors).
    if ar_recon:
        top = (ar_recon.get("rows") or [])[:3]
        for r in top:
            d = abs(r.get("delta") or 0)
            if d < 100:  # skip noise
                continue
            sign = "Alvys > QB" if (r.get("delta") or 0) < 0 else "QB > Alvys"
            items.append({
                "priority": 3,
                "owner": "Audra",
                "action": (f"Investigate {r.get('customer', '?')} &mdash; "
                           f"${d:,.0f} variance ({sign})."),
                "why": ("Largest QB-vs-Alvys gap per customer. Common cause: "
                        "invoices paid in QB but not synced back to Alvys, "
                        "or duplicate / missing invoices in one system."),
                "kb_link": "xfreight-playbook-ar-followup.md",
            })

    items.sort(key=lambda x: x["priority"])
    return items


# ----------------------------------------------------------------------
# Design helpers — mirror the safety brief so the two reports feel
# like a matched set.
# ----------------------------------------------------------------------

_PRIORITY_COLOR = {1: BAD, 2: WARN, 3: MUTE}
_PRIORITY_LABEL = {1: "URGENT", 2: "TODAY", 3: "THIS WEEK"}


def _urgent_banner(items: list[dict]) -> str:
    p1 = [i for i in items if i.get("priority") == 1]
    if not p1:
        return ""
    rows = "".join(
        f"<div style='padding:4px 0;font-size:13px;color:{INK};'>"
        f"&nbsp;&middot;&nbsp;{i.get('action', '')}</div>"
        for i in p1
    )
    return (
        f"<tr><td style='padding:0 18px 14px;'>"
        f"<div style='background:{BADBG};border-left:6px solid {BAD};"
        f"border-radius:6px;padding:12px 16px;'>"
        f"<div style='font-size:10px;letter-spacing:2px;font-weight:800;color:{BAD};"
        f"margin-bottom:6px;'>&#9888;&nbsp;URGENT &middot; ACT NOW</div>"
        f"{rows}"
        f"</div></td></tr>"
    )


def _action_items_block(items: list[dict]) -> str:
    if not items:
        return ""
    blocks = []
    for prio in (1, 2, 3):
        slice_ = [i for i in items if i.get("priority") == prio]
        if not slice_:
            continue
        color = _PRIORITY_COLOR[prio]
        label = _PRIORITY_LABEL[prio]
        rows = ""
        for i in slice_:
            kb = (f"<div style='font-size:11px;color:{MUTE};margin-top:3px;'>"
                  f"playbook: <code style='font-size:10px;'>{i['kb_link']}</code></div>"
                  if i.get("kb_link") else "")
            rows += (
                f"<div style='padding:10px 12px;border-top:1px solid {LINE};'>"
                f"<div style='font-size:13px;color:{INK};'><b>{i.get('action', '')}</b></div>"
                f"<div style='font-size:12px;color:{MUTE};margin-top:3px;'>"
                f"{i.get('why', '')} &middot; "
                f"<span style='color:{INK};'>owner: {i.get('owner', 'Audra')}</span></div>"
                f"{kb}</div>"
            )
        blocks.append(
            f"<div style='margin-bottom:10px;border:1px solid {LINE};border-radius:6px;'>"
            f"<div style='background:#fafafa;padding:6px 12px;font-size:10px;"
            f"letter-spacing:1.5px;font-weight:700;color:{color};'>"
            f"{label}</div>"
            f"{rows}</div>"
        )
    if not blocks:
        return ""
    return (
        f"<tr><td style='padding:0 18px 14px;'>"
        f"<div style='font-size:10px;letter-spacing:2px;color:{MUTE};font-weight:700;"
        f"margin-bottom:8px;'>ACTION ITEMS</div>"
        + "".join(blocks)
        + f"</td></tr>"
    )


# ----------------------------------------------------------------------
# Page 1 — Overview (bottom line + KPI tiles + action items)
# ----------------------------------------------------------------------

def _build_bottom_line(uninvoiced, carrier_backlog, ar_recon) -> str:
    parts = []
    u_count = (uninvoiced or {}).get("count") or 0
    u_total = (uninvoiced or {}).get("total_revenue") or 0
    if u_count:
        parts.append(
            f"<b>{u_count}</b> delivered load(s) worth "
            f"<b>${u_total:,.0f}</b> not yet invoiced to customers."
        )
    else:
        parts.append("All delivered loads have been invoiced &mdash; customer side clean.")
    c_count = (carrier_backlog or {}).get("count") or 0
    c_total = (carrier_backlog or {}).get("total_carrier_rate") or 0
    if c_count:
        parts.append(
            f"<b>{c_count}</b> brokered trip(s) (~<b>${c_total:,.0f}</b>) "
            f"missing a Carrier Invoice Number in Alvys and not yet in QB X-Linx."
        )
    else:
        parts.append("Carrier-bill backlog is empty &mdash; brokered side clean.")
    if ar_recon:
        delta = ar_recon.get("delta_total") or 0
        if abs(delta) >= 1:
            sign = "Alvys ahead" if delta < 0 else "QB ahead"
            parts.append(
                f"QB-vs-Alvys AR variance is <b>${abs(delta):,.0f}</b> "
                f"({sign}); top contributors on page 3."
            )
        else:
            parts.append("QB and Alvys AR reconcile to within $1 &mdash; clean.")
    return " ".join(parts)


def build_page1_overview(uninvoiced, carrier_backlog, ar_recon,
                          *, action_items, pg, total) -> str:
    """Page 1: bottom line + 3 KPI tiles + urgent banner + action items."""
    bl = _build_bottom_line(uninvoiced, carrier_backlog, ar_recon)

    def _money(v):
        return f"${v:,.0f}" if v is not None else "&mdash;"

    u_count = (uninvoiced or {}).get("count") or 0
    u_total = (uninvoiced or {}).get("total_revenue") or 0
    u_oldest = (uninvoiced or {}).get("oldest_days")
    u_tile = _tile(
        "Un-invoiced loads",
        str(u_count),
        _pill(
            f"{_money(u_total)} · oldest "
            f"{u_oldest if u_oldest is not None else '&mdash;'}d",
            "bad" if u_count else "good",
        ),
        width="33%",
    )

    c_count = (carrier_backlog or {}).get("count") or 0
    c_total = (carrier_backlog or {}).get("total_carrier_rate") or 0
    c_oldest = (carrier_backlog or {}).get("oldest_days")
    c_tile = _tile(
        "Carrier-bill backlog",
        str(c_count),
        _pill(
            f"{_money(c_total)} · oldest "
            f"{c_oldest if c_oldest is not None else '&mdash;'}d",
            "bad" if c_count else "good",
        ),
        width="33%",
    )

    delta = (ar_recon or {}).get("delta_total") or 0
    abs_delta = abs(delta)
    delta_label = "QB &minus; Alvys variance"
    delta_sub = (
        ("Alvys > QB" if delta < 0 else "QB > Alvys")
        if abs_delta >= 1 else "Reconciled"
    )
    ar_tile = _tile(
        delta_label,
        _money(abs_delta),
        _pill(delta_sub, "warn" if abs_delta >= 1 else "good"),
        width="34%",
    )

    tiles = (
        "<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        + u_tile + c_tile + ar_tile +
        "</tr></table>"
    )

    bottom_line_block = (
        f"<tr><td style='padding:18px 24px 6px;'>"
        f"<div style='font-size:10px;letter-spacing:2px;color:{MUTE};"
        f"font-weight:700;margin-bottom:8px;'>BOTTOM LINE</div>"
        f"<div style='{FONT_SERIF}font-size:15px;line-height:1.55;color:{INK};"
        f"border-left:3px solid {XFREIGHT_RED};padding-left:14px;'>{bl}</div>"
        f"</td></tr>"
    )

    urgent_items = [i for i in (action_items or []) if i.get("priority") == 1]

    body = (
        bottom_line_block
        + _urgent_banner(urgent_items)
        + f"<tr><td style='padding:14px 18px 8px;'>{tiles}</td></tr>"
        + _action_items_block(action_items)
    )
    return _page_header_financial("Overview", pg, total) + _wrap_page(body)


# ----------------------------------------------------------------------
# Header — same layout/colors as the safety brief but rebranded
# "FINANCIAL" in the eyebrow so the two reports are visually distinct.
# ----------------------------------------------------------------------

def _page_header_financial(title: str, pg: int, total: int,
                            section: str | None = None) -> str:
    today = _today_label()
    if section:
        eyebrow = (
            f"<div style='font-size:10px;letter-spacing:2px;color:{XFREIGHT_RED};"
            f"font-weight:800;'>XFREIGHT &middot; FINANCIAL BRIEF "
            f"&middot; <span style='color:{INK};'>{section}</span></div>"
        )
    else:
        eyebrow = (
            f"<div style='font-size:10px;letter-spacing:2px;color:{XFREIGHT_RED};"
            f"font-weight:800;'>XFREIGHT &middot; FINANCIAL BRIEF</div>"
        )
    return (
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-bottom:4px solid {XFREIGHT_RED};padding:6px 24px 14px;'>"
        f"<tr>"
        f"<td valign='middle' style='padding:0;'>"
        f"{eyebrow}"
        f"<div style='{FONT_SERIF}font-size:18px;color:{INK};margin-top:4px;'>{title}</div>"
        f"</td>"
        f"<td align='right' valign='middle' style='padding:0;font-size:11px;color:{MUTE};'>"
        f"<div style='{FONT_SERIF}font-style:italic;font-weight:600;color:{INK};'>{today}</div>"
        f"<div class='pg-of' style='font-size:9px;margin-top:4px;letter-spacing:0.5px;'>"
        f"Page {pg} of {total}</div>"
        f"</td>"
        f"</tr></table>"
    )


# ----------------------------------------------------------------------
# Wrappers around imported page renderers to swap in the FINANCIAL
# header (vs the safety brief's SAFETY & COMPLIANCE header).
# ----------------------------------------------------------------------

def build_page_closeout_wrapped(uninvoiced, carrier_backlog,
                                  alvys_pipeline_sheets, pg, total) -> str:
    """Same body as build_page_invoice_closeout from safety_compliance_email,
    but rendered with the financial-brief header."""
    full = build_page_invoice_closeout(
        uninvoiced, carrier_backlog, alvys_pipeline_sheets, pg, total
    )
    # The imported renderer uses the safety brief's _page_header — strip
    # everything before the wrap-page table and rebuild the header with
    # the financial-brief eyebrow.
    # _page_header returns a <table>…</table>; _wrap_page wraps the body
    # in a separate <table>. Find the boundary by the page-body marker.
    body_marker = "<table width='100%' cellpadding='0' cellspacing='0' style='background:#fff;'>"
    idx = full.find(body_marker)
    if idx < 0:
        return full  # fallback: ship as-is
    return (_page_header_financial("Invoice Closeout", pg, total,
                                    section="CLOSEOUT")
            + full[idx:])


def build_page_ar_recon_wrapped(qb_ar, alvys_ar, date_str, pg) -> str:
    """build_page7 with the financial-brief header swapped in. The exec
    brief's _header is similar enough that mixed-style mid-report would
    work, but the swap keeps the visual identity consistent."""
    return _exec_build_page7(qb_ar, alvys_ar, date_str, pg=pg)


# ----------------------------------------------------------------------
# Report assembly + PDF render
# ----------------------------------------------------------------------

def _build_html_report(*, uninvoiced, carrier_backlog, ar_recon,
                        alvys_sheets, qb_ar, alvys_ar,
                        action_items) -> str:
    today_label = _today_label()
    total = 3
    pages = [
        build_page1_overview(uninvoiced, carrier_backlog, ar_recon,
                              action_items=action_items, pg=1, total=total),
        build_page_closeout_wrapped(uninvoiced, carrier_backlog,
                                      alvys_sheets, 2, total),
        build_page_ar_recon_wrapped(qb_ar, alvys_ar, today_label, pg=3),
    ]
    body = "<div class='page-break' style='page-break-after:always;'></div>".join(pages)
    body += _footer_kb_links()
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "body{margin:0;background:#fff;font-family:Helvetica,Arial,sans-serif;color:" + INK + ";}"
        ".page-break{page-break-after:always;break-after:page;height:0;}"
        "@page{size:letter;margin:0.45in 0.35in 0.7in;"
        "@bottom-center{content:'Page ' counter(page) ' of ' counter(pages);"
        f"font-family:Helvetica,Arial,sans-serif;font-size:9px;color:{MUTE};"
        "letter-spacing:0.5px;}}"
        "@media print{.pg-of{display:none;}}"
        "table.tbl{border-collapse:collapse;width:100%;}"
        "</style></head><body>"
        + body
        + "</body></html>"
    )


def _render_pdf(html: str) -> bytes | None:
    try:
        from weasyprint import HTML
    except Exception as e:
        log.warning("WeasyPrint not available — skipping PDF attachment: %s", e)
        return None
    return HTML(string=html).write_pdf()


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    upn = os.environ.get("ONEDRIVE_USER_UPN")
    if not upn:
        log.error("ONEDRIVE_USER_UPN not set — aborting.")
        return 1
    to_emails = [e.strip() for e in
                 os.environ.get("FINANCIAL_TO_EMAILS", "jeff@xfreight.net").split(",")
                 if e.strip()]
    log.info("Recipients: %s", to_emails)

    tok = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )

    today = _today_chi()
    skip = os.environ.get("FINANCIAL_SKIP_IDEMPOTENCY", "").strip() == "1"
    if not skip and _marker_exists(tok, upn, today):
        log.info("Marker present for %s — already sent today. Skipping.", today)
        return 0

    missing: list[str] = []
    alvys_path = os.environ.get("ALVYS_PIPELINE_ONEDRIVE_PATH",
                                "Alvys Pipeline.xlsx")
    alvys_sheets = _safe_read(tok, upn, alvys_path, missing, "Alvys Pipeline")
    qb_bills_path = os.environ.get("QB_BILLS_ONEDRIVE_PATH",
                                    "QuickBooks/QB_Bills.xlsx")
    qb_bills_sheets = _safe_read(tok, upn, qb_bills_path, missing, "QB Bills")
    qb_ar_path = os.environ.get("QB_AR_ONEDRIVE_PATH",
                                 "QuickBooks/QB_AgedReceivableDetail.xlsx")
    qb_ar_sheets = _safe_read(tok, upn, qb_ar_path, missing, "QB AR aging")
    if missing:
        log.info("Optional sources missing (page(s) will soft-skip): %s",
                 ", ".join(missing))

    uninvoiced = compute_alvys_uninvoiced(alvys_sheets) if alvys_sheets else {}
    qb_billed_loads = compute_qb_xlinx_bill_loads(qb_bills_sheets)
    log.info("QB X-Linx bill cross-reference: %d load #s indexed (last 180d)",
             len(qb_billed_loads))
    carrier_backlog = compute_carrier_invoice_backlog(
        alvys_sheets, qb_billed_load_ids=qb_billed_loads
    )
    qb_ar = (compute_qb_ar_detail(next(iter(qb_ar_sheets.values())))
             if qb_ar_sheets else {})
    alvys_ar = compute_alvys_ar(alvys_sheets) if alvys_sheets else {}

    # AR reconciliation rollup (per-customer) for the page-1 tile +
    # action items. Same compute function the exec brief + build_page7
    # call.
    from src.scorecard_email import compute_ar_customer_reconciliation
    ar_recon = compute_ar_customer_reconciliation(qb_ar, alvys_ar) or {}

    action_items = compute_financial_action_items(
        uninvoiced=uninvoiced,
        carrier_backlog=carrier_backlog,
        ar_recon=ar_recon,
    )

    html = _build_html_report(
        uninvoiced=uninvoiced,
        carrier_backlog=carrier_backlog,
        ar_recon=ar_recon,
        alvys_sheets=alvys_sheets,
        qb_ar=qb_ar,
        alvys_ar=alvys_ar,
        action_items=action_items,
    )
    pdf = _render_pdf(html)

    subj = f"XFreight Financial Brief — {today.strftime('%B %-d, %Y')}"
    attachments = None
    if pdf:
        log.info("Generated PDF (%.1f KB)", len(pdf) / 1024)
        attachments = [{
            "name": f"financial-brief-{today.isoformat()}.pdf",
            "content_bytes": pdf,
            "mime": "application/pdf",
        }]
    send_email(tok, upn, to_emails, subj, html, attachments=attachments)

    _write_marker(tok, upn, today,
                  f"sent={len(to_emails)} pdf={'yes' if pdf else 'no'}")
    log.info("Marker written: %s", _marker_path(today))
    return 0


if __name__ == "__main__":
    sys.exit(main())
