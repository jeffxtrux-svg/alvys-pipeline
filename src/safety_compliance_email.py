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
    FONT_SERIF,
    INK,
    LINE,
    MUTE,
    XFREIGHT_RED,
    _find_col,
    _safe_read,
    _section,
    _table,
    _tile,
    _to_naive_dt,
    _tr,
    _windows,
    compute_samsara,
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


def _page_header(title: str, pg: int, total: int) -> str:
    """Lighter header than the executive brief — no logo SVG to keep
    the dependency surface low. Title + date stamp + page counter."""
    today = _today_label()
    return (
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-bottom:4px solid {XFREIGHT_RED};padding:6px 24px 14px;'>"
        f"<tr>"
        f"<td valign='middle' style='padding:0;'>"
        f"<div style='font-size:10px;letter-spacing:2px;color:{XFREIGHT_RED};"
        f"font-weight:800;'>XFREIGHT &middot; SAFETY &amp; COMPLIANCE</div>"
        f"<div style='{FONT_SERIF}font-size:18px;color:{INK};margin-top:4px;'>{title}</div>"
        f"</td>"
        f"<td align='right' valign='middle' style='padding:0;font-size:11px;color:{MUTE};'>"
        f"<div style='{FONT_SERIF}font-style:italic;font-weight:600;color:{INK};'>{today}</div>"
        f"<div class='pg-of' style='font-size:9px;margin-top:4px;letter-spacing:0.5px;'>"
        f"Page {pg} of {total}</div>"
        f"</td>"
        f"</tr></table>"
    )


def build_page1_overview(samsara: dict | None, metrics: dict, pg: int, total: int) -> str:
    """Bottom line at the top + KPI tiles."""
    bl = build_bottom_line(metrics)

    def _fmt(v):
        return "&mdash;" if v is None else str(v)

    score = metrics.get("fleet_score")
    score_sub = "Lower = more incidents per mile"
    if metrics.get("events_trend_change") is not None:
        d = metrics["events_trend_change"]
        if d == 0:
            score_sub = "Events vs prior month: flat"
        else:
            arrow = "&#9650;" if d > 0 else "&#9660;"
            score_sub = f"Events vs prior month: {arrow} {abs(d)}"

    uc_sub = (
        f"Worst: {metrics['uncert_worst_name']} ({metrics['uncert_worst_days']}d)"
        if metrics.get("uncert_worst_name")
        else "All daily logs certified"
    )

    tiles_row1 = (
        "<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        + _tile("Fleet Safety Score", _fmt(int(round(score)) if score is not None else None),
                score_sub, width="25%")
        + _tile("Safety Events (7d)", _fmt(metrics["events_7d"]),
                f"{metrics['events_24h']} in last 24h", width="25%")
        + _tile("HOS Violations (7d)", _fmt(metrics["hos_7d"]),
                "Driving-rule breaches only", width="25%")
        + _tile("DVIR Open Defects", _fmt(metrics["dvir_open"]),
                "Pending mechanic resolution", width="25%")
        + "</tr></table>"
    )

    tiles_row2 = (
        "<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        + _tile("Missing Log Certs", _fmt(metrics["uncert_drivers"]),
                uc_sub, width="50%")
        + _tile("Safety Events (30d)", _fmt(metrics["events_30d"]),
                "Rolling 30-day rollup", width="50%")
        + "</tr></table>"
    )

    bottom_line_block = (
        f"<tr><td style='padding:18px 24px 6px;'>"
        f"<div style='font-size:10px;letter-spacing:2px;color:{MUTE};"
        f"font-weight:700;margin-bottom:8px;'>BOTTOM LINE</div>"
        f"<div style='{FONT_SERIF}font-size:15px;line-height:1.55;color:{INK};"
        f"border-left:3px solid {XFREIGHT_RED};padding-left:14px;'>{bl}</div>"
        f"</td></tr>"
        f"<tr><td style='padding:14px 18px 8px;'>{tiles_row1}</td></tr>"
        f"<tr><td style='padding:0 18px 14px;'>{tiles_row2}</td></tr>"
    )

    return _page_header("Overview", pg, total) + _wrap_page(bottom_line_block)


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
        f"<tr><td style='padding:18px 18px 0;'>"
        f"{_section('Safety events &mdash; last 7 days')}"
        f"{_table(['Driver','Unit','Reported','Event','Severity','Status'], ['left']*6, rows_html)}"
        f"</td></tr>"
    )
    return _page_header("Safety events", pg, total) + _wrap_page(body)


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
        f"<tr><td style='padding:18px 18px 0;'>"
        f"{_section('HOS violations &mdash; last 7 days')}"
        f"{_table(['Driver','Reported','Violation','Status'], ['left']*4, hos_rows)}"
        f"{_section('Missing log certifications &mdash; last 7 days')}"
        f"{_table(['Driver','Days missing','Date range','Status'], ['left','right','left','left'], uncert_rows)}"
        f"</td></tr>"
    )
    return _page_header("HOS compliance", pg, total) + _wrap_page(body)


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
        f"<tr><td style='padding:18px 18px 0;'>"
        f"{_section('Driver safety scores &mdash; worst-to-best')}"
        f"{_table(['Driver','Score','Hard brake','Hard accel','Hard turn','Crash'], ['left','right','right','right','right','right'], rows_html)}"
        f"</td></tr>"
    )
    return _page_header("Driver safety scores", pg, total) + _wrap_page(body)


def build_page5_vehicles(samsara: dict | None, samsara_sheets: dict | None,
                         pg: int, total: int) -> str:
    """Open DVIR defects + vehicle inspections due in the next 30 days."""
    detail = (samsara or {}).get("detail", {}) or {}
    dvirs = detail.get("dvir", []) or []
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
        for r in dvirs
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
        f"<tr><td style='padding:18px 18px 0;'>"
        f"{_section('Open DVIR defects &mdash; all unresolved')}"
        f"{_table(['Unit','Driver','Reported','Defect','Type','Status'], ['left']*6, dvir_rows)}"
        f"{inspection_html}"
        f"</td></tr>"
    )
    return _page_header("Vehicle compliance", pg, total) + _wrap_page(body)


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
# Top-level report assembly + PDF
# ----------------------------------------------------------------------

def _build_html_report(samsara: dict | None, samsara_sheets: dict | None) -> str:
    metrics = compute_metrics(samsara)
    total = 5
    pages = [
        build_page1_overview(samsara, metrics, 1, total),
        build_page2_events(samsara, 2, total),
        build_page3_hos(samsara, 3, total),
        build_page4_scores(samsara, 4, total),
        build_page5_vehicles(samsara, samsara_sheets, 5, total),
    ]
    body = "<div class='page-break' style='page-break-after:always;'></div>".join(pages)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "body{margin:0;background:#fff;font-family:Helvetica,Arial,sans-serif;color:" + INK + ";}"
        ".page-break{page-break-after:always;break-after:page;height:0;}"
        "@page{size:letter;margin:0.45in 0.35in 0.55in;}"
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

    # Load Samsara_Master.xlsx from OneDrive (same path the scorecard reads).
    missing: list[str] = []
    samsara_path = os.environ.get("SAMSARA_ONEDRIVE_PATH",
                                  "Samsara/Samsara Master.xlsx")
    samsara_sheets = _safe_read(tok, upn, samsara_path, missing, "Samsara Master")
    if samsara_sheets is None:
        log.error("Could not read Samsara Master from OneDrive — aborting.")
        return 1

    samsara = compute_samsara(samsara_sheets)
    html = _build_html_report(samsara, samsara_sheets)
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
