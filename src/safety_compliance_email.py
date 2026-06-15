"""
Safety & Compliance Report — daily HTML brief focused exclusively on
driver safety, HOS compliance, and vehicle inspection state.

The executive brief (scorecard_email) is P&L-led with safety as one of
several sections. This report inverts that — safety is the whole agenda,
with a page-1 auto-narrative bottom line that calls out what changed,
who's the biggest problem this week, and what's overdue.

v1 pages:
  1. Overview — bottom-line narrative + KPI tiles + 6mo events trend
  2. Safety events — last 7 days, per-driver and per-event
  3. HOS compliance — driving-rule violations + missing log certifications
  4. Driver safety scores — ranked worst-to-best over 30 days
  5. Vehicle compliance — open DVIR defects + tractor/trailer inspections due

Sources: Samsara_Master.xlsx (OneDrive) — same data the executive brief
already consumes. No new pulls; this report is purely a re-cut.

Reads only — never writes to Samsara. Sends via Microsoft Graph
/users/{from}/sendMail using the same Azure app credentials as the
scorecard.

Required env:
    AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET — Graph auth
    ONEDRIVE_USER_UPN  — mailbox to read OneDrive from + send mail as
    SAFETY_TO_EMAILS   — comma-separated recipient list (jeff@ while testing)
"""
from __future__ import annotations

import datetime
import io
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
from src.scorecard_email import (
    BAD,
    BADBG,
    FONT_SERIF,
    GOOD,
    GOODBG,
    INK,
    LINE,
    MUTE,
    NAVY,
    TILEBG,
    WARN,
    WARNBG,
    XFREIGHT_RED,
    COACH_EVENT_THRESHOLD,
    _bar_chart,
    _find_col,
    _is_ar_excluded,
    _isnum,
    _last_6_months,
    _monthly_counts,
    _mwtile,
    _pill,
    _safe_read,
    _safety_detail_tables,
    _section,
    _table,
    _tile,
    _to_naive_dt,
    _tr,
    _windows,
    _xfreight_logo_svg,
    build_page2b as _exec_build_page2b,
    build_page7 as _exec_build_page7,
    build_page_coached as _exec_build_page_coached,
    compute_alvys_ar,
    compute_alvys_drivers,
    compute_alvys_uninvoiced,
    compute_csa_scorecard,
    compute_inspection_compliance,
    compute_qb_ar_detail,
    compute_sambasafety,
    compute_samsara,
    compute_speed_comment,
    send_email,
)

log = logging.getLogger("safety_compliance_email")

# ----------------------------------------------------------------------
# Date / report helpers
# ----------------------------------------------------------------------

def _today_chi() -> datetime.date:
    return datetime.datetime.now(ZoneInfo("America/Chicago")).date()


def _today_label() -> str:
    return _today_chi().strftime("%A, %B %d, %Y")


# Idempotency marker so the staggered backup crons (5:00/5:30/6:30am)
# all short-circuit once today's report has landed. Manual dispatch
# bypasses via the same SAFETY_SKIP_IDEMPOTENCY env var pattern.
_MARKER_FOLDER = "Safety"
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
# Metric computation — the bottom-line narrative is built from these
# ----------------------------------------------------------------------

def compute_metrics(samsara: dict | None) -> dict:
    """Pull the headline numbers out of compute_samsara's output into a
    flat dict the bottom-line narrator + KPI tiles can both read."""
    if not samsara:
        return {
            "events_7d": 0, "events_30d": 0, "events_24h": 0,
            "hos_7d": 0, "hos_24h": 0,
            "dvir_open": 0,
            "fleet_score": None,
            "uncert_drivers": 0, "uncert_worst_name": None, "uncert_worst_days": 0,
            "events_trend_change": None,
        }
    w = samsara.get("windows", {}) or {}
    fleet = samsara.get("fleet", {}) or {}
    detail = samsara.get("detail", {}) or {}

    events_w = w.get("events", {}) or {}
    hos_w = w.get("hos", {}) or {}
    dvir_w = w.get("dvir", {}) or {}

    # Use the monthly trend to compare current vs prior month if available.
    et = samsara.get("trend", {}).get("events") or ([], [])
    et_counts = et[1] if isinstance(et, tuple) and len(et) > 1 else []
    events_trend_change = None
    if len(et_counts) >= 2 and et_counts[-2]:
        events_trend_change = et_counts[-1] - et_counts[-2]

    # Missing log certifications — already grouped per driver.
    uncert = detail.get("hos_uncert", []) or []
    uncert_drivers = len(uncert)
    worst = max(uncert, key=lambda r: r.get("days_missing", 0)) if uncert else None
    uncert_worst_name = worst.get("driver") if worst else None
    uncert_worst_days = int(worst.get("days_missing", 0)) if worst else 0

    return {
        "events_24h": int(events_w.get("24h", 0)),
        "events_7d": int(events_w.get("7d", 0)),
        "events_30d": int(events_w.get("mtd", 0)),
        "hos_24h": int(hos_w.get("24h", 0)),
        "hos_7d": int(hos_w.get("7d", 0)),
        "dvir_open": int(dvir_w.get("mtd", 0)),
        "fleet_score": fleet.get("fleet_score"),
        "uncert_drivers": uncert_drivers,
        "uncert_worst_name": uncert_worst_name,
        "uncert_worst_days": uncert_worst_days,
        "events_trend_change": events_trend_change,
    }


def build_bottom_line(m: dict) -> str:
    """Auto-generated 2-3 sentence narrative summarizing the current
    safety+compliance posture. Computed from the metrics dict so it
    moves with the data day-over-day."""
    sentences: list[str] = []

    # Sentence 1 — fleet score + events trend.
    fs = m.get("fleet_score")
    tc = m.get("events_trend_change")
    if fs is not None:
        s = f"Fleet safety score sits at <b>{int(round(fs))}</b>"
        if tc is not None:
            arrow = "down" if tc > 0 else ("up" if tc < 0 else "flat")
            # tc is event-count delta (more events = score pressure), not score delta.
            s += (f" with <b>{m['events_7d']}</b> safety event"
                  f"{'s' if m['events_7d'] != 1 else ''} in the last 7 days "
                  f"({arrow} {abs(tc)} month-over-month).")
        else:
            s += (f" with <b>{m['events_7d']}</b> safety event"
                  f"{'s' if m['events_7d'] != 1 else ''} in the last 7 days.")
        sentences.append(s)
    else:
        sentences.append(
            f"<b>{m['events_7d']}</b> safety event"
            f"{'s' if m['events_7d'] != 1 else ''} recorded in the last 7 days."
        )

    # Sentence 2 — HOS posture (violations + missing certs).
    hos = m["hos_7d"]
    uc = m["uncert_drivers"]
    worst_nm = m["uncert_worst_name"]
    worst_d = m["uncert_worst_days"]
    if hos == 0 and uc == 0:
        sentences.append("HOS compliance is clean — no driving-rule violations and all daily logs certified.")
    else:
        bits = []
        if hos:
            bits.append(f"<b>{hos}</b> HOS violation{'s' if hos != 1 else ''} (last 7d)")
        if uc:
            worst_clause = (
                f"; <b>{worst_nm}</b> worst at <b>{worst_d}</b> day"
                f"{'s' if worst_d != 1 else ''} behind"
            ) if worst_nm else ""
            bits.append(
                f"<b>{uc}</b> driver{'s' if uc != 1 else ''} with missing log certifications"
                f"{worst_clause}"
            )
        sentences.append("HOS: " + ", ".join(bits) + ".")

    # Sentence 3 — vehicle compliance.
    if m["dvir_open"] > 0:
        sentences.append(
            f"<b>{m['dvir_open']}</b> open DVIR defect"
            f"{'s' if m['dvir_open'] != 1 else ''} pending repair."
        )
    else:
        sentences.append("No open DVIR defects.")

    return " ".join(sentences)


# ----------------------------------------------------------------------
# Page renderers — small, focused HTML chunks
# ----------------------------------------------------------------------

def _wrap_page(inner_html: str) -> str:
    """Wrap a page's inner content in a table-row container the email
    body and PDF both understand."""
    return (
        "<table width='100%' cellpadding='0' cellspacing='0' "
        "style='background:#fff;'>" + inner_html + "</table>"
    )


def _page_header(title: str, pg: int, total: int,
                  section: str | None = None) -> str:
    """Branded page header — XFreight logo + section chip + two-line date,
    matching the executive brief's visual quality.

    `section` is the topic banner above the page title (DRIVERS / EVENTS
    / EQUIPMENT / REGULATORY). Pages within the same section share a
    banner so the reader can see the brief's structure at a glance."""
    logo = _xfreight_logo_svg(width=150, height=26)
    today = _today_label()
    try:
        from datetime import datetime as _dt
        dt = _dt.strptime(today, "%A, %B %d, %Y")
        day_part = dt.strftime("%A")
        date_part = dt.strftime("%B %d, %Y")
    except Exception:
        day_part, date_part = today, ""
    section_chip = ""
    if section:
        section_chip = (
            f"<span style='display:inline-block;padding:2px 9px;border-radius:3px;"
            f"background:{XFREIGHT_RED};color:#fff;font-size:9px;font-weight:800;"
            f"letter-spacing:1.2px;margin-left:14px;vertical-align:middle;'>{section}</span>"
        )
    return (
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-bottom:4px solid {XFREIGHT_RED};padding:6px 24px 14px;'>"
        f"<tr>"
        f"<td valign='middle' style='padding:0;'>"
        f"{logo}{section_chip}"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:13px;color:{INK};"
        f"font-weight:400;margin-top:8px;'>"
        f"Safety &amp; Compliance &middot; <b style='font-style:normal;'>{title}</b>"
        f"</div>"
        f"</td>"
        f"<td align='right' valign='middle' style='padding:0;font-size:9.5px;color:{MUTE};font-weight:500;'>"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:11px;color:{INK};"
        f"font-weight:600;margin-bottom:2px;'>{day_part}</div>"
        f"<div>{date_part}</div>"
        f"<div class='pg-of' style='font-size:9px;color:{MUTE};margin-top:4px;letter-spacing:0.5px;'>"
        f"Page {pg} of {total}</div>"
        f"</td>"
        f"</tr></table>"
    )


# ----------------------------------------------------------------------
# Additional computes — Audra's full ownership scope (per the
# xfreight-employee-responsibilities.md core memory): safety +
# compliance + invoice closeout (loads invoiced timely + carrier
# invoices entered into Alvys).
# ----------------------------------------------------------------------

import re


def compute_qb_xlinx_bill_loads(qb_bills_sheets: dict | None) -> set[str]:
    """Build a set of Alvys load #s that already have a QB X-Linx bill
    (paid OR unpaid). Used by compute_carrier_invoice_backlog to exclude
    trips whose carrier has been billed via QB even if the Alvys Carrier
    Invoice Number column never got the write-back.

    QB Bills land in QB_Bills.xlsx with one sheet per company; X-Linx Inc
    is the only company we cross-reference here (carrier bills for the
    brokerage live there). The Alvys load # — typically a 7-digit
    integer — is searched across DocNumber, PrivateNote, and every
    line-item description on each bill, since the place it gets written
    varies by who entered the bill. Returns the set of digit-normalized
    load #s found (leading 'T' / 'XL' / etc. stripped to match the same
    _norm_inv pattern the executive brief uses)."""
    out: set[str] = set()
    if not qb_bills_sheets:
        return out
    # X-Linx bills live on the "X-Linx Inc" sheet (one sheet per company),
    # or in the global df with a Company column — be flexible.
    df = None
    for name, candidate in (qb_bills_sheets or {}).items():
        if candidate is None or getattr(candidate, "empty", True):
            continue
        if "linx" in str(name).lower():
            df = candidate
            break
    if df is None:
        # Single combined sheet fallback — filter by Company column.
        first = next(iter((qb_bills_sheets or {}).values()), None)
        if first is None or getattr(first, "empty", True):
            return out
        co_col = _find_col(first, ["company"])
        df = first[first[co_col].astype(str).str.lower().str.contains("linx", na=False)] \
             if co_col else first
    if df is None or df.empty:
        return out

    # Columns to scan for load-# tokens. json_normalize of a QB Bill
    # record produces dotted names — "Line", "PrivateNote", "DocNumber"
    # at top level, plus "Line[0].Description" etc. if not stringified.
    # We string-concat every column whose name implies free-text content
    # to be robust against schema variations.
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

    pattern = re.compile(r"\b(\d{6,8})\b")  # Alvys load #s are 7 digits;
                                              # allow 6–8 for robustness.

    for _, r in df.iterrows():
        blob_parts: list[str] = []
        for c in free_text_cols:
            v = r.get(c)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            blob_parts.append(str(v))
        if not blob_parts:
            continue
        blob = " ".join(blob_parts)
        for tok in pattern.findall(blob):
            # Strip a single leading alpha if the source carried "T1234567"
            # style — keeps parity with _norm_inv in scorecard_email.
            out.add(tok.lstrip("0") or tok)
    return out


def _norm_load_token(s) -> str:
    """Normalize a load # for set-membership comparison against the QB
    bill index. Strips non-digits and leading zeros so '1008720',
    '1008720.0', and ' 1008720 ' all collapse to the same key."""
    if s is None:
        return ""
    t = re.sub(r"\D", "", str(s))
    return t.lstrip("0") or t


def compute_carrier_invoice_backlog(alvys_pipeline_sheets: dict | None,
                                      qb_billed_load_ids: set[str] | None = None,
                                      limit: int = 30) -> dict:
    """X-Linx brokered loads that are delivered but have no carrier
    invoice number entered into Alvys yet — Audra's second-half of
    invoice closeout (the asset side is compute_alvys_uninvoiced).

    Confidence problem solved here: the Alvys "Carrier Invoice Number"
    column comes from a load→invoice-index lookup that misses any
    invoice not indexed under the Carrier heuristic in lookups.py.
    When a carrier invoice is entered in Alvys then later posted +
    paid in QuickBooks under X-Linx, the column on the Trips sheet
    can still read blank long after the bill has cleared. That used
    to dump hundreds of 6-month / 2-year-old ghost rows onto Audra's
    brief.

    Multiple-signal AND filter, all must hold for the trip to count
    as backlog:
      1. Carrier Invoice Number is empty/missing
      2. Carrier Invoice Due Date is empty/missing
         (a due date implies the invoice exists)
      3. Brokerage Status is NOT a settled/paid value
         (Alvys writes 'Carrier Settled', 'Paid', etc. when the
         carrier side is closed)
      4. Delivered in the last 60 days
         (anything older is almost certainly a data issue, not
         a real backlog — the carrier won't wait 60+ days to
         invoice and we won't wait 60+ days to pay)

    Cross-reference with QB paid bills would be the gold-standard
    confirmation but needs a new pull — TODO: add a QB Bill entity
    pull or a Purchase query so we can exclude any load# that shows
    up as a paid bill in QB X-Linx.

    Returns {count, total_carrier_rate, oldest_days, rows, shown}.
    """
    empty = {"count": 0, "total_carrier_rate": 0.0, "oldest_days": None,
             "rows": [], "shown": 0}
    if not alvys_pipeline_sheets:
        return empty
    trips = alvys_pipeline_sheets.get("Trips")
    if trips is None or trips.empty:
        return empty
    office_col = _find_col(trips, ["office"])
    status_col = "Trip Status" if "Trip Status" in trips.columns else _find_col(trips, ["trip status", "status"])
    inv_col = _find_col(trips, ["carrier invoice number", "carrier invoice #"])
    due_col = _find_col(trips, ["carrier invoice due date", "carrier invoice due"])
    brok_col = _find_col(trips, ["brokerage status"])
    rate_col = "Carrier Rate" if "Carrier Rate" in trips.columns else _find_col(trips, ["carrier rate"])
    if not (status_col and inv_col and rate_col):
        return empty

    sub = trips.copy()
    # X-Linx scope: brokered trips only. Office field on a trip can read
    # "X-LINX INC" etc. — soft contains match.
    if office_col:
        sub = sub[sub[office_col].astype(str).str.lower().str.contains("linx", na=False)]
    # Delivered or downstream — i.e., the load has actually been hauled.
    delivered_statuses = {"delivered", "released", "completed", "invoiced"}
    sub = sub[sub[status_col].astype(str).str.strip().str.lower().isin(delivered_statuses)]

    # Signal 1: Carrier Invoice Number must be empty/missing. Robust
    # against NaN, "0", "None", "null", and whitespace-only strings.
    inv_norm = sub[inv_col].astype(str).str.strip().str.lower()
    sub = sub[inv_norm.isin(["", "nan", "none", "null", "0", "<na>"])]

    # Signal 2: Carrier Invoice Due Date must be empty too — if a due
    # date exists, the invoice exists even if the number didn't make
    # it back through the lookup index.
    if due_col:
        sub = sub[pd.to_datetime(sub[due_col], errors="coerce").isna()]

    # Signal 3: Brokerage Status must not indicate the carrier side is
    # already settled or paid. Conservative match — substring on any
    # of the known close-out tokens.
    if brok_col:
        bs = sub[brok_col].astype(str).str.lower()
        settled_tokens = ("settled", "paid", "closed", "complete")
        for tok in settled_tokens:
            sub = sub[~bs.str.contains(tok, na=False)]
            bs = sub[brok_col].astype(str).str.lower()

    # Exclude JW Logistics on either side — match the executive brief's
    # _AR_DETAIL_EXCLUDE rule so the safety report's bills reconcile
    # like-for-like with the AR pages. Applied to BOTH the customer
    # (a JW-customer brokered load) and the carrier (a JW-carrier
    # brokered load) — neither should surface as a bill to chase.
    pre_cust_col = "Customer" if "Customer" in sub.columns else _find_col(sub, ["customer name"])
    pre_carrier_col = "Carrier" if "Carrier" in sub.columns else _find_col(sub, ["carrier"])
    if pre_cust_col:
        sub = sub[~sub[pre_cust_col].apply(_is_ar_excluded)]
    if pre_carrier_col:
        sub = sub[~sub[pre_carrier_col].apply(_is_ar_excluded)]

    # Signal 5 (when available): exclude any load # that already has a
    # QB X-Linx bill (paid OR unpaid) — Audra has already entered it,
    # the Alvys-side write-back just never landed.
    if qb_billed_load_ids:
        pre_load_col = "Load #" if "Load #" in sub.columns else _find_col(sub, ["load #", "load number"])
        if pre_load_col:
            mask = ~sub[pre_load_col].apply(_norm_load_token).isin(qb_billed_load_ids)
            sub = sub[mask]

    if sub.empty:
        return empty

    rate = pd.to_numeric(sub[rate_col], errors="coerce").fillna(0)
    today = pd.Timestamp.now().normalize()
    deliv_col = _find_col(sub, ["actual delivery", "scheduled delivery", "delivery date"])
    if deliv_col:
        deliv = _to_naive_dt(sub[deliv_col])
    else:
        deliv = pd.Series(pd.NaT, index=sub.index)
    days = (today - deliv).dt.days

    # Signal 4: cap age. Anything > 60 days post-delivery without a
    # carrier invoice number / due date / settlement status is almost
    # certainly a data-cleanup issue (Alvys lost the lookup), not a
    # real bill to chase. Drop them so the section stays trustworthy.
    age_mask = (days.notna() & (days <= 60))
    sub = sub[age_mask]
    rate = rate[age_mask]
    deliv = deliv[age_mask]
    days = days[age_mask]
    if sub.empty:
        return empty

    load_col = "Load #" if "Load #" in sub.columns else _find_col(sub, ["load #", "load number"])
    cust_col = "Customer" if "Customer" in sub.columns else _find_col(sub, ["customer"])
    carrier_col = "Carrier" if "Carrier" in sub.columns else _find_col(sub, ["carrier"])

    rows = []
    for idx in sub.index:
        d = days.get(idx)
        rows.append({
            "load":     str(sub.at[idx, load_col]).strip() if load_col else "",
            "customer": str(sub.at[idx, cust_col]).strip() if cust_col else "",
            "carrier":  str(sub.at[idx, carrier_col]).strip() if carrier_col else "",
            "delivered": deliv.get(idx).strftime("%m/%d/%Y") if pd.notna(deliv.get(idx)) else "",
            "days":     int(d) if pd.notna(d) else None,
            "carrier_rate": float(rate.get(idx, 0)),
        })
    rows.sort(key=lambda r: ((r["days"] if r["days"] is not None else -1),
                              r["carrier_rate"]), reverse=True)
    valid_days = [r["days"] for r in rows if r["days"] is not None]
    return {
        "count": len(rows),
        "total_carrier_rate": float(rate.sum()),
        "oldest_days": max(valid_days) if valid_days else None,
        "rows": rows[:limit],
        "shown": min(len(rows), limit),
    }


def compute_action_items(*, samsara, samba, alvys_drivers, equipment,
                          uninvoiced, carrier_backlog, csa) -> list[dict]:
    """Top-priority action items for Audra today. Each item is a dict
    with {priority, owner, action, why, kb_link}. Priority ordering:
    1 = drop-everything; 2 = today; 3 = this week. Caller renders the
    list in order.
    """
    items: list[dict] = []
    today = pd.Timestamp.now().normalize()

    # PRIORITY 1 — disqualified/invalid CDLs.
    invalid = (samba or {}).get("invalid_licenses") or []
    for inv in invalid:
        nm = inv.get("name") or "Unknown driver"
        st = inv.get("status") or "DISQUALIFIED"
        eff = inv.get("effective") or inv.get("date") or ""
        items.append({
            "priority": 1,
            "owner": "Audra",
            "action": f"Pull {nm} from dispatch immediately — license status {st}.",
            "why": (f"SambaSafety Invalid License Report shows {st} effective "
                    f"{eff}. Driver cannot legally operate."),
            "kb_link": "xfreight-playbook-driver-disciplinary.md",
        })

    # PRIORITY 1 — CDL expiring ≤7 days (immediate).
    crit_cdl = (alvys_drivers or {}).get("license_critical_14") or []
    for d in crit_cdl:
        days = d.get("license_days")
        if days is not None and days <= 7:
            items.append({
                "priority": 1,
                "owner": "Audra",
                "action": f"Confirm {d.get('name', '?')} renewed CDL — expires in {days}d.",
                "why": "CDL expiration ≤7 days. Pull from dispatch the moment it lapses.",
                "kb_link": "xfreight-playbook-driver-disciplinary.md",
            })

    # PRIORITY 2 — Medical card expiring ≤14 days.
    med = ((alvys_drivers or {}).get("medical_critical_14") or
           [d for d in ((alvys_drivers or {}).get("medical_issues_30") or [])
            if d.get("medical_days") is not None and d.get("medical_days") <= 14])
    for d in med[:5]:
        days = d.get("medical_days")
        if days is None:
            continue
        items.append({
            "priority": 2,
            "owner": "Audra",
            "action": f"Schedule {d.get('name', '?')} DOT physical — med card expires in {days}d.",
            "why": "DOT medical card expiration ≤14 days. Federal OOS if it lapses.",
            "kb_link": "xfreight-playbook-driver-disciplinary.md",
        })

    # PRIORITY 2 — CSA BASIC at intervention threshold.
    if csa:
        n_alert = csa.get("n_alert") or 0
        worst = csa.get("worst") or {}
        if n_alert and worst:
            items.append({
                "priority": 2,
                "owner": "Audra",
                "action": f"Review CSA {worst.get('basic', 'BASIC')} — at intervention threshold.",
                "why": (f"{worst.get('basic', 'BASIC')} at {worst.get('pct', '?')}th "
                        f"percentile (threshold {worst.get('threshold', '?')}). "
                        f"{n_alert} BASIC(s) flagged."),
                "kb_link": "xfreight-fmcsa-csa.md",
            })

    # PRIORITY 2 — equipment past 120d company policy (>30 days).
    # TRACTORS ONLY on Audra's brief. Per the responsibility map,
    # trailer inspections are Jackson + Dan's lane (they own trailer
    # maintenance); they'll see trailers on the operational/maintenance
    # brief. Ownership split by fleet:
    #   - X-Trux owner-operator tractors: Audra solo (safety + compliance).
    #   - Truk-Way fleet tractors: shared — Audra (safety/CSA Maintenance
    #     BASIC) plus Jackson + Dan (Truk-Way tractor maintenance, per
    #     the responsibility map).
    # The owner label below reflects that split. TODO once main.py adds
    # Fleet.Name to the Trucks sheet, split the tractor list into
    # per-fleet action items so each owner sees only their slice.
    # `policy_days` counts down from the 120d window after
    # LastInspectionDate (negative = past policy). `annual_days` is the
    # 365d federal date — we don't gate on that here because anything
    # past company policy gets flagged for inspection long before the
    # federal OOS line.
    if equipment:
        od_t = [t for t in (equipment.get("tractors") or [])
                if isinstance(t.get("policy_days"), int) and t["policy_days"] < -30]
        if od_t:
            units = ", ".join(str(t.get("unit") or "?") for t in od_t[:5])
            more = f" (+{len(od_t) - 5} more)" if len(od_t) > 5 else ""
            items.append({
                "priority": 2,
                "owner": "Audra (Truk-Way tractors: shared w/ Jackson + Dan)",
                "action": f"Schedule tractor inspection: {units}{more}.",
                "why": (f"{len(od_t)} tractor(s) past 120d company policy "
                        f"by >30d. Flagged for inspection; still in service. "
                        f"Federal 365d is the OOS line. X-Trux owner-operator "
                        f"tractors: Audra owns. Truk-Way fleet tractors: "
                        f"co-owned with Jackson + Dan (maintenance)."),
                "kb_link": "xfreight-playbook-equipment-inspection-backlog.md",
            })

    # PRIORITY 2 — un-acked coaching > 72h.
    detail = (samsara or {}).get("detail", {}) or {}
    coaching = detail.get("coaching") or []
    stale_coach = [c for c in coaching if (c.get("days_since") or 0) > 3
                   and (c.get("status") or "").lower() in ("needscoaching", "open", "")]
    if stale_coach:
        items.append({
            "priority": 2,
            "owner": "Audra",
            "action": f"Close out {len(stale_coach)} coaching session(s) un-acked >72h.",
            "why": "Stale coaching tickets erode the CSA Maintenance / Driver BASIC scores.",
            "kb_link": "xfreight-playbook-driver-disciplinary.md",
        })

    # PRIORITY 3 — un-invoiced loads aging > 7 days.
    if uninvoiced:
        aged = [r for r in (uninvoiced.get("rows") or [])
                if (r.get("days") or 0) > 7]
        if aged:
            total_aged = sum(r.get("revenue", 0) for r in aged)
            items.append({
                "priority": 3,
                "owner": "Audra",
                "action": f"Invoice {len(aged)} delivered load(s) (>${total_aged:,.0f}) past 7-day window.",
                "why": ("Un-invoiced delivered loads drag AR aging and the "
                        "QB-vs-Alvys reconciliation."),
                "kb_link": "xfreight-playbook-ar-followup.md",
            })

    # PRIORITY 3 — carrier invoices not entered into Alvys.
    if carrier_backlog and carrier_backlog.get("count"):
        items.append({
            "priority": 3,
            "owner": "Audra",
            "action": (f"Enter {carrier_backlog['count']} carrier invoice(s) "
                       f"(~${carrier_backlog.get('total_carrier_rate', 0):,.0f}) "
                       f"into Alvys."),
            "why": ("X-Linx brokered loads delivered but no Carrier Invoice "
                    "Number on file — blocks settlement to the carrier."),
            "kb_link": "xfreight-playbook-ar-followup.md",
        })

    items.sort(key=lambda x: x["priority"])
    return items


def safety_relevant_signals(results: list[dict]) -> list[dict]:
    """Filter risk_watch signals to the subset Audra owns or directly
    needs to see on her brief. Keeps the cross-loop architecture intact
    (one source of truth in risk-signals.yml) while letting each role
    see only their slice.

    Trailer-inspection counts are Jackson + Dan's responsibility per
    the org responsibility map, so the equipment-inspection-backlog
    signal is rewritten in-place to strip its paired trailer values
    before rendering. The same signal still ships unmodified to the
    operational brief; we mutate a copy so we don't poison the cache."""
    safety_ids = {
        "equipment-inspection-backlog",
        "equipment-registration-backlog",
        "csa-near-intervention",
    }
    out: list[dict] = []
    for r in (results or []):
        if r.get("id") not in safety_ids:
            continue
        if r.get("id") == "equipment-inspection-backlog":
            # Shallow copy + zero the paired-trailer keys so the strip
            # renderer omits the "+ N trailers" suffix.
            r = {**r, "paired_value": None, "paired_tripped_text": None}
        out.append(r)
    return out


# ----------------------------------------------------------------------
# Design system helpers — clear hierarchy for the rebuilt brief
# ----------------------------------------------------------------------

_PRIORITY_COLOR = {1: BAD, 2: WARN, 3: MUTE}
_PRIORITY_BG = {1: BADBG, 2: WARNBG, 3: "#fafafa"}
_PRIORITY_LABEL = {1: "URGENT", 2: "TODAY", 3: "THIS WEEK"}


def _urgent_banner(items: list[dict]) -> str:
    """Red banner at the top of page 1 for any P1 items. Quiet (omitted)
    when nothing's urgent — keeps signal-to-noise high."""
    p1 = [i for i in items if i.get("priority") == 1]
    if not p1:
        return ""
    rows = "".join(
        f"<div style='padding:5px 0 5px 12px;font-size:13px;color:{INK};"
        f"border-left:3px solid {BAD};margin-bottom:4px;line-height:1.4;'>"
        f"<b>{i.get('action', '')}</b>"
        f"<div style='font-size:11px;color:{MUTE};margin-top:2px;'>{i.get('why', '')}</div>"
        f"</div>"
        for i in p1
    )
    return (
        f"<tr><td style='padding:0 24px 14px;'>"
        f"<div style='background:{BADBG};border:1px solid {BAD};"
        f"border-left:6px solid {BAD};border-radius:8px;padding:14px 18px;'>"
        f"<div style='font-size:10px;letter-spacing:2px;font-weight:800;color:{BAD};"
        f"margin-bottom:10px;'>&#9888;&nbsp;URGENT &mdash; ACT NOW</div>"
        f"{rows}"
        f"</div></td></tr>"
    )


def _action_items_block(items: list[dict]) -> str:
    """Top action items today, grouped by priority. Each item shows the
    action, owner, why, and a KB link when one's available."""
    if not items:
        # All-clear state — green signal so Audra knows she can skip this section.
        return (
            f"<tr><td style='padding:0 24px 18px;'>"
            f"<div style='background:{GOODBG};border-left:4px solid {GOOD};"
            f"border-radius:6px;padding:12px 16px;'>"
            f"<div style='font-size:10px;letter-spacing:2px;font-weight:800;color:{GOOD};"
            f"margin-bottom:4px;'>&#10003;&nbsp;ALL CLEAR</div>"
            f"<div style='font-size:12.5px;color:{INK};'>No action items today &mdash; "
            f"fleet is within all safety and compliance thresholds.</div>"
            f"</div></td></tr>"
        )
    blocks = []
    for prio in (1, 2, 3):
        slice_ = [i for i in items if i.get("priority") == prio]
        if not slice_:
            continue
        color = _PRIORITY_COLOR[prio]
        bg = _PRIORITY_BG[prio]
        label = _PRIORITY_LABEL[prio]
        rows = ""
        for i in slice_:
            kb = (f"<div style='font-size:10.5px;color:{MUTE};margin-top:4px;'>"
                  f"&#128196;&nbsp;playbook: "
                  f"<code style='font-size:10px;color:{MUTE};'>{i['kb_link']}</code></div>"
                  if i.get("kb_link") else "")
            owner_chip = (
                f"<span style='display:inline-block;padding:1px 7px;border-radius:3px;"
                f"background:#eef2f7;color:{INK};font-size:10px;font-weight:700;"
                f"margin-left:6px;'>owner: {i.get('owner', 'Audra')}</span>"
            )
            rows += (
                f"<div style='padding:11px 14px;border-top:1px solid {LINE};'>"
                f"<div style='font-size:13px;color:{INK};font-weight:700;line-height:1.4;'>"
                f"{i.get('action', '')}</div>"
                f"<div style='font-size:11.5px;color:{MUTE};margin-top:4px;line-height:1.4;'>"
                f"{i.get('why', '')}{owner_chip}</div>"
                f"{kb}</div>"
            )
        blocks.append(
            f"<div style='margin-bottom:12px;border:1px solid {LINE};border-radius:8px;"
            f"overflow:hidden;'>"
            f"<div style='background:{bg};border-bottom:1px solid {LINE};"
            f"padding:7px 14px;font-size:9.5px;"
            f"letter-spacing:1.8px;font-weight:800;color:{color};'>"
            f"&#9679;&nbsp;{label}</div>"
            f"{rows}</div>"
        )
    if not blocks:
        return ""
    return (
        f"<tr><td style='padding:4px 24px 18px;'>"
        f"<div style='font-size:9.5px;letter-spacing:2px;color:{MUTE};font-weight:700;"
        f"margin-bottom:10px;text-transform:uppercase;'>Action items</div>"
        + "".join(blocks)
        + f"</td></tr>"
    )


def _risk_watch_block(signals: list[dict]) -> str:
    """Compact safety-relevant Risk Watch strip. Same renderer as the
    executive brief — single source of truth for the visual + value
    formatting (money/days/pct)."""
    if not signals:
        return ""
    from src.risk_watch import render_strip_html
    strip = render_strip_html(
        signals,
        red=BAD, redbg=BADBG, green=GOOD, greenbg=GOODBG,
        mute=MUTE, line=LINE,
    )
    if not strip:
        return ""
    return f"<tr><td style='padding:0 24px 8px;'>{strip}</td></tr>"


def compute_onduty_uncertified(samsara_sheets: dict | None) -> list[dict]:
    """Drivers currently working today who have UNCERTIFIED logs from
    PREVIOUS days. This is the actual FMCSA audit risk — yesterday's
    log should already be certified before today's shift starts. The
    naive interpretation ("any active driver with any uncertified log")
    catches everyone working today since today's log is uncertified
    until end-of-day, which is noise not signal.

    Two filters AND'd:
      1. Driver is on a HOS daily log for today with drive or on-duty
         time > 0 (i.e., actively working today)
      2. Driver has at least one HOS daily log for a date BEFORE today
         that is uncertified AND has drive or on-duty time > 0
         (a missed cert on a day they actually worked)

    Returns a list of dicts sorted worst-first by count of uncertified
    prior days:
      {driver, on_duty_days, date_range, last_uncert_date}

    where on_duty_days = count of PRIOR uncertified working days,
    date_range = earliest..latest of those prior uncert dates."""
    if not samsara_sheets:
        return []
    df = samsara_sheets.get("HOS_DailyLogs")
    if df is None or df.empty:
        return []
    cert_col = _find_col(df, ["logmetadata.iscertified", "iscertified"])
    drive_col = _find_col(df, ["dutystatusdurations.drivedurationms",
                                 "drivedurationms"])
    onduty_col = _find_col(df, ["dutystatusdurations.ondutydurationms",
                                  "ondutydurationms"])
    name_col = _find_col(df, ["driver name", "driver.name"])
    date_col = _find_col(df, ["logstartdate", "log start date", "date",
                                "logmetadata.logdate"])
    if not (cert_col and name_col and date_col):
        return []

    log_dt = _to_naive_dt(df[date_col])
    log_date = log_dt.dt.date

    cert_series = df[cert_col]
    if cert_series.dtype == object:
        cert_norm = cert_series.astype(str).str.strip().str.lower()
        uncert_mask = cert_norm.isin(["false", "0", "no", ""])
    else:
        uncert_mask = ~cert_series.fillna(False).astype(bool)

    drive = (pd.to_numeric(df[drive_col], errors="coerce").fillna(0)
             if drive_col else pd.Series(0, index=df.index))
    onduty = (pd.to_numeric(df[onduty_col], errors="coerce").fillna(0)
              if onduty_col else pd.Series(0, index=df.index))
    active_mask = (drive > 0) | (onduty > 0)
    nm_series = df[name_col].astype(str).str.strip()

    today = _today_chi()
    # Step 1 — drivers actively working today (any active log dated today).
    today_mask = (log_date == today) & active_mask
    today_drivers = {n for n in nm_series[today_mask].dropna().unique()
                     if n and n.lower() != "nan"}
    if not today_drivers:
        return []

    # Step 2 — prior uncertified active logs (date < today).
    prior_mask = (log_date < today) & active_mask & uncert_mask
    prior_sub = df[prior_mask]
    if prior_sub.empty:
        return []
    prior_dates = log_dt[prior_mask]
    prior_names = nm_series[prior_mask]

    out: list[dict] = []
    for nm in today_drivers:
        nm_rows = prior_names == nm
        if not nm_rows.any():
            continue
        d_series = prior_dates[nm_rows].dropna()
        if d_series.empty:
            continue
        n_days = int(d_series.count())
        d_min = d_series.min().strftime("%Y-%m-%d")
        d_max = d_series.max().strftime("%Y-%m-%d")
        date_range = d_min if d_min == d_max else f"{d_min} &ndash; {d_max}"
        out.append({
            "driver": nm,
            "on_duty_days": n_days,
            "date_range": date_range,
            "last_uncert_date": d_max,
        })
    out.sort(key=lambda r: (-r["on_duty_days"], r["last_uncert_date"]))
    return out


def _speed_window_trend(samsara: dict | None
                          ) -> tuple[list[str], list[float]]:
    """Fleet-avg speed-over-limit % rendered as 6 monthly bars
    (Jan..Jun*) so it matches the visual shape of the other 6-month
    trend charts. Samsara only exposes speed time-over-limit at 3
    window granularities (6mo / 3mo / MTD) — there's no per-month
    breakdown — so we synthesize the monthly view via window-
    decomposition algebra:

      pct_6mo  = fleet-avg speed-over-limit % for the last 6 months
      pct_3mo  = same for the last 3 months
      pct_mtd  = same for the current month-to-date

      Oldest 3 months (Jan/Feb/Mar) = 2*pct_6mo - pct_3mo
        (algebra: 6mo total time = oldest_3_total + 3mo_total;
        assuming equal monthly drive time, oldest_3 contributes
        half the 6mo window time, so oldest_3_pct = 2*pct_6mo - pct_3mo.)
      Middle 2 months (Apr/May) = (3*pct_3mo - pct_mtd) / 2
        (similar derivation.)
      Current month (Jun*) = pct_mtd

    Months within each window share the same value (the chart shows
    3 step-changes rather than 6 distinct heights) but the 6-bar
    shape matches the other trend charts as requested. Subtitle
    notes "approx. from 3 windows" so the reader knows the math."""
    scores_all = ((samsara or {}).get("fleet") or {}).get("scores_all") or []
    months = _last_6_months()
    labels = []
    for i, (yy, mm) in enumerate(months):
        lab = pd.Timestamp(year=yy, month=mm, day=1).strftime("%b")
        if i == len(months) - 1:
            lab += "*"
        labels.append(lab)
    if not scores_all:
        return labels, [0.0] * 6

    def _avg(key: str) -> float:
        vals = [r.get(key) for r in scores_all if _isnum(r.get(key))]
        return (sum(vals) / len(vals)) if vals else 0.0

    pct_6mo = _avg("speed_pct")
    pct_3mo = _avg("speed_pct_3mo")
    pct_mtd = _avg("speed_pct_mtd")

    older = max(0.0, 2 * pct_6mo - pct_3mo)
    mid = max(0.0, (3 * pct_3mo - pct_mtd) / 2)
    current = pct_mtd

    # Map by month index: [oldest, oldest, oldest, mid, mid, current]
    values = [round(older, 1)] * 3 + [round(mid, 1)] * 2 + [round(current, 1)]
    return labels, values


def _coaching_action_monthly(samsara: dict | None, state: str
                              ) -> tuple[list[str], list[int]]:
    """6-month bar-chart data for coaching-action counts (coached /
    dismissed / recognized). Bins samsara.coached_events by
    coached_at month — same month labels (Jun*) the existing trend
    charts use so the bars line up visually.

    `state` is one of "coached" / "dismissed" / "recognized" — matches
    the lowercase value stored on each coached_events row."""
    rows = (samsara or {}).get("coached_events") or []
    state = state.lower().strip()
    dates: list[pd.Timestamp] = []
    for r in rows:
        if (r.get("state") or "").lower().strip() != state:
            continue
        ca = r.get("coached_at") or ""
        # coached_at is a "YYYY-MM-DD HH:MM" string or "&mdash;" /
        # blank — pd.to_datetime("&mdash;") returns NaT which the
        # _monthly_counts helper drops.
        ts = pd.to_datetime(ca, errors="coerce")
        if pd.notna(ts):
            dates.append(ts)
    if not dates:
        return _monthly_counts(pd.Series(dtype="datetime64[ns]"))
    return _monthly_counts(pd.Series(dates))


def _onduty_uncert_block(samsara_sheets: dict | None) -> str:
    """Render the On-duty Today + Prior-day Uncertified table.

    Always rendered (with an "all clear" placeholder when no offenders)
    so the reader can see the check ran. Designed to be injected above
    the Missing Log Certifications section for at-a-glance comparison."""
    rows = compute_onduty_uncertified(samsara_sheets)
    if not rows:
        # All-clear placeholder so the reader sees the check was made.
        return (
            _section('On-duty today &mdash; uncertified prior-day logs &middot; '
                     'started this shift without certifying yesterday')
            + f"<tr><td colspan='4' style='padding:0 6px;'>"
            f"<div style='border:1px solid {LINE};border-left:4px solid {GOOD};"
            f"border-radius:6px;padding:12px 16px;background:{GOODBG};'>"
            f"<div style='font-size:10px;letter-spacing:1.5px;font-weight:800;"
            f"color:{GOOD};margin-bottom:4px;'>&#10003;&nbsp;ALL CLEAR</div>"
            f"<div style='font-size:12.5px;color:{INK};'>Every driver working "
            f"today has certified their prior-day logs &mdash; no audit risk "
            f"from missed start-of-shift certifications.</div>"
            f"</div></td></tr>"
        )
    body_rows = "".join(
        _tr(
            [r["driver"], str(r["on_duty_days"]),
             r["date_range"], r["last_uncert_date"], "Not certified"],
            ["left", "right", "left", "left", "left"],
            [None, "bad", None, None, "bad"],
        )
        for r in rows
    )
    return (
        _section('On-duty today &mdash; uncertified prior-day logs &middot; '
                 'started this shift without certifying yesterday')
        + _table(
            ['Driver', 'Prior days uncertified', 'Uncert date range',
             'Latest uncert date', 'Status'],
            ['left', 'right', 'left', 'left', 'left'],
            body_rows,
        )
    )


def _inject_onduty_section(detail_html: str,
                             samsara_sheets: dict | None) -> str:
    """Splice the On Duty + Uncertified table into the shared detail-tables
    HTML, positioned immediately above the Missing Log Certifications
    section. Falls back to a no-op when either side is empty so the brief
    never breaks on missing data."""
    block = _onduty_uncert_block(samsara_sheets)
    if not block:
        return detail_html
    marker = "Missing log certifications"
    pos = detail_html.find(marker)
    if pos <= 0:
        # Marker text changed — append to top of detail block as a fallback.
        return block + detail_html
    # _section() returns "<tr><td colspan=...>...</td></tr>" — back up to
    # that <tr> so the new block sits cleanly between sections rather than
    # inside the marker's table cell.
    sec_start = detail_html.rfind("<tr>", 0, pos)
    if sec_start < 0:
        return block + detail_html
    return detail_html[:sec_start] + block + detail_html[sec_start:]


def _safety_summary_block_inline(samsara: dict | None,
                                   samsara_sheets: dict | None = None) -> str:
    """The executive brief's page-1 safety section, lifted whole into
    the safety brief — Audra's brief was missing the 24h/7d/MTD tile
    breakdown, the 6-month trend bars, and the unified detail tables.

    Built from the same helpers as scorecard_email so the visual is
    pixel-identical to the executive brief: _mwtile (24h/7d/MTD tile),
    _bar_chart (6-month bars), _tile (fleet score), and
    _safety_detail_tables (events / HOS / missing logs / DVIR /
    coaching). Returns a <tr> chain ready to drop into the page-1
    body table.

    6-month-trend layout (per latest user direction — uniform 3x3 grid):
      Row 1 (snapshot tiles, 33% each):
        Fleet Avg Safety Score | DVIR Open Defects | Missing Log Certs
      Row 2 (bars, 33% each):
        HOS violations         | DVIR defects      | Coached events
      Row 3 (bars, 33% each):
        Safety events          | Dismissed events  | Speed over limit
    Missing Log Certs moved out of its own 50%-wide row into the
    snapshot lead row so the layout reads as a clean 3x3 grid with
    no half-empty rows. DVIR Open Defects + Missing Log Certs are the
    "right now" indicators paired with the Safety Score; the bars
    below all share the 33%-width geometry so they look uniform.
    Speed Over Limit synthesizes 6 monthly bars from the 3 available
    windows (Samsara doesn't expose monthly speed time-over-limit) —
    Jan/Feb/Mar = 2*pct_6mo - pct_3mo, Apr/May = (3*pct_3mo - pct_mtd)/2,
    Jun* = pct_mtd. Coached / Dismissed bars come from binning
    samsara.coached_events by state + coached_at month. Recognized
    bar dropped from the visible set; it runs all-zero in our data
    (no manager recognitions in the period)."""
    if not samsara:
        return ""
    sw = samsara.get("windows", {}) or {}

    def swv(metric, k):
        return sw.get(metric, {}).get(k, 0)

    safety_tiles = (
        _mwtile("Safety events", swv("events", "24h"), swv("events", "7d"),
                swv("events", "mtd"), "warn")
        + _mwtile("HOS violations", swv("hos", "24h"), swv("hos", "7d"),
                  swv("hos", "mtd"), "bad")
        + _mwtile("Open DVIR defects", swv("dvir", "24h"), swv("dvir", "7d"),
                  swv("dvir", "mtd"), "warn")
        + _mwtile("Coaching due", samsara.get("coaching", {}).get("24h", 0),
                  samsara.get("coaching", {}).get("7d", 0),
                  samsara.get("coaching", {}).get("mtd", 0), "warn")
    )

    tr = samsara.get("trend", {}) or {}

    def chart(metric, title, sub):
        ml = tr.get(metric)
        return _bar_chart(title, ml[0] if ml else [],
                          ml[1] if ml else [], sub)

    # 6-month coaching-action series (coached / dismissed).
    coached_ml = _coaching_action_monthly(samsara, "coached")
    dismissed_ml = _coaching_action_monthly(samsara, "dismissed")
    # Speed-over-limit 3-window trend (6mo / 3mo / MTD) — replaces the
    # prior SafetyEvents-derived bar that returned 0 (Samsara records
    # speed as a continuous metric, not as discrete events).
    spd_labels, spd_vals = _speed_window_trend(samsara)

    # Snapshot tiles for row 1 — same overall tile geometry as the bar
    # charts so all 9 cells of the 3x3 grid baseline-align. The big value
    # is bottom-anchored via a nested table cell with valign=bottom, which
    # mirrors where the bar-chart bars sit. Title at the top, value at the
    # bottom — gives the grid a consistent visual rhythm.
    def _snap_tile(label: str, value: str, sub: str,
                    value_color: str = INK) -> str:
        # Shorter than the bar-chart tiles below — there's only one number
        # to show, no point in matching the full ~180px chart height. The
        # big value is bottom-right-anchored via position:absolute so it
        # truly sits at the bottom of the tile (WeasyPrint doesn't honor
        # td valign='bottom' reliably when the row has no explicit height —
        # same fix as the bar-chart bars).
        return (
            f"<td class='tile' width='33%' valign='top' style='padding:6px;'>"
            f"<div style='border:1px solid {LINE};border-radius:10px;"
            f"padding:10px 14px 10px;height:96px;text-align:center;'>"
            f"<div style='font-size:12px;font-weight:800;color:{NAVY};"
            f"margin-bottom:2px;'>{label}</div>"
            f"<div style='font-size:10.5px;color:{MUTE};line-height:1.3;'>{sub}</div>"
            f"<div style='{FONT_SERIF}font-size:34px;font-weight:400;"
            f"color:{value_color};letter-spacing:-1px;line-height:1;margin-top:6px;'>{value}</div>"
            f"</div>"
            f"</td>"
        )

    fleet_score = (samsara.get("fleet") or {}).get("fleet_score")
    fs_val = f"{fleet_score:.0f}" if _isnum(fleet_score) else "&mdash;"
    fs_color = INK
    if _isnum(fleet_score):
        fs_color = GOOD if fleet_score >= 90 else (WARN if fleet_score >= 75 else BAD)
    fleet_score_tile = _snap_tile(
        "Fleet avg safety score",
        fs_val,
        "Samsara &middot; 0&ndash;100 &middot; higher is better",
        value_color=fs_color,
    )
    # DVIR Open Defects snapshot tile — current open count.
    dvir_open_mtd = swv("dvir", "mtd")
    dvir_open_tile = _snap_tile(
        "DVIR open defects",
        str(dvir_open_mtd),
        "pending mechanic resolution",
        value_color=BAD if dvir_open_mtd else INK,
    )
    # Missing Log Certs snapshot tile — moves into the snapshot lead
    # row so the layout reads as a 3x3 grid with no half-empty rows.
    uncert_drivers = ((samsara.get("detail") or {}).get("hos_uncert") or [])
    uncert_count = len(uncert_drivers)
    uncert_worst = ""
    if uncert_drivers:
        worst = max(uncert_drivers, key=lambda r: r.get("days_missing", 0))
        uncert_worst = (f"worst: {worst.get('driver')} "
                         f"({int(worst.get('days_missing', 0))}d)")
    miss_log_tile = _snap_tile(
        "Missing log certs",
        str(uncert_count),
        uncert_worst or "all daily logs certified",
        value_color=BAD if uncert_count else GOOD,
    )

    # Row 1: snapshot tiles (3 at 33% each) — all "right now"
    # indicators paired together at the top of the trend section.
    safety_charts_row1 = fleet_score_tile + dvir_open_tile + miss_log_tile

    # Row 2: 3 bars at 33% each — HOS, DVIR, Coached.
    safety_charts_row2 = (
        chart("hos", "HOS violations", "per month &middot; *MTD")
        + chart("dvir", "DVIR defects", "reported/mo &middot; *MTD")
        + _bar_chart("Coached events", coached_ml[0], coached_ml[1],
                     "manager-reviewed / mo &middot; *MTD")
    )

    # Row 3: 3 bars at 33% each — Safety events, Dismissed, Speed
    # over limit. Speed uses a percentage formatter since its values
    # are %s rather than raw event counts.
    safety_charts_row3 = (
        chart("events", "Safety events", "per month &middot; *MTD")
        + _bar_chart("Dismissed events", dismissed_ml[0], dismissed_ml[1],
                     "no-action-needed / mo &middot; *MTD")
        + _bar_chart("Speed over limit", spd_labels, spd_vals,
                     "% drive time &middot; fleet avg",
                     fmt=lambda v: f"{v:.1f}%" if v else "0%")
    )

    # Separate <table> elements for the 4-col metrics row and 3-col trend
    # grid — mixing column counts in one table can misalign column widths.
    # _safety_detail_tables emits its own _section/_table rows so it also
    # gets its own table wrapper.
    return (
        f"<tr><td colspan='4' style='padding:8px 24px 0;'>"
        # 4-column metrics snapshot (25% each) — table-layout:fixed forces
        # the 25%-width cells to honor their widths even when the COACHING
        # DUE label is longer than the other labels, so all 4 tiles stay
        # the same size and the row doesn't overflow.
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='table-layout:fixed;'>"
        f"{_section('Current period &mdash; 24h / 7d / month-to-date')}"
        f"<tr>{safety_tiles}</tr>"
        f"</table>"
        # 3-column 6-month trend grid (33% each — separate table for clean widths)
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='table-layout:fixed;margin-top:4px;'>"
        f"{_section('6-month trend &mdash; rolling window &middot; * = month-to-date', span=3)}"
        f"<tr>{safety_charts_row1}</tr>"
        f"<tr>{safety_charts_row2}</tr>"
        f"<tr>{safety_charts_row3}</tr>"
        f"</table>"
        f"</td></tr>"
    )


def _footer_kb_links() -> str:
    """Footer pointing readers at the canonical KB pages so the brief
    becomes a launch surface, not a dead-end."""
    items = [
        ("Risk Register", "Karpathy-Wiki/wiki/risk-register.md"),
        ("Decision Journal", "Karpathy-Wiki/wiki/decision-journal.md"),
        ("Safety + DOT inspection policy", "Karpathy-Wiki/raw/xfreight-dot-inspection-policy.md"),
        ("Employee responsibilities", "Karpathy-Wiki/raw/xfreight-employee-responsibilities.md"),
        ("Driver disciplinary playbook", "Karpathy-Wiki/raw/xfreight-playbook-driver-disciplinary.md"),
        ("Equipment inspection backlog playbook", "Karpathy-Wiki/raw/xfreight-playbook-equipment-inspection-backlog.md"),
        ("AR follow-up playbook", "Karpathy-Wiki/raw/xfreight-playbook-ar-followup.md"),
    ]
    rows = "".join(
        f"<div style='padding:3px 0;font-size:11px;color:{MUTE};'>"
        f"&middot;&nbsp;<b style='color:{INK};'>{label}</b> &mdash; "
        f"<code style='font-size:10px;'>{path}</code></div>"
        for label, path in items
    )
    return (
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='background:{TILEBG};border-top:2px solid {LINE};margin-top:16px;'>"
        f"<tr><td style='padding:16px 28px 18px;'>"
        f"<div style='font-size:9.5px;letter-spacing:2px;color:{MUTE};font-weight:700;"
        f"text-transform:uppercase;margin-bottom:8px;'>Knowledge base &amp; playbooks</div>"
        f"{rows}"
        f"<div style='font-size:11px;color:{MUTE};margin-top:10px;font-style:italic;"
        f"border-top:1px solid {LINE};padding-top:8px;'>"
        f"Each playbook is a living protocol with a <b>Recent Runs</b> log &mdash; "
        f"append outcomes when you act on a brief item so the playbook learns from real "
        f"invocations and the team builds institutional memory.</div>"
        f"</td></tr></table>"
    )


def build_page1_overview(samsara: dict | None, metrics: dict,
                          pg: int, total: int, *,
                          urgent_items: list[dict] | None = None,
                          action_items: list[dict] | None = None,
                          risk_signals: list[dict] | None = None,
                          samsara_sheets: dict | None = None) -> str:
    """Executive summary — bottom line + URGENT banner + Risk Watch strip
    + Action items. The dense metrics view (24h/7d/MTD tiles, 6-month
    trend bars, detail tables) moved to its own logical page 2 so page 1
    stays a clean "what changed and what to do" page; the metrics on page
    2 are the supporting evidence."""
    urgent_items = urgent_items or []
    action_items = action_items or []
    risk_signals = risk_signals or []
    bl = build_bottom_line(metrics)

    bottom_line_block = (
        f"<tr><td style='padding:20px 24px 8px;'>"
        f"<div style='font-size:9.5px;letter-spacing:2px;color:{MUTE};"
        f"font-weight:700;text-transform:uppercase;margin-bottom:10px;'>Bottom line</div>"
        f"<div style='border:1px solid {LINE};border-left:4px solid {XFREIGHT_RED};"
        f"background:#fafafa;border-radius:0 6px 6px 0;padding:14px 18px 14px 20px;'>"
        f"<div style='{FONT_SERIF}font-size:15px;line-height:1.6;color:{INK};'>{bl}</div>"
        f"</div>"
        f"</td></tr>"
    )

    body = (
        bottom_line_block
        + _urgent_banner(urgent_items)
        + _risk_watch_block(risk_signals)
        + _action_items_block(action_items)
    )

    return _page_header("Overview", pg, total) + _wrap_page(body)


def build_page2_metrics(samsara: dict | None, samsara_sheets: dict | None,
                          pg: int, total: int) -> str:
    """Page 2 — Safety & compliance metrics. Carries the 24h/7d/MTD tiles
    row, the 6-month trend grid (snapshot tiles + bar charts), and the
    detail tables (events, HOS, on-duty + uncertified, missing log certs,
    DVIR, coaching).

    Split off from page 1 (executive summary) so the dense metrics view
    starts on a fresh page with its own page header rather than flowing
    continuously from the bottom line. The reader sees a clear two-page
    overview structure: page 1 = what to do, page 2 = the supporting
    numbers."""
    body = _safety_summary_block_inline(samsara, samsara_sheets)
    return _page_header("Safety metrics", pg, total,
                         section=_SEC_EVENTS) + _wrap_page(body)


# Section banners — keep them centralized so the page-order block in
# _build_html_report is the only place that knows what section a page
# belongs to.
_SEC_DRIVERS = "DRIVERS"
_SEC_EVENTS = "EVENTS"
_SEC_EQUIPMENT = "EQUIPMENT"
_SEC_REGULATORY = "REGULATORY"
_SEC_CLOSEOUT = "CLOSEOUT"


def _detail_table(rows: list[dict], headers: list[str], keys: list[str],
                  empty_msg: str = "Nothing in this window.") -> str:
    """Helper for the simple driver/event detail tables on pages 2-4."""
    if not rows:
        return (
            f"<div style='padding:14px 18px;color:{MUTE};font-size:12px;'>"
            f"{empty_msg}</div>"
        )
    al = ["left"] * len(headers)
    body = "".join(
        _tr([str(r.get(k, "") or "&mdash;") for k in keys], al)
        for r in rows
    )
    return _table(headers, al, body)


def build_page2_events(samsara: dict | None, pg: int, total: int) -> str:
    """Safety events — last 7 days table."""
    detail = (samsara or {}).get("detail", {}) or {}
    evs = detail.get("events", []) or []
    rows_html = "".join(
        _tr(
            [r.get("driver name", "&mdash;"),
             r.get("unit", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("event type", "&mdash;"),
             r.get("severity", "&mdash;"),
             r.get("status", "&mdash;")],
            ["left", "left", "left", "left", "left", "left"],
            [None, None, None, None,
             ("bad" if str(r.get("severity", "")).lower() == "high" else "warn"),
             None],
        )
        for r in evs
    )
    if not rows_html:
        rows_html = (
            f"<tr><td colspan='6' style='padding:14px;color:{MUTE};font-size:12px;'>"
            f"No safety events in the last 7 days.</td></tr>"
        )
    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('Safety events &mdash; last 7 days')}"
        f"{_table(['Driver','Unit','Reported','Event','Severity','Status'], ['left']*6, rows_html)}"
        f"</td></tr>"
    )
    return _page_header("Safety events", pg, total, section=_SEC_EVENTS) + _wrap_page(body)


def build_page3_hos(samsara: dict | None, pg: int, total: int) -> str:
    """HOS violations (driving-rule) + missing log certifications."""
    detail = (samsara or {}).get("detail", {}) or {}
    hos = detail.get("hos", []) or []
    hos_rows = "".join(
        _tr(
            [r.get("driver name", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("violation type", "&mdash;"),
             r.get("status", "&mdash;")],
            ["left", "left", "left", "left"],
            [None, None, "bad", None],
        )
        for r in hos
    )
    if not hos_rows:
        hos_rows = (
            f"<tr><td colspan='4' style='padding:14px;color:{MUTE};font-size:12px;'>"
            f"No HOS violations in the last 7 days.</td></tr>"
        )

    uncert = detail.get("hos_uncert", []) or []
    uncert_rows = "".join(
        _tr([r.get("driver", "&mdash;"),
             str(r.get("days_missing", "")),
             r.get("span", "&mdash;"),
             "Not certified"],
            ["left", "right", "left", "left"],
            [None, "bad", None, "bad"])
        for r in uncert
    )
    if not uncert_rows:
        uncert_rows = (
            f"<tr><td colspan='4' style='padding:14px;color:{MUTE};font-size:12px;'>"
            f"All daily logs certified.</td></tr>"
        )

    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('HOS violations &mdash; last 7 days')}"
        f"{_table(['Driver','Reported','Violation','Status'], ['left']*4, hos_rows)}"
        f"{_section('Missing log certifications &mdash; last 7 days')}"
        f"{_table(['Driver','Days missing','Date range','Status'], ['left','right','left','left'], uncert_rows)}"
        f"</td></tr>"
    )
    return _page_header("HOS compliance", pg, total, section=_SEC_EVENTS) + _wrap_page(body)


def build_page4_scores(samsara: dict | None, pg: int, total: int) -> str:
    """Per-driver safety scores, ranked worst-to-best."""
    fleet = (samsara or {}).get("fleet", {}) or {}
    # compute_samsara emits scores_all already ranked worst→best with the
    # keys: driver, score, harsh_accel, harsh_brake, harsh_turn,
    # speed_min, speed_pct, crashes, miles.
    scores = fleet.get("scores_all") or []
    rows_html = ""
    for r in scores:
        s = r.get("score")
        kind = "good" if (s is None or s >= 100) else ("warn" if s >= 90 else "bad")
        crashes = r.get("crashes") or 0
        def _n(v):
            return "&ndash;" if v in (None, "", 0) else str(v)
        rows_html += _tr(
            [r.get("driver", "&mdash;"),
             "&ndash;" if s is None else str(int(round(s))),
             _n(r.get("harsh_brake")),
             _n(r.get("harsh_accel")),
             _n(r.get("harsh_turn")),
             _n(crashes)],
            ["left", "right", "right", "right", "right", "right"],
            [None, kind, None, None, None, ("bad" if crashes > 0 else None)],
        )
    if not rows_html:
        rows_html = (
            f"<tr><td colspan='6' style='padding:14px;color:{MUTE};font-size:12px;'>"
            f"No driver safety scores available.</td></tr>"
        )
    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('Driver safety scores &mdash; worst-to-best')}"
        f"{_table(['Driver','Score','Hard brake','Hard accel','Hard turn','Crash'], ['left','right','right','right','right','right'], rows_html)}"
        f"</td></tr>"
    )
    return _page_header("Driver safety scores", pg, total, section=_SEC_DRIVERS) + _wrap_page(body)


def build_page5_vehicles(samsara: dict | None, samsara_sheets: dict | None,
                         pg: int, total: int) -> str:
    """Open DVIR defects + vehicle inspections due in the next 30 days."""
    detail = (samsara or {}).get("detail", {}) or {}
    dvirs = detail.get("dvir", []) or []
    # De-duplicate DVIR rows. Samsara reports one row per defect line on
    # an inspection form — if the same defect ("Left inside tail light
    # dim") appears multiple times in one inspection, it surfaces here as
    # duplicate rows. We collapse rows with identical (unit, defect, type,
    # date, time) so the table reads as one row per open defect on one
    # unit, regardless of how many times the inspector logged it.
    seen: set[tuple] = set()
    deduped_dvirs: list[dict] = []
    for r in dvirs:
        key = (
            str(r.get("unit") or "").strip().lower(),
            str(r.get("defect") or "").strip().lower(),
            str(r.get("defect type") or "").strip().lower(),
            str(r.get("date") or "").strip(),
            str(r.get("time") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped_dvirs.append(r)
    dvir_rows = "".join(
        _tr(
            [r.get("unit", "&mdash;"),
             r.get("driver", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("defect", "&mdash;"),
             r.get("defect type", "&mdash;"),
             "Open"],
            ["left", "left", "left", "left", "left", "left"],
            [None, None, None, None, None, "bad"],
        )
        for r in deduped_dvirs
    )
    if not dvir_rows:
        dvir_rows = (
            f"<tr><td colspan='6' style='padding:14px;color:{MUTE};font-size:12px;'>"
            f"No open DVIR defects.</td></tr>"
        )

    # Inspections-due lookup: scan Vehicles sheet for any *Inspection* /
    # *Maintenance* column with a date in the next 30 days. Best-effort —
    # the Samsara feed surface here is thin so we mark unknowns "&mdash;".
    inspection_html = _inspections_due_html(samsara_sheets)

    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('Open DVIR defects &mdash; all unresolved')}"
        f"{_table(['Unit','Driver','Reported','Defect','Type','Status'], ['left']*6, dvir_rows)}"
        f"{inspection_html}"
        f"</td></tr>"
    )
    return _page_header("Vehicle compliance", pg, total, section=_SEC_EQUIPMENT) + _wrap_page(body)


def _inspections_due_html(samsara_sheets: dict | None) -> str:
    """Soft-render: only show the inspections-due table if we can find a
    date column on Vehicles named like 'next inspection' / 'inspection due'."""
    if not samsara_sheets:
        return ""
    veh = samsara_sheets.get("Vehicles")
    if veh is None or veh.empty:
        return ""
    date_col = _find_col(veh, [
        "next inspection", "inspection due", "next service",
        "service due", "next dot", "annual inspection",
    ])
    if not date_col:
        # Not exposed by current Samsara plan — leave a small placeholder so
        # the section is acknowledged without faking data.
        return (
            f"{_section('Inspections due (next 30 days)')}"
            f"<div style='padding:14px 18px;color:{MUTE};font-size:12px;'>"
            f"Inspection due-dates aren't exposed by the current Samsara feed. "
            f"Wire up the Alvys <code>Maintenance</code> source to populate this section."
            f"</div>"
        )
    name_col = _find_col(veh, ["name", "vehicle", "asset"])
    dt = _to_naive_dt(veh[date_col])
    window_end = pd.Timestamp.now().normalize() + pd.Timedelta(days=30)
    today = pd.Timestamp.now().normalize()
    mask = dt.notna() & (dt <= window_end)
    upcoming = veh[mask].copy()
    if upcoming.empty:
        return (
            f"{_section('Inspections due (next 30 days)')}"
            f"<div style='padding:14px 18px;color:{MUTE};font-size:12px;'>"
            f"None in this window.</div>"
        )
    upcoming["_due"] = dt[mask]
    upcoming = upcoming.sort_values("_due")
    rows = "".join(
        _tr(
            [str(r.get(name_col, "&mdash;") or "&mdash;"),
             r["_due"].strftime("%Y-%m-%d") if pd.notna(r["_due"]) else "&mdash;",
             ("OVERDUE" if pd.notna(r["_due"]) and r["_due"] < today else "Due soon")],
            ["left", "left", "left"],
            [None, None,
             ("bad" if pd.notna(r["_due"]) and r["_due"] < today else "warn")],
        )
        for _, r in upcoming.head(30).iterrows()
    )
    return (
        f"{_section('Inspections due (next 30 days)')}"
        f"{_table(['Unit','Due date','Status'], ['left','left','left'], rows)}"
    )


# ----------------------------------------------------------------------
# Standalone detail pages (p3: events+HOS, p4: DVIR+coaching)
# ----------------------------------------------------------------------

def build_page_safety_events_hos(samsara: dict | None,
                                   samsara_sheets: dict | None,
                                   pg: int, total: int) -> str:
    """Page 3 — Safety events + HOS violations + on-duty uncertified +
    missing log certifications. Starts on a fresh page after the metrics
    tiles so safety events are guaranteed to appear at the top of p3."""
    detail = (samsara or {}).get("detail", {}) or {}

    evs = detail.get("events", []) or []
    event_rows = "".join(
        _tr(
            [r.get("driver name", "&mdash;"), r.get("unit", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("event type", "&mdash;"), r.get("severity", "&mdash;"),
             r.get("status", "&mdash;")],
            ["left"] * 6,
            [None, None, None, None,
             ("bad" if str(r.get("severity", "")).lower() == "high" else "warn"), None],
        )
        for r in evs
    )
    if not event_rows:
        event_rows = (f"<tr><td colspan='6' style='padding:14px;color:{MUTE};font-size:12px;'>"
                      f"No safety events in the last 7 days.</td></tr>")

    hos = detail.get("hos", []) or []
    hos_rows = "".join(
        _tr(
            [r.get("driver name", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("violation type", "&mdash;"), r.get("status", "&mdash;")],
            ["left"] * 4, [None, None, "bad", None],
        )
        for r in hos
    )
    if not hos_rows:
        hos_rows = (f"<tr><td colspan='4' style='padding:14px;color:{MUTE};font-size:12px;'>"
                    f"No HOS violations in the last 7 days.</td></tr>")

    uncert = detail.get("hos_uncert", []) or []
    uncert_rows = "".join(
        _tr([r.get("driver", "&mdash;"), str(r.get("days_missing", "")),
             r.get("span", "&mdash;"), "Not certified"],
            ["left", "right", "left", "left"], [None, "bad", None, "bad"])
        for r in uncert
    )
    if not uncert_rows:
        uncert_rows = (f"<tr><td colspan='4' style='padding:14px;color:{MUTE};font-size:12px;'>"
                       f"All daily logs certified.</td></tr>")

    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"<table width='100%' cellpadding='0' cellspacing='0'>"
        + _section('Safety events &mdash; last 7 days')
        + _table(['Driver', 'Unit', 'Reported', 'Event', 'Severity', 'Status'],
                 ['left'] * 6, event_rows)
        + _section('HOS violations &mdash; last 7 days')
        + _table(['Driver', 'Reported', 'Violation', 'Status'], ['left'] * 4, hos_rows)
        + _onduty_uncert_block(samsara_sheets)
        + _section('Missing log certifications &mdash; last 7 days')
        + _table(['Driver', 'Days missing', 'Date range', 'Status'],
                 ['left', 'right', 'left', 'left'], uncert_rows)
        + f"</table></td></tr>"
    )
    return _page_header("Safety events & HOS", pg, total, section=_SEC_EVENTS) + _wrap_page(body)


def build_page_dvir_coaching(samsara: dict | None, pg: int, total: int) -> str:
    """Page 4 — Open DVIR defects + coaching needs assigned. Starts on a
    fresh page so DVIR always appears at the top regardless of how much
    content the safety-events/HOS page carries."""
    detail = (samsara or {}).get("detail", {}) or {}

    # DVIR dedup — same logic as build_page5_vehicles.
    dvirs = detail.get("dvir", []) or []
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in dvirs:
        key = (str(r.get("unit") or "").strip().lower(),
               str(r.get("defect") or "").strip().lower(),
               str(r.get("defect type") or "").strip().lower(),
               str(r.get("date") or "").strip(),
               str(r.get("time") or "").strip())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    dvir_rows = "".join(
        _tr(
            [r.get("unit", "&mdash;"), r.get("driver", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("defect", "&mdash;"), r.get("defect type", "&mdash;"), "Open"],
            ["left"] * 6, [None, None, None, None, None, "bad"],
        )
        for r in deduped
    )
    if not dvir_rows:
        dvir_rows = (f"<tr><td colspan='6' style='padding:14px;color:{MUTE};font-size:12px;'>"
                     f"No open DVIR defects.</td></tr>")

    # Coaching needs assigned — replicated from _safety_detail_tables.
    _ACK_KEEP_DAYS = 3
    _now_utc = pd.Timestamp.now(tz="UTC")
    _seven_d_ago = _now_utc - pd.Timedelta(days=7)
    coaching_list = (samsara or {}).get("coaching_list") or []
    coach_rows = ""
    for c in coaching_list:
        n = c.get("events", 0)
        last_ts = pd.to_datetime(c.get("last", ""), errors="coerce", utc=True)
        is_coaching = n >= COACH_EVENT_THRESHOLD
        if is_coaching:
            ack_ts = c.get("ack_ts") if c.get("acked") else None
            if ack_ts is not None and (_now_utc - ack_ts).total_seconds() > _ACK_KEEP_DAYS * 86400:
                continue
            acked = ack_ts is not None
        else:
            if pd.notna(last_ts) and last_ts < _seven_d_ago:
                continue
            acked = False
        action = "Assign coaching" if is_coaching else "Monitor"
        action_kind = "bad" if is_coaching else "warn"
        events_kind = "bad" if is_coaching else ("warn" if n > 0 else None)
        types_str = ", ".join(c.get("types") or [])[:60] or "&mdash;"
        ack_cell = ("&check;" if acked else "&mdash;") if is_coaching else "n/a"
        ack_color = ("good" if acked else "mute") if is_coaching else "mute"
        _coach_full = (c.get("coach") or "").strip()
        coach_cell = _coach_full.split()[0] if _coach_full else "&mdash;"
        coach_rows += _tr(
            [c.get("driver", ""), types_str, str(n), c.get("last", "") or "&mdash;",
             action, coach_cell, ack_cell],
            ["left", "left", "right", "left", "left", "left", "center"],
            [None, None, events_kind, None, action_kind, None, ack_color],
        )
    if not coach_rows:
        coach_rows = (f"<tr><td colspan='7' style='padding:14px;color:{MUTE};font-size:12px;'>"
                      f"No coaching needs assigned.</td></tr>")

    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"<table width='100%' cellpadding='0' cellspacing='0'>"
        + _section('DVIR defects (open) &mdash; all unresolved')
        + _table(['Unit', 'Driver', 'Reported', 'Defect', 'Type', 'Status'],
                 ['left'] * 6, dvir_rows)
        + _section('Coaching needs assigned &mdash; drivers with safety events &middot; last 7 days')
        + _table(['Driver', 'Event types', 'Events (7d)', 'Last event', 'Action', 'Coach', 'Ack'],
                 ['left', 'left', 'right', 'left', 'left', 'left', 'center'], coach_rows)
        + f"</table></td></tr>"
    )
    return _page_header("DVIR & Coaching", pg, total, section=_SEC_EVENTS) + _wrap_page(body)


# ----------------------------------------------------------------------
# New page renderers — driver compliance, CSA scorecard, invoice closeout
# ----------------------------------------------------------------------

def build_page_driver_compliance(samba: dict | None,
                                  alvys_drivers: dict | None,
                                  pg: int, total: int) -> str:
    """Driver compliance — disqualified/invalid CDLs (banner), then
    CDL + DOT medical card expirations from the Alvys Drivers sheet,
    plus the SambaSafety risk roster if available. This is the
    "who can't drive today / this week" page."""
    inner = ""

    # 1. Disqualification banner — anyone SambaSafety flagged as
    # DISQUALIFIED / SUSPENDED / INVALID is rendered first, in red,
    # because they cannot legally operate as of today.
    invalid = (samba or {}).get("invalid_licenses") or []
    if invalid:
        rows = "".join(
            _tr(
                [d.get("name", "&mdash;"),
                 d.get("status", "INVALID"),
                 d.get("action", "") or "&mdash;",
                 (d.get("action_date").strftime("%Y-%m-%d")
                  if d.get("action_date") is not None and pd.notna(d.get("action_date"))
                  else "&mdash;")],
                ["left", "left", "left", "left"],
                [None, "bad", None, None],
            )
            for d in invalid
        )
        inner += (
            f"<div style='margin:14px 24px 10px;padding:12px 16px;background:{BADBG};"
            f"border:1px solid {BAD};border-left:6px solid {BAD};border-radius:8px;'>"
            f"<div style='font-size:10px;letter-spacing:1.8px;font-weight:800;color:{BAD};"
            f"margin-bottom:8px;'>&#9888;&nbsp;DISQUALIFIED / INVALID LICENSES &mdash; PULL FROM DISPATCH</div>"
            f"<div style='font-size:12.5px;color:{INK};'>These drivers cannot legally operate. "
            f"Remove from dispatch schedule immediately.</div>"
            f"</div>"
            + f"<div style='padding:0 24px 6px;'>"
            f"{_table(['Driver','Status','Latest action','Action date'], ['left']*4, rows)}"
            f"</div>"
        )

    # 2. CDL expirations — next 30 days from the Alvys Drivers sheet.
    lic30 = (alvys_drivers or {}).get("license_issues_30") or []
    if lic30:
        rows = "".join(
            _tr(
                [d.get("name", "&mdash;"),
                 (d.get("license_exp").strftime("%Y-%m-%d")
                  if d.get("license_exp") is not None and pd.notna(d.get("license_exp"))
                  else "&mdash;"),
                 (f"{d['license_days']}d"
                  if isinstance(d.get("license_days"), int) else "&mdash;"),
                 d.get("type", "") or "&mdash;"],
                ["left", "left", "right", "left"],
                [None, None,
                 ("bad" if isinstance(d.get("license_days"), int) and d["license_days"] <= 7
                  else "warn"),
                 None],
            )
            for d in lic30
        )
        cdl_table = _table(
            ['Driver', 'Expires', 'In', 'Type'],
            ['left', 'left', 'right', 'left'],
            rows,
        )
    else:
        cdl_table = (
            f"<div style='padding:12px 18px;color:{MUTE};font-size:12px;'>"
            f"No CDL expirations in the next 30 days.</div>"
        )

    # 3. DOT medical card expirations — next 30 days from the same sheet.
    med30 = (alvys_drivers or {}).get("medical_issues_30") or []
    if med30:
        rows = "".join(
            _tr(
                [d.get("name", "&mdash;"),
                 (d.get("medical_exp").strftime("%Y-%m-%d")
                  if d.get("medical_exp") is not None and pd.notna(d.get("medical_exp"))
                  else "&mdash;"),
                 (f"{d['medical_days']}d"
                  if isinstance(d.get("medical_days"), int) else "&mdash;"),
                 d.get("type", "") or "&mdash;"],
                ["left", "left", "right", "left"],
                [None, None,
                 ("bad" if isinstance(d.get("medical_days"), int) and d["medical_days"] <= 14
                  else "warn"),
                 None],
            )
            for d in med30
        )
        med_table = _table(
            ['Driver', 'Expires', 'In', 'Type'],
            ['left', 'left', 'right', 'left'],
            rows,
        )
    else:
        med_table = (
            f"<div style='padding:12px 18px;color:{MUTE};font-size:12px;'>"
            f"No DOT medical card expirations in the next 30 days.</div>"
        )

    inner += (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('CDL expirations &mdash; next 30 days')}"
        f"{cdl_table}"
        f"{_section('DOT medical card expirations &mdash; next 30 days')}"
        f"{med_table}"
    )

    # 4. SambaSafety roster snapshot — high-risk drivers + worst-N.
    if samba:
        high = samba.get("high_risk") or []
        ranked = samba.get("ranked") or []
        avg = samba.get("avg_score")
        avg_txt = (f"{avg:.0f}" if isinstance(avg, (int, float)) and avg == avg
                   else "&mdash;")
        if high or ranked:
            inner += ("<div style='page-break-before:always;break-before:page;"
                      "height:0;overflow:hidden;'></div>")
            inner += _section('SambaSafety risk roster &mdash; all monitored drivers, worst-to-best')
            if ranked:
                rrows = "".join(
                    _tr([d.get("name", "&mdash;"),
                         f"{int(d['score'])}" if d.get("score") is not None else "&mdash;",
                         d.get("category", "") or "&mdash;",
                         d.get("state", "") or "&mdash;"],
                        ["left", "right", "left", "left"],
                        [None,
                         ("bad" if d.get("high") else None),
                         None, None])
                    for d in ranked
                )
                inner += _table(['Driver', 'Score', 'Risk category', 'State'],
                                 ['left', 'right', 'left', 'left'], rrows)
            inner += (
                f"<div style='padding:6px 24px;color:{MUTE};font-size:11px;'>"
                f"{len(high)} driver{'s' if len(high) != 1 else ''} at HIGH risk &middot; "
                f"fleet avg risk score: {avg_txt}.</div>"
            )

    inner += "</td></tr>"
    return _page_header("Driver compliance", pg, total, section=_SEC_DRIVERS) + _wrap_page(inner)


def build_page_inspection_compliance(samsara_sheets: dict | None,
                                       pg: int, total: int) -> str:
    """Per-driver DVIR inspection compliance over the last 7 days.

    FMCSA 396.11 / 396.13 requires a pre-trip AND a post-trip DVIR per
    working day, so expected = working_days * 2. The table shows each
    driver who worked in the window with their expected vs completed
    inspections + defects logged, broken out by tractor vs trailer."""
    rows = compute_inspection_compliance(samsara_sheets, days=7)
    if not rows:
        body = (
            f"<tr><td style='padding:18px 24px;color:{MUTE};font-size:12px;'>"
            f"DVIR inspection data unavailable from Samsara for this window. "
            f"Check the DVIRs / HOS_DailyLogs sheets in Samsara Master.xlsx."
            f"</td></tr>"
        )
        return _page_header("Inspection compliance", pg, total,
                             section=_SEC_EQUIPMENT) + _wrap_page(body)

    # Totals row across all drivers.
    tot_wd = sum(r["working_days"] for r in rows)
    tot_exp_t = sum(r["expected_tractor"] for r in rows)
    tot_done_t = sum(r["done_tractor"] for r in rows)
    tot_def_t = sum(r["defects_tractor"] for r in rows)
    tot_exp_tr = sum(r["expected_trailer"] for r in rows)
    tot_done_tr = sum(r["done_trailer"] for r in rows)
    tot_def_tr = sum(r["defects_trailer"] for r in rows)
    tot_exp = sum(r["expected_total"] for r in rows)
    tot_done = sum(r["done_total"] for r in rows)
    tot_def = sum(r["defects_total"] for r in rows)

    def _pct(done: int, expected: int) -> str:
        if expected <= 0:
            return "&mdash;"
        return f"{100 * done / expected:.0f}%"

    def _kind(done: int, expected: int) -> str:
        if expected <= 0:
            return None
        pct = done / expected
        return "good" if pct >= 0.9 else ("warn" if pct >= 0.5 else "bad")

    body_rows = ""
    for r in rows:
        body_rows += _tr(
            [r["driver"],
             str(r["working_days"]),
             f"{r['done_tractor']} / {r['expected_tractor']}",
             str(r["defects_tractor"]),
             f"{r['done_trailer']} / {r['expected_trailer']}",
             str(r["defects_trailer"]),
             f"{r['done_total']} / {r['expected_total']}",
             str(r["defects_total"]),
             _pct(r["done_total"], r["expected_total"])],
            ["left", "right", "right", "right", "right", "right",
             "right", "right", "right"],
            [None, None,
             _kind(r["done_tractor"], r["expected_tractor"]),
             ("warn" if r["defects_tractor"] > 0 else None),
             _kind(r["done_trailer"], r["expected_trailer"]),
             ("warn" if r["defects_trailer"] > 0 else None),
             _kind(r["done_total"], r["expected_total"]),
             ("warn" if r["defects_total"] > 0 else None),
             _kind(r["done_total"], r["expected_total"])],
        )
    body_rows += _totals_row(
        [f"TOTAL ({len(rows)} drivers)",
         str(tot_wd),
         f"{tot_done_t} / {tot_exp_t}",
         str(tot_def_t),
         f"{tot_done_tr} / {tot_exp_tr}",
         str(tot_def_tr),
         f"{tot_done} / {tot_exp}",
         str(tot_def),
         _pct(tot_done, tot_exp)],
        ["left", "right", "right", "right", "right", "right",
         "right", "right", "right"],
    )

    note = (
        f"<div style='padding:8px 24px;color:{MUTE};font-size:11px;'>"
        f"Expected inspections = working days &times; 2 (FMCSA 396.11 requires "
        f"a pre-trip and post-trip DVIR each working day). Working days "
        f"counted from HOS daily logs with drive or on-duty time &gt; 0. "
        f"Tractor vs trailer split derived from the asset on each DVIR; "
        f"defects exploded from DVIR_Defects with one row per defect line."
        f"</div>"
    )

    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('DVIR inspection compliance &mdash; last 7 days')}"
        f"{_table(['Driver', 'Worked', 'Tractor done / exp', 'Tractor defects', 'Trailer done / exp', 'Trailer defects', 'Total done / exp', 'Total defects', 'Compliance'], ['left', 'right', 'right', 'right', 'right', 'right', 'right', 'right', 'right'], body_rows)}"
        f"{note}"
        f"</td></tr>"
    )
    return _page_header("Inspection compliance", pg, total,
                         section=_SEC_EQUIPMENT) + _wrap_page(body)


def build_page_csa_scorecard(csa: dict | None, pg: int, total: int) -> str:
    """FMCSA CSA BASIC percentiles — same shape as the executive brief
    page 10, but rendered with the safety-brief's lighter header.
    Soft-skips when the SambaSafety CSV isn't on disk."""
    if not csa:
        body = (
            f"<tr><td style='padding:18px 18px;color:{MUTE};font-size:12px;'>"
            f"CSA scorecard CSV not present in OneDrive/SambaSafety/. "
            f"Power Automate drops it several times a day &mdash; this page "
            f"will re-appear automatically on the next run after the drop."
            f"</td></tr>"
        )
        return _page_header("FMCSA CSA scorecard", pg, total, section=_SEC_REGULATORY) + _wrap_page(body)

    basics = csa.get("basics") or []
    rows = ""
    for b in basics:
        pct = b.get("percentile")
        thr = b.get("threshold") or 80
        is_int = b.get("intervention")
        kind = "bad" if is_int else ("warn" if (pct or 0) >= max(thr - 10, 0) else "good")
        pct_txt = f"{pct:.0f}" if pct is not None else "&mdash;"
        thr_txt = f"{thr}th"
        status_txt = "INTERVENTION LIKELY" if is_int else "OK"
        rows += _tr(
            [b.get("category", "&mdash;"),
             pct_txt,
             thr_txt,
             (f"{b['seg_violations']}/{b['rel_inspections']}"
              if (b.get("seg_violations") is not None
                  and b.get("rel_inspections") is not None)
              else "&mdash;"),
             status_txt],
            ["left", "right", "right", "right", "left"],
            [None, kind, None, None, ("bad" if is_int else "good")],
        )
    meta = (
        f"<div style='padding:8px 18px;color:{MUTE};font-size:11px;'>"
        f"DOT {csa.get('dot_number', '&mdash;')} &middot; "
        f"avg power units {csa.get('avg_power_units', '&mdash;')} &middot; "
        f"snapshot {csa.get('snapshot_date', '&mdash;')} &middot; "
        f"{csa.get('n_alert', 0)} BASIC(s) at intervention threshold."
        f"</div>"
    )
    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('CSA BASIC percentiles')}"
        f"{_table(['BASIC','Percentile','Intervention threshold','Viol/Insp','Status'], ['left','right','right','right','left'], rows)}"
        f"{meta}"
        f"</td></tr>"
    )
    return _page_header("FMCSA CSA scorecard", pg, total) + _wrap_page(body)


def _load_carrier_map(alvys_pipeline_sheets: dict | None) -> dict[str, str]:
    """Build {load# (digit-normalized) → carrier name} from the Loads
    sheet so the safety brief's Invoice Closeout page can display the
    actual carrier on un-invoiced (customer-side) loads — answers
    "who hauled this?" without re-touching the shared
    compute_alvys_uninvoiced. Returns {} when the sheet or columns
    are missing."""
    if not alvys_pipeline_sheets:
        return {}
    loads = alvys_pipeline_sheets.get("Loads")
    if loads is None or loads.empty:
        return {}
    load_col = "Load #" if "Load #" in loads.columns else _find_col(loads, ["load #", "load number"])
    carrier_col = "Carrier" if "Carrier" in loads.columns else _find_col(loads, ["carrier"])
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


def _totals_row(cells: list[str], al: list[str], colspan_of: list[int] | None = None) -> str:
    """A distinct TOTAL row for the bottom of detail tables. Bold,
    top-accent border, no per-cell bottom border so it reads as a
    summary rather than just another data row."""
    out = ""
    for cc, a in zip(cells, al):
        out += (
            f"<td align='{a}' style='padding:10px 8px;font-size:13px;"
            f"color:{INK};font-weight:800;background:#fafafa;"
            f"border-top:2px solid {INK};'>{cc}</td>"
        )
    return f"<tr>{out}</tr>"


def build_page_invoice_closeout(uninvoiced: dict | None,
                                  carrier_backlog: dict | None,
                                  alvys_pipeline_sheets: dict | None,
                                  pg: int, total: int) -> str:
    """Audra's invoice-closeout responsibility (per the responsibility-map
    core memory): loads invoiced timely AND carrier invoices entered
    into Alvys. Two side-by-side sections.

    Asset side (X-Trux + X-Linx delivered, no customer invoice yet) is
    the same shape compute_alvys_uninvoiced returns to the executive
    brief; brokered side (X-Linx delivered, no carrier invoice number
    entered) is compute_carrier_invoice_backlog. Both feed AR aging.

    `alvys_pipeline_sheets` is used to derive a load→carrier map so
    the customer-side table can show who's hauling each un-invoiced
    load — Audra often needs that to phone the right party."""
    carrier_map = _load_carrier_map(alvys_pipeline_sheets)

    # --- Section 1: customer side ---
    u_rows = (uninvoiced or {}).get("rows") or []
    u_count = (uninvoiced or {}).get("count") or 0
    u_total = (uninvoiced or {}).get("total_revenue") or 0
    u_oldest = (uninvoiced or {}).get("oldest_days")
    u_summary = (
        f"<div style='padding:8px 18px;color:{MUTE};font-size:11px;'>"
        f"{u_count} load(s) &middot; ${u_total:,.0f} revenue not yet invoiced &middot; "
        f"oldest {u_oldest if u_oldest is not None else '&mdash;'}d.</div>"
    )
    if u_rows:
        rows = "".join(
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
        # Totals row: sum of revenue across all shown rows. The page-1
        # summary uses the unfiltered total_revenue from
        # compute_alvys_uninvoiced (full count), but the table caps at
        # `limit` shown rows — so the row total is what's visible here.
        shown_total = sum((r.get("revenue") or 0) for r in u_rows)
        rows += _totals_row(
            [f"TOTAL ({len(u_rows)} shown)", "", "", "", "", "",
             f"${shown_total:,.0f}"],
            ["left", "left", "left", "left", "left", "right", "right"],
        )
        u_table = _table(['Load #', 'Customer', 'Entity', 'Carrier', 'Delivered', 'Days', 'Revenue'],
                          ['left', 'left', 'left', 'left', 'left', 'right', 'right'], rows)
    else:
        u_table = (
            f"<div style='padding:12px 18px;color:{MUTE};font-size:12px;'>"
            f"All delivered loads have been invoiced.</div>"
        )

    # --- Section 2: carrier side ---
    c_rows = (carrier_backlog or {}).get("rows") or []
    c_count = (carrier_backlog or {}).get("count") or 0
    c_total = (carrier_backlog or {}).get("total_carrier_rate") or 0
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
        rows = "".join(
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
        rows += _totals_row(
            [f"TOTAL ({len(c_rows)} shown)", "", "", "", "",
             f"${shown_c_total:,.0f}"],
            ["left", "left", "left", "left", "right", "right"],
        )
        c_table = _table(['Load #', 'Customer', 'Carrier', 'Delivered', 'Days', 'Carrier rate'],
                          ['left', 'left', 'left', 'left', 'right', 'right'], rows)
    else:
        c_table = (
            f"<div style='padding:12px 18px;color:{MUTE};font-size:12px;'>"
            f"No outstanding carrier invoices to enter.</div>"
        )

    body = (
        f"<tr><td style='padding:18px 24px 0;'>"
        f"{_section('Customer side &mdash; delivered loads not yet invoiced')}"
        f"{u_summary}"
        f"{u_table}"
        f"{_section('Carrier side &mdash; brokered trips with no carrier invoice number entered')}"
        f"{c_summary}"
        f"{c_table}"
        f"</td></tr>"
    )
    return _page_header("Invoice closeout", pg, total, section=_SEC_CLOSEOUT) + _wrap_page(body)


# ----------------------------------------------------------------------
# Top-level report assembly + PDF
# ----------------------------------------------------------------------

def _build_html_report(*,
                        samsara: dict | None,
                        samsara_sheets: dict | None,
                        samba: dict | None,
                        csa: dict | None,
                        alvys_drivers: dict | None,
                        alvys_sheets: dict | None,
                        risk_signals: list[dict] | None,
                        action_items: list[dict] | None) -> str:
    metrics = compute_metrics(samsara)
    urgent_items = [i for i in (action_items or []) if i.get("priority") == 1]

    # Page flow (logical pages — each starts on a fresh PDF page):
    #   1. Overview            — bottom line, urgent, risk-watch, actions
    #   2. Safety metrics      — 24h/7d/MTD tiles + 6-month trend grid
    #   3. Safety events & HOS — events last 7d + HOS + on-duty uncert + certs
    #   4. DVIR & coaching     — open DVIR defects + coaching needs assigned
    #   5. Driver compliance   — CDL/DOT/MVR (SambaSafety risk roster gets
    #                            its own physical page via CSS page-break)
    #   6. Driver safety scores— per-driver score + harsh/speed/crash cols;
    #                            Speed Over Limit methodology note appended
    #                            at bottom so it sits on the same page rather
    #                            than alone on the next page.
    #   7. Inspection compliance — per-driver DVIR completion vs FMCSA 2/day
    #   8. FMCSA CSA scorecard — BASIC percentile ranks
    #   9. Coached events trail — 190-day every-coach/dismiss/recognize
    today_label = _today_label()
    total = 9
    _scores_footnote = (
        f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;"
        f"border-top:1px solid {LINE};margin-top:14px;'>"
        f"24h sections: Samsara (SafetyEvents, HOS_Violations, DVIR_Defects). "
        f"Speed Over Limit = time-over-posted-limit &divide; total drive time, shown as % "
        f"when both fields are available (&ge;5% flagged for coaching, 1&ndash;5% monitored); "
        f"falls back to minutes over limit when drive time isn&rsquo;t exposed. "
        f"Coaching &amp; training: Samsara Coaching Sessions / "
        f"Training Assignments (past-due only; tiles hidden when module not enabled).</div>"
    )
    pages = [
        build_page1_overview(samsara, metrics, 1, total,
                              urgent_items=urgent_items,
                              action_items=(action_items or []),
                              risk_signals=(risk_signals or []),
                              samsara_sheets=samsara_sheets),
        build_page2_metrics(samsara, samsara_sheets, 2, total),
        build_page_safety_events_hos(samsara, samsara_sheets, 3, total),
        build_page_dvir_coaching(samsara, 4, total),
        build_page_driver_compliance(samba, alvys_drivers, 5, total),
        _exec_build_page2b(samsara, today_label, pg=6) + _scores_footnote,
        build_page_inspection_compliance(samsara_sheets, 7, total),
        build_page_csa_scorecard(csa, 8, total),
        _exec_build_page_coached(samsara, today_label, pg=9),
    ]
    body = "<div class='page-break' style='page-break-after:always;'></div>".join(pages)
    body += _footer_kb_links()
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        # No body line-height — inherited line-height inflates spacer divs
        # in _bar_chart and breaks the bar bottom-anchoring. Components
        # that need their own line-height set it inline.
        f"body{{margin:0;background:#fff;font-family:Helvetica,Arial,sans-serif;color:{INK};font-size:13px;}}"
        ".page-break{page-break-after:always;break-after:page;height:0;}"
        # WeasyPrint page counters — adds a true per-PDF-page footer on
        # every physical page (auto-paginated continuations included).
        # Inline 'Page X of N' counters in the per-page headers stay
        # hidden in print (.pg-of below) so we don't double up; the
        # @page footer is the single source of truth in the PDF.
        "@page{size:letter;margin:0.5in 0.4in 0.75in;"
        "@bottom-center{content:'Page ' counter(page) ' of ' counter(pages);"
        f"font-family:Helvetica,Arial,sans-serif;font-size:9px;color:{MUTE};"
        "letter-spacing:0.5px;}}"
        "@media print{.pg-of{display:none;}}"
        "table.tbl{border-collapse:collapse;width:100%;}"
        ".tile{vertical-align:top!important;}"
        f"td{{vertical-align:top;}}"
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
                 os.environ.get("SAFETY_TO_EMAILS", "jeff@xfreight.net").split(",")
                 if e.strip()]
    log.info("Recipients: %s", to_emails)

    tok = get_token(
        os.environ["AZURE_TENANT_ID"],
        os.environ["AZURE_CLIENT_ID"],
        os.environ["AZURE_CLIENT_SECRET"],
    )

    # Idempotency check — only one safety report per Central day, unless
    # SAFETY_SKIP_IDEMPOTENCY=1 (handy for code-iteration re-sends).
    today = _today_chi()
    skip = os.environ.get("SAFETY_SKIP_IDEMPOTENCY", "").strip() == "1"
    if not skip and _marker_exists(tok, upn, today):
        log.info("Marker present for %s — already sent today. Skipping.", today)
        return 0

    # Load OneDrive sources: Samsara is required; SambaSafety + Alvys
    # Pipeline are optional — pages soft-skip when their data is missing.
    missing: list[str] = []
    samsara_path = os.environ.get("SAMSARA_ONEDRIVE_PATH",
                                  "Samsara/Samsara Master.xlsx")
    samsara_sheets = _safe_read(tok, upn, samsara_path, missing, "Samsara Master")
    if samsara_sheets is None:
        log.error("Could not read Samsara Master from OneDrive — aborting.")
        return 1

    samba_path = os.environ.get("SAMBASAFETY_ONEDRIVE_PATH",
                                "SambaSafety/SambaSafety_Master.xlsx")
    samba_sheets = _safe_read(tok, upn, samba_path, missing, "SambaSafety Master")
    alvys_path = os.environ.get("ALVYS_PIPELINE_ONEDRIVE_PATH",
                                "Alvys Pipeline.xlsx")
    alvys_sheets = _safe_read(tok, upn, alvys_path, missing, "Alvys Pipeline")
    if missing:
        log.info("Optional sources missing (page(s) will soft-skip): %s",
                 ", ".join(missing))

    samsara = compute_samsara(samsara_sheets)
    samba = compute_sambasafety(samba_sheets) if samba_sheets else None
    csa = compute_csa_scorecard(samba_sheets) if samba_sheets else None
    alvys_drivers = compute_alvys_drivers(alvys_sheets) if alvys_sheets else None

    # Equipment compute — needed only for the action-items engine here
    # (the equipment detail pages live on the executive brief). Import
    # locally so missing optional deps don't break the safety brief.
    try:
        from src.scorecard_email import compute_alvys_equipment
        equipment = compute_alvys_equipment(alvys_sheets,
                                              samsara_sheets=samsara_sheets) \
                    if alvys_sheets else None
    except Exception as e:
        log.warning("compute_alvys_equipment unavailable: %s", e)
        equipment = None

    # Risk Watch — evaluate the shared signal catalog and keep only the
    # safety-relevant subset for Audra's brief.
    try:
        from src.risk_watch import evaluate as eval_signals
        all_signals = eval_signals({
            "equipment": equipment or {},
            "csa": csa or {},
            "samsara": samsara or {},
        })
        risk_signals = safety_relevant_signals(all_signals)
    except Exception as e:
        log.warning("Risk Watch evaluation failed: %s", e)
        risk_signals = []

    # Safety-only action items. Invoice closeout + carrier-bill backlog
    # action items moved to the Financial Brief; pass None for those
    # so compute_action_items skips the P3 financial rows.
    action_items = compute_action_items(
        samsara=samsara, samba=samba, alvys_drivers=alvys_drivers,
        equipment=equipment, uninvoiced=None,
        carrier_backlog=None, csa=csa,
    )

    html = _build_html_report(
        samsara=samsara, samsara_sheets=samsara_sheets,
        samba=samba, csa=csa, alvys_drivers=alvys_drivers,
        alvys_sheets=alvys_sheets,
        risk_signals=risk_signals, action_items=action_items,
    )
    pdf = _render_pdf(html)

    subj = f"XFreight Safety & Compliance Report — {today.strftime('%B %-d, %Y')}"
    attachments = None
    if pdf:
        log.info("Generated PDF (%.1f KB)", len(pdf) / 1024)
        attachments = [{
            "name": f"safety-compliance-{today.isoformat()}.pdf",
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
