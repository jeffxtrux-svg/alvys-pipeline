"""Shared helpers for the Financial Brief (financial_email.py).

Extracted from safety_compliance_email.py (git f519023, Jun 15 2026) to
restore these functions after the Jun 16 safety-brief refactor removed them
from that module.  financial_email.py imports from here instead of from
safety_compliance_email so the two briefs can evolve independently.
"""
from __future__ import annotations

import re

import pandas as pd

from src.scorecard_email import (
    FONT_SERIF,
    INK,
    MUTE,
    XFREIGHT_RED,
    _find_col,
    _is_ar_excluded,
    _section,
    _table,
    _to_naive_dt,
    _tr,
)
from src.safety_compliance_email import _today_label

_SEC_CLOSEOUT = "CLOSEOUT"


# ── page-layout primitives ────────────────────────────────────────────────────

def _wrap_page(inner_html: str) -> str:
    return (
        "<table width='100%' cellpadding='0' cellspacing='0' "
        "style='background:#fff;'>" + inner_html + "</table>"
    )


def _page_header(title: str, pg: int, total: int,
                 section: str | None = None) -> str:
    today = _today_label()
    if section:
        eyebrow = (
            f"<div style='font-size:10px;letter-spacing:2px;color:{XFREIGHT_RED};"
            f"font-weight:800;'>XFREIGHT &middot; SAFETY &amp; COMPLIANCE "
            f"&middot; <span style='color:{INK};'>{section}</span></div>"
        )
    else:
        eyebrow = (
            f"<div style='font-size:10px;letter-spacing:2px;color:{XFREIGHT_RED};"
            f"font-weight:800;'>XFREIGHT &middot; SAFETY &amp; COMPLIANCE</div>"
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


# ── vendor/load normalisation ─────────────────────────────────────────────────

def _norm_load_token(s) -> str:
    if s is None:
        return ""
    t = re.sub(r"\D", "", str(s))
    return t.lstrip("0") or t


# ── compute helpers ───────────────────────────────────────────────────────────

def compute_qb_xlinx_bill_loads(qb_bills_sheets: dict | None) -> set[str]:
    """Return set of digit-normalised Alvys load #s that already have a QB
    X-Linx bill (paid or unpaid), used to exclude false-positive carrier
    backlog rows whose Alvys carrier-invoice write-back never landed."""
    out: set[str] = set()
    if not qb_bills_sheets:
        return out
    df = None
    for name, candidate in (qb_bills_sheets or {}).items():
        if candidate is None or getattr(candidate, "empty", True):
            continue
        if "linx" in str(name).lower():
            df = candidate
            break
    if df is None:
        first = next(iter((qb_bills_sheets or {}).values()), None)
        if first is None or getattr(first, "empty", True):
            return out
        co_col = _find_col(first, ["company"])
        df = first[first[co_col].astype(str).str.lower().str.contains("linx", na=False)] \
             if co_col else first
    if df is None or df.empty:
        return out

    free_text_cols: list[str] = []
    for c in df.columns:
        lc = str(c).lower()
        if any(k in lc for k in ("docnumber", "doc_number", "doc number",
                                  "privatenote", "private_note", "private note",
                                  "memo", "description", "line", "reference",
                                  "ref number", "refnumber")):
            free_text_cols.append(c)
    if not free_text_cols:
        return out

    pattern = re.compile(r"\b(\d{6,8})\b")
    for _, r in df.iterrows():
        blob_parts: list[str] = []
        for c in free_text_cols:
            v = r.get(c)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            blob_parts.append(str(v))
        if not blob_parts:
            continue
        for tok in pattern.findall(" ".join(blob_parts)):
            out.add(tok.lstrip("0") or tok)
    return out


def compute_carrier_invoice_backlog(alvys_pipeline_sheets: dict | None,
                                    qb_billed_load_ids: set[str] | None = None,
                                    limit: int = 30) -> dict:
    """X-Linx brokered loads delivered but with no carrier invoice number
    entered into Alvys yet.  Multi-signal AND filter (inv# empty, due-date
    empty, brokerage status unsettled, delivered ≤60d).  Cross-referenced
    against QB X-Linx bills so already-billed loads are excluded even when
    the Alvys write-back never landed."""
    empty = {"count": 0, "total_carrier_rate": 0.0, "oldest_days": None,
             "rows": [], "shown": 0}
    if not alvys_pipeline_sheets:
        return empty
    trips = alvys_pipeline_sheets.get("Trips")
    if trips is None or trips.empty:
        return empty

    office_col  = _find_col(trips, ["office"])
    status_col  = ("Trip Status" if "Trip Status" in trips.columns
                   else _find_col(trips, ["trip status", "status"]))
    inv_col     = _find_col(trips, ["carrier invoice number", "carrier invoice #"])
    due_col     = _find_col(trips, ["carrier invoice due date", "carrier invoice due"])
    brok_col    = _find_col(trips, ["brokerage status"])
    rate_col    = ("Carrier Rate" if "Carrier Rate" in trips.columns
                   else _find_col(trips, ["carrier rate"]))
    if not (status_col and inv_col and rate_col):
        return empty

    sub = trips.copy()
    if office_col:
        sub = sub[sub[office_col].astype(str).str.lower().str.contains("linx", na=False)]

    delivered_statuses = {"delivered", "released", "completed", "invoiced"}
    sub = sub[sub[status_col].astype(str).str.strip().str.lower().isin(delivered_statuses)]

    inv_norm = sub[inv_col].astype(str).str.strip().str.lower()
    sub = sub[inv_norm.isin(["", "nan", "none", "null", "0", "<na>"])]

    if due_col:
        sub = sub[pd.to_datetime(sub[due_col], errors="coerce").isna()]

    if brok_col:
        bs = sub[brok_col].astype(str).str.lower()
        for tok in ("settled", "paid", "closed", "complete"):
            sub = sub[~bs.str.contains(tok, na=False)]
            bs = sub[brok_col].astype(str).str.lower()

    pre_cust_col    = ("Customer" if "Customer" in sub.columns
                       else _find_col(sub, ["customer name"]))
    pre_carrier_col = ("Carrier" if "Carrier" in sub.columns
                       else _find_col(sub, ["carrier"]))
    if pre_cust_col:
        sub = sub[~sub[pre_cust_col].apply(_is_ar_excluded)]
    if pre_carrier_col:
        sub = sub[~sub[pre_carrier_col].apply(_is_ar_excluded)]

    if qb_billed_load_ids:
        pre_load_col = ("Load #" if "Load #" in sub.columns
                        else _find_col(sub, ["load #", "load number"]))
        if pre_load_col:
            sub = sub[~sub[pre_load_col].apply(_norm_load_token).isin(qb_billed_load_ids)]

    if sub.empty:
        return empty

    rate    = pd.to_numeric(sub[rate_col], errors="coerce").fillna(0)
    today   = pd.Timestamp.now().normalize()
    deliv_col = _find_col(sub, ["actual delivery", "scheduled delivery", "delivery date"])
    deliv   = _to_naive_dt(sub[deliv_col]) if deliv_col else pd.Series(pd.NaT, index=sub.index)
    days    = (today - deliv).dt.days

    age_mask = (days.notna() & (days <= 60))
    sub   = sub[age_mask]
    rate  = rate[age_mask]
    deliv = deliv[age_mask]
    days  = days[age_mask]
    if sub.empty:
        return empty

    load_col    = ("Load #" if "Load #" in sub.columns
                   else _find_col(sub, ["load #", "load number"]))
    cust_col    = ("Customer" if "Customer" in sub.columns
                   else _find_col(sub, ["customer"]))
    carrier_col = ("Carrier" if "Carrier" in sub.columns
                   else _find_col(sub, ["carrier"]))

    rows = []
    for idx in sub.index:
        d = days.get(idx)
        rows.append({
            "load":         str(sub.at[idx, load_col]).strip() if load_col else "",
            "customer":     str(sub.at[idx, cust_col]).strip() if cust_col else "",
            "carrier":      str(sub.at[idx, carrier_col]).strip() if carrier_col else "",
            "delivered":    deliv.get(idx).strftime("%m/%d/%Y") if pd.notna(deliv.get(idx)) else "",
            "days":         int(d) if pd.notna(d) else None,
            "carrier_rate": float(rate.get(idx, 0)),
        })
    rows.sort(key=lambda r: ((r["days"] if r["days"] is not None else -1),
                              r["carrier_rate"]), reverse=True)
    valid_days = [r["days"] for r in rows if r["days"] is not None]
    return {
        "count":              len(rows),
        "total_carrier_rate": float(rate.sum()),
        "oldest_days":        max(valid_days) if valid_days else None,
        "rows":               rows[:limit],
        "shown":              min(len(rows), limit),
    }


def _load_carrier_map(alvys_pipeline_sheets: dict | None) -> dict[str, str]:
    """Build {load# (digit-normalised) → carrier name} from the Loads sheet."""
    if not alvys_pipeline_sheets:
        return {}
    loads = alvys_pipeline_sheets.get("Loads")
    if loads is None or loads.empty:
        return {}
    load_col    = ("Load #" if "Load #" in loads.columns
                   else _find_col(loads, ["load #", "load number"]))
    carrier_col = ("Carrier" if "Carrier" in loads.columns
                   else _find_col(loads, ["carrier"]))
    if not (load_col and carrier_col):
        return {}
    out: dict[str, str] = {}
    for idx in loads.index:
        ln = _norm_load_token(loads.at[idx, load_col])
        cr = loads.at[idx, carrier_col]
        if not ln or cr is None or (isinstance(cr, float) and pd.isna(cr)):
            continue
        out[ln] = str(cr).strip()
    return out


# ── render helpers ────────────────────────────────────────────────────────────

def _totals_row(cells: list[str], al: list[str],
                colspan_of: list[int] | None = None) -> str:
    out = ""
    for cc, a in zip(cells, al):
        out += (
            f"<td align='{a}' style='padding:10px 8px;font-size:13px;"
            f"color:{INK};font-weight:800;background:#fafafa;"
            f"border-top:2px solid {INK};'>{cc}</td>"
        )
    return f"<tr>{out}</tr>"


# ── page builder ──────────────────────────────────────────────────────────────

def build_page_invoice_closeout(uninvoiced: dict | None,
                                carrier_backlog: dict | None,
                                alvys_pipeline_sheets: dict | None,
                                pg: int, total: int) -> str:
    """Invoice closeout page: customer-side un-invoiced loads + carrier-side
    brokered trips with no carrier invoice number entered into Alvys."""
    carrier_map = _load_carrier_map(alvys_pipeline_sheets)

    u_rows   = (uninvoiced or {}).get("rows") or []
    u_count  = (uninvoiced or {}).get("count") or 0
    u_total  = (uninvoiced or {}).get("total_revenue") or 0
    u_oldest = (uninvoiced or {}).get("oldest_days")
    u_summary = (
        f"<div style='padding:8px 18px;color:{MUTE};font-size:11px;'>"
        f"{u_count} load(s) &middot; ${u_total:,.0f} revenue not yet invoiced &middot; "
        f"oldest {u_oldest if u_oldest is not None else '&mdash;'}d.</div>"
    )
    if u_rows:
        trs = "".join(
            _tr([str(r.get("load") or "&mdash;"),
                 str(r.get("customer") or "&mdash;"),
                 str(r.get("entity") or "&mdash;"),
                 (carrier_map.get(_norm_load_token(r.get("load"))) or "&mdash;"),
                 str(r.get("delivered") or "&mdash;"),
                 (f"{r['days']}d" if r.get("days") is not None else "&mdash;"),
                 f"${(r.get('revenue') or 0):,.0f}"],
                ["left", "left", "left", "left", "left", "right", "right"],
                [None, None, None, None, None,
                 ("bad" if (r.get("days") or 0) > 7 else "warn"),
                 None])
            for r in u_rows
        )
        shown_total = sum((r.get("revenue") or 0) for r in u_rows)
        trs += _totals_row(
            [f"TOTAL ({len(u_rows)} shown)", "", "", "", "", "",
             f"${shown_total:,.0f}"],
            ["left", "left", "left", "left", "left", "right", "right"],
        )
        u_table = _table(
            ["Load #", "Customer", "Entity", "Carrier", "Delivered", "Days", "Revenue"],
            ["left", "left", "left", "left", "left", "right", "right"],
            trs,
        )
    else:
        u_table = (
            f"<div style='padding:12px 18px;color:{MUTE};font-size:12px;'>"
            "All delivered loads have been invoiced.</div>"
        )

    c_rows   = (carrier_backlog or {}).get("rows") or []
    c_count  = (carrier_backlog or {}).get("count") or 0
    c_total  = (carrier_backlog or {}).get("total_carrier_rate") or 0
    c_oldest = (carrier_backlog or {}).get("oldest_days")
    c_summary = (
        f"<div style='padding:8px 18px;color:{MUTE};font-size:11px;'>"
        f"{c_count} brokered trip(s) &middot; ~${c_total:,.0f} carrier rate "
        f"not yet entered into Alvys &middot; oldest "
        f"{c_oldest if c_oldest is not None else '&mdash;'}d."
        f"<br/><i>Scope: delivered in the last 60 days &middot; Alvys "
        f"Carrier Invoice Number, Due Date, and Brokerage Status all "
        f"empty/unsettled &middot; cross-referenced against QB X-Linx "
        f"Bills (paid + unpaid, last 180d) so anything already billed in "
        f"QB is excluded even if the Alvys carrier-invoice-number "
        f"write-back never landed.</i>"
        f"</div>"
    )
    if c_rows:
        trs = "".join(
            _tr([str(r.get("load") or "&mdash;"),
                 str(r.get("customer") or "&mdash;"),
                 str(r.get("carrier") or "&mdash;"),
                 str(r.get("delivered") or "&mdash;"),
                 (f"{r['days']}d" if r.get("days") is not None else "&mdash;"),
                 f"${(r.get('carrier_rate') or 0):,.0f}"],
                ["left", "left", "left", "left", "right", "right"],
                [None, None, None, None,
                 ("bad" if (r.get("days") or 0) > 7 else "warn"),
                 None])
            for r in c_rows
        )
        shown_c_total = sum((r.get("carrier_rate") or 0) for r in c_rows)
        trs += _totals_row(
            [f"TOTAL ({len(c_rows)} shown)", "", "", "", "",
             f"${shown_c_total:,.0f}"],
            ["left", "left", "left", "left", "right", "right"],
        )
        c_table = _table(
            ["Load #", "Customer", "Carrier", "Delivered", "Days", "Carrier rate"],
            ["left", "left", "left", "left", "right", "right"],
            trs,
        )
    else:
        c_table = (
            f"<div style='padding:12px 18px;color:{MUTE};font-size:12px;'>"
            "No outstanding carrier invoices to enter.</div>"
        )

    body = (
        f"<tr><td style='padding:18px 18px 0;'>"
        f"{_section('Customer side &mdash; delivered loads not yet invoiced')}"
        f"{u_summary}"
        f"{u_table}"
        f"{_section('Carrier side &mdash; brokered trips with no carrier invoice number entered')}"
        f"{c_summary}"
        f"{c_table}"
        f"</td></tr>"
    )
    return _page_header("Invoice closeout", pg, total, section=_SEC_CLOSEOUT) + _wrap_page(body)
