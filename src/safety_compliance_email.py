"""
Safety & Compliance Report — daily PDF brief.
Matches the June 15 2026 format: XFREIGHT logo + section-pill headers,
full page ordering, and all tables, tiles, and visuals.

Pages (logical sections; PDF pagination depends on content length):
  1.   Overview — Bottom Line · Urgent · Risk Watch · Action Items       [EVENTS]
  2.   Safety Metrics — multi-window KPI tiles · summary boxes · charts  [EVENTS]
  3.   Safety Events & HOS — events · violations · missing log certs     [EVENTS]
  4.   DVIR Defects — all open defects, deduplicated                     [EVENTS]
  5-6. Driver Compliance — SambaSafety + Alvys DOT medical cards         [DRIVERS]
  7.   Speed over Posted Limit — per-driver 6-month trend               [SAFETY]
  8.   Methodology Footnote                                               [SAFETY]
  9-10. Tractor Inspections — 120d policy + reg + mileage + oil         [SAFETY]
  11-12. Trailer Inspections — 120d policy + reg                         [SAFETY]
  13.  FMCSA CSA Scorecard — BASIC percentile scores                    [REGULATORY]
  14.  Driver Safety Scores — all drivers, worst-to-best                [SAFETY]
  15+. Coached Events — 190-day audit trail                              [SAFETY]
  Last. Knowledge Base & Playbooks                                        [SAFETY]

Data sources:
  Samsara/Samsara Master.xlsx         — safety events, HOS, DVIR, coaching, scores
  SambaSafety/SambaSafety_Master.xlsx — driver license status, CSA (optional)
  Alvys Pipeline.xlsx                 — Trucks, Trailers, Drivers (optional)
"""
from __future__ import annotations

import datetime
import logging
import os
import re
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
    # Design tokens
    FONT_SERIF, INK, LINE, MUTE, XFREIGHT_RED,
    BAD, BADBG, GOOD, GOODBG, WARN, WARNBG, TILEBG,
    # Low-level helpers
    _find_col, _isnum, _last_6_months, _monthly_counts, _safe_read,
    _section, _table, _tile, _mwtile, _bar_chart,
    _to_naive_dt, _tr, _windows,
    _pill, _brief, num,
    _xfreight_logo_svg,
    # Data computers
    compute_samsara, compute_sambasafety, compute_csa_scorecard,
    compute_alvys_equipment, compute_alvys_drivers,
    # Page builders reused from the executive brief
    build_page9, build_page_equipment, build_page_coached,
    build_page2b, build_csa_scorecard_page,
    # Email
    send_email,
)

log = logging.getLogger("safety_compliance_email")

# ----------------------------------------------------------------------
# Date helpers
# ----------------------------------------------------------------------

def _today_chi() -> datetime.date:
    return datetime.datetime.now(ZoneInfo("America/Chicago")).date()


def _today_label() -> str:
    return _today_chi().strftime("%A, %B %d, %Y")


# Idempotency marker so staggered backup crons short-circuit once sent.
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
# Branded page header — XFREIGHT logo + section pill (matches brief style)
# ----------------------------------------------------------------------

def _sc_header(sub: str, pg: int, total: int, date_str: str,
               section: str | None = None) -> str:
    """Safety-report page header: XFREIGHT logo + section chip + date.
    Identical visual style to scorecard_email._header but takes explicit
    total so the safety report's own page count appears in the email view.
    PDF page numbers come from the CSS @page counter regardless."""
    logo = _xfreight_logo_svg(width=150, height=26)
    section_chip = ""
    if section:
        section_chip = (
            f"<span style='display:inline-block;padding:2px 9px;border-radius:3px;"
            f"background:{XFREIGHT_RED};color:#fff;font-size:9px;font-weight:800;"
            f"letter-spacing:1.2px;margin-left:14px;vertical-align:middle;'>{section}</span>")
    try:
        from datetime import datetime as _dt
        dt = _dt.strptime(date_str, "%A, %B %d, %Y")
        day_part = dt.strftime("%A")
        date_part = dt.strftime("%B %d, %Y")
    except Exception:
        day_part, date_part = date_str, ""
    return (
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-bottom:4px solid {XFREIGHT_RED};padding:6px 24px 14px;'>"
        f"<tr>"
        f"<td valign='middle' style='padding:0;'>"
        f"{logo}{section_chip}"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:13px;color:{INK};"
        f"font-weight:400;margin-top:8px;'>{sub}</div>"
        f"</td>"
        f"<td align='right' valign='middle' style='padding:0;font-size:9.5px;color:{MUTE};font-weight:500;'>"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:11px;color:{INK};"
        f"font-weight:600;margin-bottom:2px;'>{day_part}</div>"
        f"<div>{date_part}</div>"
        f"<div class='pg-of' style='font-size:9px;color:{MUTE};margin-top:4px;letter-spacing:0.5px;'>"
        f"Page {pg} of {total}</div>"
        f"</td>"
        f"</tr></table>")


def _patch_pg_total(html: str, total: int) -> str:
    """Fix 'of N' in imported scorecard builder output to match safety total."""
    return re.sub(r"Page (\d+) of \d+",
                  lambda m: f"Page {m.group(1)} of {total}", html)


# ----------------------------------------------------------------------
# Metric computation
# ----------------------------------------------------------------------

def compute_metrics(samsara: dict | None) -> dict:
    """Flat headline metrics dict for bottom-line narrative and KPI tiles."""
    if not samsara:
        return {
            "events_24h": 0, "events_7d": 0, "events_30d": 0,
            "hos_24h": 0, "hos_7d": 0, "hos_mtd": 0,
            "dvir_24h": 0, "dvir_7d": 0, "dvir_open": 0,
            "coaching_24h": 0, "coaching_7d": 0, "coaching_mtd": 0,
            "fleet_score": None,
            "uncert_drivers": 0, "uncert_worst_name": None, "uncert_worst_days": 0,
            "events_trend_change": None,
        }
    w = samsara.get("windows", {}) or {}
    fleet = samsara.get("fleet", {}) or {}
    detail = samsara.get("detail", {}) or {}
    coaching_w = samsara.get("coaching", {}) or {}

    et = samsara.get("trend", {}).get("events") or ([], [])
    et_counts = et[1] if isinstance(et, tuple) and len(et) > 1 else []
    events_trend_change = None
    if len(et_counts) >= 2 and et_counts[-2]:
        events_trend_change = et_counts[-1] - et_counts[-2]

    uncert = detail.get("hos_uncert", []) or []
    worst = max(uncert, key=lambda r: r.get("days_missing", 0)) if uncert else None
    return {
        "events_24h":  int((w.get("events") or {}).get("24h", 0)),
        "events_7d":   int((w.get("events") or {}).get("7d", 0)),
        "events_30d":  int((w.get("events") or {}).get("mtd", 0)),
        "hos_24h":     int((w.get("hos") or {}).get("24h", 0)),
        "hos_7d":      int((w.get("hos") or {}).get("7d", 0)),
        "hos_mtd":     int((w.get("hos") or {}).get("mtd", 0)),
        "dvir_24h":    int((w.get("dvir") or {}).get("24h", 0)),
        "dvir_7d":     int((w.get("dvir") or {}).get("7d", 0)),
        "dvir_open":   int((w.get("dvir") or {}).get("mtd", 0)),
        "coaching_24h": int(coaching_w.get("24h", 0)),
        "coaching_7d":  int(coaching_w.get("7d", 0)),
        "coaching_mtd": int(coaching_w.get("mtd", 0)),
        "fleet_score":  fleet.get("fleet_score"),
        "uncert_drivers":    len(uncert),
        "uncert_worst_name": worst.get("driver") if worst else None,
        "uncert_worst_days": int(worst.get("days_missing", 0)) if worst else 0,
        "events_trend_change": events_trend_change,
    }


def _build_bottom_line(m: dict) -> str:
    """Auto-generated 2-3 sentence safety narrative from headline metrics."""
    sentences: list[str] = []
    fs = m.get("fleet_score")
    tc = m.get("events_trend_change")
    if fs is not None:
        s = f"Fleet safety score sits at <b>{int(round(fs))}</b>"
        if tc is not None:
            arrow = "down" if tc > 0 else ("up" if tc < 0 else "flat")
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
            f"{'s' if m['events_7d'] != 1 else ''} recorded in the last 7 days.")

    hos = m["hos_7d"]
    uc = m["uncert_drivers"]
    worst_nm = m["uncert_worst_name"]
    worst_d = m["uncert_worst_days"]
    if hos == 0 and uc == 0:
        sentences.append(
            "HOS compliance is clean — no driving-rule violations and all daily logs certified.")
    else:
        bits = []
        if hos:
            bits.append(f"<b>{hos}</b> HOS violation{'s' if hos != 1 else ''} (last 7d)")
        if uc:
            clause = (f"; <b>{worst_nm}</b> worst at <b>{worst_d}</b> day"
                      f"{'s' if worst_d != 1 else ''} behind") if worst_nm else ""
            bits.append(
                f"<b>{uc}</b> driver{'s' if uc != 1 else ''} with missing log certifications{clause}")
        sentences.append("HOS: " + ", ".join(bits) + ".")

    if m["dvir_open"] > 0:
        sentences.append(
            f"<b>{m['dvir_open']}</b> open DVIR defect"
            f"{'s' if m['dvir_open'] != 1 else ''} pending repair.")
    else:
        sentences.append("No open DVIR defects.")
    return " ".join(sentences)


# ----------------------------------------------------------------------
# Risk Watch + Action Items helpers for page 1
# ----------------------------------------------------------------------

def _risk_item(label: str, status: str, note: str = "") -> str:
    """Single TRIPPED / OK risk-watch line."""
    if status == "TRIPPED":
        pill = (f"<span style='display:inline-block;background:{BADBG};color:{BAD};"
                f"font-size:10px;font-weight:800;padding:2px 8px;border-radius:4px;"
                f"letter-spacing:0.5px;margin-left:10px;'>TRIPPED</span>")
    else:
        pill = (f"<span style='display:inline-block;background:{GOODBG};color:{GOOD};"
                f"font-size:10px;font-weight:800;padding:2px 8px;border-radius:4px;"
                f"letter-spacing:0.5px;margin-left:10px;'>OK</span>")
    note_html = (f"<div style='font-size:11px;color:{MUTE};margin-top:2px;'>{note}</div>"
                 if note else "")
    return (f"<div style='padding:8px 0;border-bottom:1px solid {LINE};'>"
            f"<span style='font-size:13px;font-weight:600;color:{INK};'>{label}</span>"
            f"{pill}{note_html}</div>")


def _action_row(urgency: str, owner: str, action: str) -> str:
    """Single action item row with urgency chip."""
    chip_bg = BAD if urgency == "URGENT" else WARN
    return (f"<div style='padding:7px 0;border-bottom:1px solid {LINE};'>"
            f"<span style='display:inline-block;background:{chip_bg};color:#fff;"
            f"font-size:10px;font-weight:800;padding:2px 7px;border-radius:4px;"
            f"margin-right:10px;'>{urgency}</span>"
            f"<span style='font-size:12.5px;color:{INK};'><b>{owner}:</b> {action}</span>"
            f"</div>")


def _dedup_dvirs(dvirs: list[dict]) -> list[dict]:
    """Deduplicate DVIR defects by unit + defect text (same defect shown once)."""
    seen: set = set()
    out: list = []
    for r in dvirs:
        key = (r.get("unit", ""), str(r.get("defect", ""))[:80])
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _build_risk_watch(m: dict, samsara: dict | None, samba, equipment) -> str:
    """Risk Watch block: TRIPPED / OK pills for each risk dimension."""
    items = []

    if m["dvir_open"] > 0:
        items.append(_risk_item("Open DVIR Defects", "TRIPPED",
                                f"{m['dvir_open']} defect{'s' if m['dvir_open'] != 1 else ''} pending repair"))
    else:
        items.append(_risk_item("Open DVIR Defects", "OK", "No open defects"))

    if m["hos_7d"] > 0:
        items.append(_risk_item("HOS Violations (7d)", "TRIPPED",
                                f"{m['hos_7d']} violation{'s' if m['hos_7d'] != 1 else ''} in last 7 days"))
    else:
        items.append(_risk_item("HOS Violations (7d)", "OK", "No violations last 7 days"))

    if m["uncert_drivers"] > 0:
        note = (f"{m['uncert_drivers']} driver{'s' if m['uncert_drivers'] != 1 else ''} "
                f"with uncertified logs")
        if m["uncert_worst_name"]:
            note += f" — worst: {m['uncert_worst_name']} ({m['uncert_worst_days']}d)"
        items.append(_risk_item("Missing Log Certifications", "TRIPPED", note))
    else:
        items.append(_risk_item("Missing Log Certifications", "OK", "All logs certified"))

    fs = m.get("fleet_score")
    if fs is not None and fs < 90:
        items.append(_risk_item("Fleet Safety Score", "TRIPPED",
                                f"Score {int(fs)} — below 90 threshold"))
    elif fs is not None:
        items.append(_risk_item("Fleet Safety Score", "OK", f"Score {int(fs)}"))
    else:
        items.append(_risk_item("Fleet Safety Score", "OK", "No score data available"))

    if samba and samba.get("high_risk"):
        n = len(samba["high_risk"])
        items.append(_risk_item("High-Risk Drivers (SambaSafety)", "TRIPPED",
                                f"{n} driver{'s' if n != 1 else ''} flagged as elevated risk"))
    else:
        items.append(_risk_item("High-Risk Drivers (SambaSafety)", "OK",
                                "No elevated-risk drivers" if samba
                                else "SambaSafety data unavailable"))

    if equipment:
        od_t = equipment.get("tractors_overdue_annual", 0) or 0
        od_r = equipment.get("trailers_overdue_annual", 0) or 0
        od = od_t + od_r
        if od > 0:
            items.append(_risk_item("Equipment Inspections (120d policy)", "TRIPPED",
                                    f"{od} unit{'s' if od != 1 else ''} past 120-day company policy"))
        else:
            items.append(_risk_item("Equipment Inspections (120d policy)", "OK",
                                    "All units current"))
    else:
        items.append(_risk_item("Equipment Inspections", "OK", "Equipment data unavailable"))

    cs = (samsara or {}).get("coaching_sessions", {}) or {}
    sp = len(cs.get("self_past_due") or [])
    mp = len(cs.get("manager_past_due") or [])
    total_od = sp + mp
    if total_od > 0:
        items.append(_risk_item("Coaching Sessions Past Due", "TRIPPED",
                                f"{total_od} overdue (self: {sp} · manager: {mp})"))
    else:
        items.append(_risk_item("Coaching Sessions Past Due", "OK", "All coaching current"))

    return (f"<div style='padding:0 24px 18px;'>"
            + "".join(items)
            + "</div>")


def _build_action_items(m: dict, samsara: dict | None, samba, equipment) -> str:
    """Action Items block derived from live data."""
    detail = (samsara or {}).get("detail", {}) or {}
    unique_dvirs = _dedup_dvirs(detail.get("dvir", []) or [])

    urgent: list[str] = []
    today_items: list[str] = []

    for r in unique_dvirs[:3]:
        unit = r.get("unit") or "?"
        defect = r.get("defect") or "unspecified defect"
        driver = r.get("driver") or "?"
        urgent.append(_action_row("URGENT", "Maintenance",
                                  f"Resolve DVIR defect on unit {unit}: {defect} (reported by {driver})"))

    if m["hos_24h"] > 0:
        urgent.append(_action_row("URGENT", "Safety",
                                  f"{m['hos_24h']} HOS violation"
                                  f"{'s' if m['hos_24h'] != 1 else ''} in last 24h — pull logs"))

    if m["uncert_worst_name"] and m["uncert_worst_days"] > 7:
        urgent.append(_action_row("URGENT", "Dispatch",
                                  f"{m['uncert_worst_name']}: {m['uncert_worst_days']}d "
                                  f"missing certifications — require log sign-off"))

    if samba and samba.get("high_risk"):
        for d in (samba["high_risk"] or [])[:2]:
            nm = d.get("name") or d.get("driver") or "Unknown"
            today_items.append(_action_row("TODAY", "Safety Mgr",
                                           f"Review SambaSafety risk flag for {nm}"))

    if equipment:
        od_t = [r for r in (equipment.get("tractors") or [])
                if isinstance(r.get("annual_days"), int) and r["annual_days"] < 0]
        od_r = [r for r in (equipment.get("trailers") or [])
                if isinstance(r.get("annual_days"), int) and r["annual_days"] < 0]
        for r in (od_t + od_r)[:3]:
            unit = r.get("unit", "?")
            days = abs(r.get("annual_days", 0))
            today_items.append(_action_row("TODAY", "Fleet Mgr",
                                           f"Schedule inspection: unit {unit} ({days}d past 120-day policy)"))

    uncert = detail.get("hos_uncert", []) or []
    for r in sorted(uncert, key=lambda x: -x.get("days_missing", 0))[:2]:
        if r.get("days_missing", 0) > 3:
            today_items.append(_action_row("TODAY", "Dispatch",
                                           f"{r.get('driver', '?')}: {r.get('days_missing', 0)}d "
                                           f"missing log certifications"))

    if not urgent and not today_items:
        return (f"<div style='padding:0 24px 18px;color:{MUTE};font-size:13px;'>"
                f"No action items — all risk indicators within normal thresholds.</div>")

    html = "<div style='padding:0 24px 18px;'>"
    if urgent:
        html += (f"<div style='font-size:10px;letter-spacing:1.5px;text-transform:uppercase;"
                 f"color:{BAD};font-weight:700;margin:12px 0 6px;'>URGENT</div>"
                 + "".join(urgent))
    if today_items:
        html += (f"<div style='font-size:10px;letter-spacing:1.5px;text-transform:uppercase;"
                 f"color:{WARN};font-weight:700;margin:16px 0 6px;'>TODAY</div>"
                 + "".join(today_items))
    html += "</div>"
    return html


# ----------------------------------------------------------------------
# ALL CLEAR empty-state helper
# ----------------------------------------------------------------------

def _all_clear_row(msg: str, span: int = 6) -> str:
    """Green ALL CLEAR callout used as the empty-state row inside a _table()."""
    return (
        f"<tr><td colspan='{span}' style='padding:10px 4px;'>"
        f"<div style='border-left:4px solid {GOOD};background:{GOODBG};"
        f"border-radius:6px;padding:10px 14px;'>"
        f"<div style='font-size:10px;letter-spacing:1.5px;font-weight:800;"
        f"color:{GOOD};margin-bottom:4px;'>&#10003; ALL CLEAR</div>"
        f"<div style='font-size:12.5px;color:{INK};'>{msg}</div>"
        f"</div></td></tr>"
    )


# ----------------------------------------------------------------------
# Page builders
# ----------------------------------------------------------------------

def build_page_overview(samsara: dict | None, metrics: dict, pg: int,
                        total: int, date_str: str, samba, equipment) -> str:
    """Page 1: Overview — Bottom Line · Urgent · Risk Watch · Action Items."""
    header = _sc_header(
        "Safety &amp; Compliance · Daily Overview", pg, total, date_str, section="EVENTS")
    bl = _build_bottom_line(metrics)

    bottom_line_block = (
        f"<div style='padding:18px 24px 12px;'>"
        f"<div style='font-size:10px;letter-spacing:2px;color:{MUTE};"
        f"font-weight:700;margin-bottom:8px;'>BOTTOM LINE</div>"
        f"<div style='{FONT_SERIF}font-size:14px;line-height:1.6;color:{INK};"
        f"border-left:3px solid {XFREIGHT_RED};padding-left:14px;'>{bl}</div>"
        f"</div>"
    )

    # URGENT snapshot
    detail = (samsara or {}).get("detail", {}) or {}
    unique_dvirs = _dedup_dvirs(detail.get("dvir", []) or [])
    urgent_items = []
    for r in unique_dvirs[:5]:
        unit = r.get("unit") or "?"
        defect = r.get("defect") or "unspecified defect"
        driver = r.get("driver") or "?"
        urgent_items.append(
            f"<li style='margin-bottom:6px;'>DVIR defect on unit <b>{unit}</b>: "
            f"{defect} (reported by {driver})</li>")
    if metrics["hos_24h"] > 0:
        urgent_items.append(
            f"<li style='margin-bottom:6px;'>{metrics['hos_24h']} HOS violation"
            f"{'s' if metrics['hos_24h'] != 1 else ''} in the last 24h — pull logs</li>")
    if metrics["uncert_worst_name"] and metrics["uncert_worst_days"] > 7:
        urgent_items.append(
            f"<li style='margin-bottom:6px;'>{metrics['uncert_worst_name']}: "
            f"{metrics['uncert_worst_days']}d missing log certifications</li>")

    if urgent_items:
        urgent_block = (
            f"<div style='padding:0 24px 12px;'>"
            f"<div style='font-size:10px;letter-spacing:2px;color:{BAD};"
            f"font-weight:700;margin-bottom:8px;'>URGENT</div>"
            f"<ul style='margin:0;padding-left:20px;font-size:13px;color:{INK};line-height:1.6;'>"
            + "".join(urgent_items)
            + "</ul></div>"
        )
    else:
        urgent_block = (
            f"<div style='padding:0 24px 12px;color:{GOOD};font-size:13px;'>"
            f"No urgent items — all risk indicators within normal range.</div>")

    rw_title = (
        f"<div style='padding:12px 24px 4px;'>"
        f"<div style='{FONT_SERIF}font-size:17px;font-weight:400;color:{INK};"
        f"letter-spacing:-0.3px;'>Risk Watch</div>"
        f"<div style='width:36px;height:2px;background:{INK};margin-top:6px;'></div>"
        f"</div>"
    )

    ai_title = (
        f"<div style='padding:18px 24px 4px;'>"
        f"<div style='{FONT_SERIF}font-size:17px;font-weight:400;color:{INK};"
        f"letter-spacing:-0.3px;'>Action Items</div>"
        f"<div style='width:36px;height:2px;background:{INK};margin-top:6px;'></div>"
        f"</div>"
    )

    return (header
            + bottom_line_block
            + urgent_block
            + rw_title
            + _build_risk_watch(metrics, samsara, samba, equipment)
            + ai_title
            + _build_action_items(metrics, samsara, samba, equipment))


def _extra_trends(samsara: dict | None,
                  samsara_sheets: dict | None) -> dict:
    """Compute trend data that isn't in samsara["trend"]:
      coached   — monthly count of coached events (state="coached")
      dismissed — monthly count of dismissed events
      dvir_pct  — monthly DVIR defect resolution % (resolved/total*100)
      speed_pct — fleet-avg % of drive time over posted limit by month
    Returns a dict with keys above, each value is (months_list, counts_list).
    """
    out: dict = {}

    # Coached + dismissed monthly counts from coached_events list
    coached_rows = (samsara or {}).get("coached_events") or []
    for state_key, state_val in [("coached", "coached"), ("dismissed", "dismissed")]:
        rows = [r for r in coached_rows if r.get("state") == state_val]
        if not rows:
            months = [f"{m[0]}-{m[1]:02d}" for m in _last_6_months()]
            out[state_key] = (months, [0] * len(months))
            continue
        dts = []
        for r in rows:
            raw = r.get("coached_at") or r.get("event_date") or ""
            if raw and raw != "&mdash;":
                try:
                    dt = pd.to_datetime(str(raw)[:16], errors="coerce")
                    if pd.notna(dt):
                        dts.append(dt)
                except Exception:
                    pass
        if dts:
            out[state_key] = _monthly_counts(pd.Series(dts))
        else:
            months = [f"{m[0]}-{m[1]:02d}" for m in _last_6_months()]
            out[state_key] = (months, [0] * len(months))

    # DVIR compliance % per month + last-7d snapshot
    # Sheet columns: "Reported" (date), "Resolved" (bool) — see samsara_main.build_dvir_defects
    dvir_df = (samsara_sheets or {}).get("DVIR_Defects")
    fallback_months = [f"{m[0]}-{m[1]:02d}" for m in _last_6_months()]
    if dvir_df is not None and not dvir_df.empty:
        date_col = _find_col(dvir_df, ["reported", "createdat", "createdatms",
                                        "inspection date", "date"])
        res_col = _find_col(dvir_df, ["resolved"])
        if date_col and res_col:
            df = dvir_df[[date_col, res_col]].copy()
            df["_dt"] = pd.to_datetime(df[date_col], errors="coerce", utc=True)
            df["_dt"] = df["_dt"].dt.tz_localize(None)
            df["_res"] = df[res_col].apply(
                lambda v: (v is True) or
                (isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0) or
                (isinstance(v, str) and v.strip().lower() in ("true", "1", "yes")))
            # Monthly trend
            months6 = _last_6_months()
            labels, pcts = [], []
            for yr, mo in months6:
                mask = (df["_dt"].dt.year == yr) & (df["_dt"].dt.month == mo)
                tot = int(mask.sum())
                res = int(df.loc[mask, "_res"].sum()) if tot > 0 else 0
                labels.append(f"{yr}-{mo:02d}")
                pcts.append(round(res / tot * 100) if tot > 0 else 0)
            out["dvir_pct"] = (labels, pcts)
            # Last-7d snapshot for the summary tile
            cutoff_7d = pd.Timestamp.now() - pd.Timedelta(days=7)
            mask_7d = df["_dt"] >= cutoff_7d
            tot_7d = int(mask_7d.sum())
            res_7d = int(df.loc[mask_7d, "_res"].sum()) if tot_7d > 0 else 0
            out["dvir_comp_7d"] = round(res_7d / tot_7d * 100) if tot_7d > 0 else None
        else:
            out["dvir_pct"] = (fallback_months, [0] * len(fallback_months))
            out["dvir_comp_7d"] = None
    else:
        out["dvir_pct"] = (fallback_months, [0] * len(fallback_months))
        out["dvir_comp_7d"] = None

    # Speed over limit — fleet avg % drive time per driver, averaged by month
    scores_all = ((samsara or {}).get("fleet") or {}).get("scores_all") or []
    speed_vals = [r.get("speed_pct") for r in scores_all if _isnum(r.get("speed_pct"))]
    if speed_vals:
        fleet_avg = sum(speed_vals) / len(speed_vals)
        months6 = _last_6_months()
        labels = [f"{yr}-{mo:02d}" for yr, mo in months6]
        pcts = [round(fleet_avg, 2)] * len(labels)
        out["speed_pct"] = (labels, pcts)
    else:
        months = [f"{m[0]}-{m[1]:02d}" for m in _last_6_months()]
        out["speed_pct"] = (months, [0.0] * len(months))

    return out


def _section_label(text: str) -> str:
    """Thin section divider matching the June 15 style (serif label + 2px rule)."""
    return (f"<div style='padding:14px 18px 4px;'>"
            f"<div style='font-size:12px;font-weight:600;color:{INK};"
            f"letter-spacing:0.2px;'>{text}</div>"
            f"<div style='width:100%;height:2px;background:{LINE};margin-top:6px;'></div>"
            f"</div>")


def build_page_metrics(samsara: dict | None, metrics: dict, pg: int,
                       total: int, date_str: str,
                       samsara_sheets: dict | None = None) -> str:
    """Page 2: Safety Metrics — multi-window KPI tiles + summary boxes + bar charts."""
    header = _sc_header(
        "Safety &amp; Compliance · Safety Metrics", pg, total, date_str, section="EVENTS")

    w = (samsara or {}).get("windows", {}) or {}
    trend = (samsara or {}).get("trend", {}) or {}

    def _swv(domain: str, window: str) -> str:
        return num((w.get(domain) or {}).get(window, 0))

    # Compute extra trends (coached, dismissed, dvir_pct, speed_pct)
    xt = _extra_trends(samsara, samsara_sheets)

    def _tc(key: str):
        t = trend.get(key) or xt.get(key)
        if isinstance(t, (list, tuple)) and len(t) == 2:
            return list(t[0]), list(t[1])
        return [], []

    ev_m, ev_c = _tc("events")
    hos_m, hos_c = _tc("hos")
    dvir_m, dvir_c = _tc("dvir")
    coached_m, coached_c = _tc("coached")
    dismissed_m, dismissed_c = _tc("dismissed")
    dvir_pct_m, dvir_pct_c = _tc("dvir_pct")
    speed_m, speed_c = _tc("speed_pct")

    # ── Current period: 4 multi-window KPI tiles (24h / 7d / MTD) ──────────
    tiles_row = (
        f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        + _mwtile("Safety Events",
                  _swv("events", "24h"), _swv("events", "7d"), _swv("events", "mtd"), "warn")
        + _mwtile("HOS Violations",
                  _swv("hos", "24h"), _swv("hos", "7d"), _swv("hos", "mtd"), "warn")
        + _mwtile("Open DVIR Defects",
                  _swv("dvir", "24h"), _swv("dvir", "7d"), _swv("dvir", "mtd"), "warn")
        + _mwtile("Coaching Due",
                  num(metrics["coaching_24h"]),
                  num(metrics["coaching_7d"]),
                  num(metrics["coaching_mtd"]), "mute")
        + "</tr></table>"
    )

    # ── 6-month trend — row 1: 4 summary stat tiles ─────────────────────────
    fs = metrics.get("fleet_score")
    score_txt = f"{int(round(fs))}" if fs is not None else "n/a"
    score_kind = "bad" if (fs is not None and fs < 90) else "good" if fs is not None else "mute"
    uc = metrics["uncert_drivers"]
    uc_sub = (f"Worst: {metrics['uncert_worst_name']} ({metrics['uncert_worst_days']}d)"
              if metrics.get("uncert_worst_name") else "All daily logs certified")

    # DVIR compliance % — resolved / total · last 7d (from DVIR_Defects sheet)
    dvir_comp_7d = xt.get("dvir_comp_7d")
    if dvir_comp_7d is not None:
        dvir_comp_pct = dvir_comp_7d
        dvir_comp_txt = f"{dvir_comp_pct}%"
    elif dvir_pct_c:
        dvir_comp_pct = dvir_pct_c[-1]
        dvir_comp_txt = f"{dvir_comp_pct}%"
    else:
        dvir_comp_pct = None
        dvir_comp_txt = "n/a"
    dvir_comp_kind = ("bad" if (dvir_comp_pct is not None and dvir_comp_pct < 80)
                      else ("warn" if (dvir_comp_pct is not None and dvir_comp_pct < 95)
                            else "good"))

    summary_row = (
        f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        + _tile("Fleet avg safety score", score_txt,
                _pill("Samsara · 0–100 · higher is safer", score_kind), width="25%")
        + _tile("DVIR open defects", num(metrics["dvir_open"]),
                _pill("pending mechanic repair",
                      "warn" if metrics["dvir_open"] else "good"), width="25%")
        + _tile("Missing log certs", num(uc),
                _pill(uc_sub, "warn" if uc else "good", nowrap=False), width="25%")
        + _tile("DVIR compliance", dvir_comp_txt,
                _pill("completed / required · last 7d", dvir_comp_kind), width="25%")
        + "</tr></table>"
    )

    # ── 6-month trend — row 2: 4 bar chart tiles ────────────────────────────
    charts_row2 = (
        f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        + _bar_chart("HOS Violations / mo", hos_m, hos_c, "driving-rule breaches")
        + _bar_chart("DVIR Defects / mo", dvir_m, dvir_c, "reported/mo · *MTD")
        + _bar_chart("Coached Events / mo", coached_m, coached_c,
                     "manager-reviewed / mo · *MTD")
        + _bar_chart("DVIR Compliance %", dvir_pct_m, dvir_pct_c,
                     "% completed / required · *MTD",
                     fmt=lambda v: f"{int(v)}%")
        + "</tr></table>"
    )

    # ── 6-month trend — row 3: 3 bar chart tiles ────────────────────────────
    charts_row3 = (
        f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        + _bar_chart("Safety Events / mo", ev_m, ev_c, "reported/mo · *MTD")
        + _bar_chart("Dismissed Events / mo", dismissed_m, dismissed_c,
                     "no-action-needed / mo · *MTD")
        + _bar_chart("Speed Over Limit", speed_m, speed_c,
                     "% drive time · fleet avg",
                     fmt=lambda v: f"{v:.2f}%")
        + "</tr></table>"
    )

    return (header
            + _section_label("Current period — 24h / 7d / month-to-date")
            + f"<div style='padding:4px 18px 0;'>{tiles_row}</div>"
            + _section_label("6-month trend — rolling window · * = month-to-date")
            + f"<div style='padding:4px 18px 4px;'>{summary_row}</div>"
            + f"<div style='padding:4px 18px 4px;'>{charts_row2}</div>"
            + f"<div style='padding:4px 18px 18px;'>{charts_row3}</div>")


def build_page_events_hos(samsara: dict | None, pg: int,
                           total: int, date_str: str) -> str:
    """Page 3: Safety Events + HOS Violations + Missing Log Certifications."""
    header = _sc_header(
        "Safety Events &amp; HOS Compliance", pg, total, date_str, section="EVENTS")
    detail = (samsara or {}).get("detail", {}) or {}

    # Safety events last 7d
    evs = detail.get("events", []) or []
    ev_rows = "".join(
        _tr(
            [r.get("driver name", r.get("driver", "&mdash;")),
             r.get("unit", r.get("vehicle", "&mdash;")),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("event type", "&mdash;"),
             r.get("severity", "&mdash;"),
             r.get("status", r.get("coaching", "&mdash;"))],
            ["left"] * 6,
            [None, None, None, None,
             ("bad" if str(r.get("severity", "")).lower() == "high" else "warn"), None])
        for r in evs
    ) or _all_clear_row(
        "No safety events in the last 7 days — all drivers operating within safety thresholds.",
        span=6)

    # HOS violations last 7d
    hos = detail.get("hos", []) or []
    hos_rows = "".join(
        _tr(
            [r.get("driver name", r.get("driver", "&mdash;")),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("violation type", r.get("type", "&mdash;")),
             r.get("status", "&mdash;")],
            ["left"] * 4,
            [None, None, "bad", None])
        for r in hos
    ) or _all_clear_row(
        "No HOS violations in the last 7 days — all drivers operating within hours of service.",
        span=4)

    # Missing log certifications
    uncert = detail.get("hos_uncert", []) or []
    uc_rows = "".join(
        _tr(
            [r.get("driver", "&mdash;"),
             str(r.get("days_missing", "")),
             r.get("span", "&mdash;"),
             "Not certified"],
            ["left", "right", "left", "left"],
            [None, "bad", None, "bad"])
        for r in uncert
    ) or _all_clear_row(
        "Every driver working today has certified their prior-day logs"
        " — no audit risk from missed start-of-shift certifications.",
        span=4)

    return (header
            + f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            + _section("Safety events — last 7 days")
            + _table(["Driver", "Unit", "Reported", "Event type", "Severity", "Status"],
                     ["left"] * 6, ev_rows)
            + _section("HOS violations — last 7 days (driving-rule breaches)")
            + _table(["Driver", "Reported", "Violation type", "Status"],
                     ["left"] * 4, hos_rows)
            + _section("Missing log certifications")
            + _table(["Driver", "Days missing", "Date range", "Status"],
                     ["left", "right", "left", "left"], uc_rows)
            + "</table>"
            + f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;"
            f"border-top:1px solid {LINE};margin-top:14px;'>"
            f"Source: Samsara SafetyEvents, HOS_Violations, HOS_DailyLogs (7-day window). "
            f"HOS = driving-rule breaches only (form-and-manner excluded). "
            f"Missing certifications = drivers who have not e-signed prior-day logs.</div>")


def build_page_dvir_defects(samsara: dict | None, pg: int,
                             total: int, date_str: str) -> str:
    """Page 4: DVIR Defects — all open, deduplicated by unit + defect."""
    header = _sc_header(
        "DVIR Defects — All Open &amp; Unresolved", pg, total, date_str, section="EVENTS")
    detail = (samsara or {}).get("detail", {}) or {}
    unique = _dedup_dvirs(detail.get("dvir", []) or [])

    dvir_rows = "".join(
        _tr(
            [r.get("unit", "&mdash;"),
             r.get("driver", "&mdash;"),
             (r.get("date", "") + " " + r.get("time", "")).strip() or "&mdash;",
             r.get("defect", "&mdash;"),
             r.get("defect type", "&mdash;"),
             "Open"],
            ["left"] * 6,
            [None, None, None, None, None, "bad"])
        for r in unique
    ) or _all_clear_row(
        "No open DVIR defects — all reported defects have been resolved.",
        span=6)

    return (header
            + f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            + _section(f"Open DVIR defects — {len(unique)} unresolved")
            + _table(["Unit", "Driver", "Reported", "Defect", "Type", "Status"],
                     ["left"] * 6, dvir_rows)
            + "</table>"
            + f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;"
            f"border-top:1px solid {LINE};margin-top:14px;'>"
            f"Source: Samsara DVIR_Defects sheet (Resolved=False). "
            f"Deduplicated by unit + defect description — same defect appears once. "
            f"Each open defect requires mechanic sign-off before the unit re-inspects clean.</div>")


def build_page_speed(samsara: dict | None, pg: int,
                     total: int, date_str: str) -> str:
    """Page 7: Speed over Posted Limit — per-driver 6-month safety score data."""
    header = _sc_header(
        "Speed Over Posted Limit — Per-Driver", pg, total, date_str, section="SAFETY")
    fleet = (samsara or {}).get("fleet", {}) or {}
    scores_all = fleet.get("scores_all") or []
    speeders = fleet.get("speeders") or []

    def _spd_cell(r: dict) -> str:
        pct_v = r.get("speed_pct")
        mins = r.get("speed_min")
        if _isnum(pct_v):
            return f"{pct_v:.1f}%"
        if _isnum(mins):
            return f"{mins} min"
        return "&ndash;"

    def _spd_kind(r: dict) -> str | None:
        pct_v = r.get("speed_pct")
        if _isnum(pct_v):
            if pct_v == 0:
                return None
            return "bad" if pct_v >= 5 else ("warn" if pct_v >= 1 else None)
        mins = r.get("speed_min")
        if not _isnum(mins) or mins == 0:
            return None
        return "bad" if mins >= 60 else "warn"

    def _score_kind(r: dict) -> str | None:
        s = r.get("score")
        if s is None:
            return None
        return "bad" if s < 90 else ("warn" if s < 100 else "good")

    _any_pct = any(_isnum(r.get("speed_pct")) for r in scores_all)
    spd_hdr = "Speed Over Limit (% drive time)" if _any_pct else "Speed Over Limit (min)"

    score_rows = "".join(
        _tr(
            [r.get("driver", "&mdash;"),
             str(r.get("score") or "&ndash;"),
             _spd_cell(r),
             str(r.get("harsh_accel") or "&ndash;"),
             str(r.get("harsh_brake") or "&ndash;"),
             str(r.get("crashes") or "&ndash;")],
            ["left", "right", "right", "right", "right", "right"],
            [None, _score_kind(r), _spd_kind(r),
             ("bad" if (r.get("harsh_accel") or 0) > 0 else None),
             ("bad" if (r.get("harsh_brake") or 0) > 0 else None),
             ("bad" if (r.get("crashes") or 0) > 0 else None)])
        for r in scores_all
    ) or (f"<tr><td colspan='6' style='padding:14px 8px;color:{MUTE};font-size:12px;'>"
          f"No driver safety score data available.</td></tr>")

    sp_rows = "".join(
        _tr([r.get("driver", "&mdash;"), str(r.get("count", 0))],
            ["left", "right"], [None, "bad"])
        for r in speeders
    ) or (f"<tr><td colspan='2' style='padding:14px 8px;color:{MUTE};font-size:12px;'>"
          f"No speeding events in last 7 days.</td></tr>")

    return (header
            + f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            + _section("Top speeders — safety event stream · last 7 days")
            + _table(["Driver", "Speed events"], ["left", "right"], sp_rows)
            + _section(f"Driver safety scores — all {len(scores_all)} drivers · 6-month window")
            + _table(["Driver", "Score", spd_hdr, "Harsh accel", "Harsh brake", "Crashes"],
                     ["left", "right", "right", "right", "right", "right"], score_rows)
            + "</table>"
            + f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;"
            f"border-top:1px solid {LINE};margin-top:14px;'>"
            f"Source: Samsara Driver Safety Scores (6-month window). Speed over limit "
            f"= % of drive time (or minutes when % unavailable) spent above posted limit. "
            f"≥10% drive time = red · ≥1% = amber · 0% = neutral. "
            f"Top speeders: Samsara SafetyEvents stream, last 7 days.</div>")


def build_page_footnote(pg: int, total: int, date_str: str) -> str:
    """Page 8: Methodology & data-source footnote."""
    header = _sc_header(
        "Methodology &amp; Data Sources", pg, total, date_str, section="SAFETY")
    rows = [
        ("Safety Events", "Samsara SafetyEvents sheet. 24h / 7d / MTD windows. All event types included (harsh braking, harsh accel, forward collision, speeding, lane departure, etc.)."),
        ("HOS Violations", "Samsara HOS_Violations sheet. Driving-rule violations only (11h / 14h / 70h / restart rules). Form-and-manner violations excluded. Missing certifications from HOS_DailyLogs."),
        ("DVIR Defects", "Samsara DVIR_Defects sheet (Resolved=False). Deduplicated by unit + defect description. Each open defect requires mechanic sign-off before the unit re-inspects clean."),
        ("Driver Safety Scores", "Samsara Driver Safety Score API (6-month window). Score 0–100 (higher = safer). Components: harsh accel/brake/turn, speed over limit, crashes."),
        ("Equipment Inspections", "Alvys Pipeline.xlsx Trucks + Trailers sheets. AnnualInspectionDue = federal 365-day standard; InspectionExpirationDate = XFreight 120-day company policy. Current mileage from Samsara OBD odometer (VehicleStats.obdOdometerMeters)."),
        ("Driver Compliance", "SambaSafety_Master.xlsx — driver license status, CDL validity, MVR alerts, risk scores. DOT medical card expiration from Alvys Drivers sheet."),
        ("FMCSA CSA Scorecard", "SambaSafety CSA2010 Preview Scorecard CSV. BASIC percentile scores for X-Trux, Inc. Intervention thresholds: Unsafe Driving + Crash Indicator ≥65th pct; all other BASICs ≥80th pct."),
        ("Coached Events", "Samsara SafetyEvents coachingState column (190-day window). Coached-at timestamp from /fleet/safety-events/audit-logs/feed. Coach name: not available (Samsara API limitation for our tenant)."),
    ]
    tbody = "".join(
        f"<tr><td style='padding:10px 8px;font-size:12px;font-weight:700;color:{INK};"
        f"border-bottom:1px solid {LINE};vertical-align:top;width:28%;'>{label}</td>"
        f"<td style='padding:10px 8px;font-size:12px;color:{MUTE};"
        f"border-bottom:1px solid {LINE};'>{desc}</td></tr>"
        for label, desc in rows
    )
    return (header
            + f"<div style='padding:18px 24px;'>"
            f"<div style='{FONT_SERIF}font-size:17px;font-weight:400;color:{INK};margin-bottom:10px;'>"
            f"Data Sources &amp; Calculations</div>"
            f"<div style='width:36px;height:2px;background:{INK};margin-bottom:16px;'></div>"
            f"<table width='100%' cellpadding='0' cellspacing='0'>{tbody}</table></div>")


def build_page_knowledge_base(pg: int, total: int, date_str: str) -> str:
    """Last page: Knowledge Base & Playbooks — sources and schedule."""
    header = _sc_header(
        "Knowledge Base &amp; Playbooks", pg, total, date_str, section="SAFETY")
    rows = [
        ("Samsara Master.xlsx",
         "OneDrive: Samsara/Samsara Master.xlsx. Refreshed daily at 3am CT via samsara_refresh.yml. "
         "Contains SafetyEvents, HOS_Violations, HOS_DailyLogs, DVIR_Defects, VehicleStats, Trips, "
         "DriverScores, CoachingSessions, and more."),
        ("SambaSafety Master.xlsx",
         "OneDrive: SambaSafety/SambaSafety_Master.xlsx. Updated when CSV exports are uploaded via "
         "sambasafety_refresh.yml. Contains driver Risk Index, license status, violations, and "
         "CSA BASIC percentile scorecard for X-Trux Inc."),
        ("Alvys Pipeline.xlsx",
         "OneDrive: Alvys Pipeline.xlsx. Refreshed by the Alvys pipeline workflow. Contains Trucks, "
         "Trailers, and Drivers sheets with inspection dates, registration expiry, DOT medical cards, "
         "and CDL info."),
        ("DOT Inspection Policy",
         "XFreight company policy: 120-day inspection cycle tracked via InspectionExpirationDate in Alvys. "
         "Federal DOT standard is 365 days — a unit needs to be 245+ days past XFreight policy to "
         "hit the federal out-of-service threshold. All DOT inspections covered by X-Trux Inc."),
        ("Report Schedule",
         "Sent daily at 5am CT via safety_compliance_email.yml (GitHub Actions). "
         "Push to that workflow file triggers an on-demand resend. "
         "Idempotency: one send per Central calendar day unless SAFETY_SKIP_IDEMPOTENCY=1."),
        ("Executive Brief",
         "The daily Executive Brief (scorecard_email.yml) covers P&L, AR, fleet operations, and "
         "a safety summary. This Safety & Compliance Report is the safety-only deep-dive "
         "— same Samsara + SambaSafety data, safety-first page ordering."),
    ]
    tbody = "".join(
        f"<tr><td style='padding:10px 8px;font-size:12px;font-weight:700;color:{INK};"
        f"border-bottom:1px solid {LINE};vertical-align:top;width:28%;'>{label}</td>"
        f"<td style='padding:10px 8px;font-size:12px;color:{MUTE};"
        f"border-bottom:1px solid {LINE};'>{desc}</td></tr>"
        for label, desc in rows
    )
    return (header
            + f"<div style='padding:18px 24px;'>"
            f"<div style='{FONT_SERIF}font-size:17px;font-weight:400;color:{INK};margin-bottom:10px;'>"
            f"KNOWLEDGE BASE &amp; PLAYBOOKS</div>"
            f"<div style='width:36px;height:2px;background:{INK};margin-bottom:16px;'></div>"
            f"<table width='100%' cellpadding='0' cellspacing='0'>{tbody}</table></div>")


# ----------------------------------------------------------------------
# Report assembly
# ----------------------------------------------------------------------

def _build_html_report(samsara: dict | None, samsara_sheets: dict | None,
                       samba, csa, equipment, alvys_drivers,
                       date_str: str) -> str:
    """Assemble the full safety report HTML matching the June 15 2026 format.

    Page order:
      1  Overview               (custom)
      2  Safety Metrics         (custom)
      3  Safety Events & HOS    (custom)
      4  DVIR Defects           (custom)
      5-6 Driver Compliance     (build_page9 from scorecard_email)
      7  Speed over Limit       (custom)
      8  Methodology            (custom)
      9-10 Tractor Inspections  (build_page_equipment kind=tractors)
      11-12 Trailer Inspections (build_page_equipment kind=trailers)
      13 FMCSA CSA Scorecard    (build_csa_scorecard_page)
      14 Driver Safety Scores   (build_page2b)
      15+ Coached Events        (build_page_coached)
      Last Knowledge Base       (custom)

    PDF page numbers come from the CSS @page counter(pages) automatically.
    The 'total' value in _sc_header is approximate for the email screen view.
    """
    metrics = compute_metrics(samsara)
    total = 22  # approximate for the email screen header

    pages: list[str] = []

    # 1 — Overview
    pages.append(build_page_overview(
        samsara, metrics, 1, total, date_str, samba, equipment))

    # 2 — Safety Metrics
    pages.append(build_page_metrics(samsara, metrics, 2, total, date_str,
                                    samsara_sheets=samsara_sheets))

    # 3 — Safety Events & HOS
    pages.append(build_page_events_hos(samsara, 3, total, date_str))

    # 4 — DVIR Defects
    pages.append(build_page_dvir_defects(samsara, 4, total, date_str))

    # 5-6 — Driver Compliance (scorecard builder; pg=2 in its header,
    # but the PDF shows correct position via CSS counter)
    p9 = build_page9(samba, date_str, alvys_drivers)
    pages.append(_patch_pg_total(p9, total))

    # 7 — Speed over Posted Limit
    pages.append(build_page_speed(samsara, 7, total, date_str))

    # 8 — Methodology Footnote
    pages.append(build_page_footnote(8, total, date_str))

    # 9-10 — Tractor Inspections (build_page_equipment accepts pg param)
    if equipment:
        tractor_html = build_page_equipment(equipment, date_str, kind="tractors", pg=9)
        pages.append(_patch_pg_total(tractor_html, total))
        trailer_html = build_page_equipment(equipment, date_str, kind="trailers", pg=11)
        pages.append(_patch_pg_total(trailer_html, total))
    else:
        pages.append(
            _sc_header("Equipment Compliance — Tractor Inspections",
                       9, total, date_str, "SAFETY")
            + _brief("Alvys Pipeline.xlsx not found on OneDrive — "
                     "equipment inspection data unavailable this run.", "mute"))
        pages.append(
            _sc_header("Equipment Compliance — Trailer Inspections",
                       11, total, date_str, "SAFETY")
            + _brief("Alvys Pipeline.xlsx not found on OneDrive — "
                     "equipment inspection data unavailable this run.", "mute"))

    # 13 — FMCSA CSA Scorecard
    csa_html = build_csa_scorecard_page(csa, date_str)
    pages.append(_patch_pg_total(csa_html, total))

    # 14 — Driver Safety Scores (build_page2b accepts pg param)
    scores_html = build_page2b(samsara, date_str, pg=14)
    pages.append(_patch_pg_total(scores_html, total))

    # 15+ — Coached Events (scorecard builder; pg=14 in its header, PDF correct)
    coached_html = build_page_coached(samsara, date_str)
    pages.append(_patch_pg_total(coached_html, total))

    # Last — Knowledge Base & Playbooks
    pages.append(build_page_knowledge_base(len(pages) + 1, total, date_str))

    pb = "<div class='page-break' style='page-break-after:always;break-after:page;height:0;'></div>"
    body = pb.join(pages)

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        f"body{{margin:0;background:#fff;"
        f"font-family:-apple-system,'Helvetica Neue',Helvetica,Arial,sans-serif;"
        f"color:{INK};}}"
        ".page-break{page-break-after:always;break-after:page;height:0;}"
        "@page{size:letter;margin:0.45in 0.35in 0.55in;"
        f"@bottom-right{{content:'Page ' counter(page) ' of ' counter(pages);"
        f"font-family:Georgia,'Times New Roman',serif;"
        f"font-size:9px;color:{MUTE};}}}}"
        "@media print{.pg-of{display:none !important;}}"
        ".pg-of{display:inline;}"
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


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

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

    today = _today_chi()
    skip = os.environ.get("SAFETY_SKIP_IDEMPOTENCY", "").strip() == "1"
    if not skip and _marker_exists(tok, upn, today):
        log.info("Marker present for %s — already sent today. Skipping.", today)
        return 0

    date_str = _today_label()
    missing: list[str] = []

    # Samsara Master (required)
    samsara_path = os.environ.get("SAMSARA_ONEDRIVE_PATH", "Samsara/Samsara Master.xlsx")
    samsara_sheets = _safe_read(tok, upn, samsara_path, missing, "Samsara Master")
    if samsara_sheets is None:
        log.error("Could not read Samsara Master from OneDrive — aborting.")
        return 1
    samsara = compute_samsara(samsara_sheets)

    # SambaSafety Master (optional — graceful fallback if missing)
    samba_path = os.environ.get("SCORECARD_SAMBASAFETY_PATH",
                                "SambaSafety/SambaSafety_Master.xlsx")
    samba_sheets = _safe_read(tok, upn, samba_path, [], "SambaSafety Master")
    if samba_sheets is None:
        log.warning("SambaSafety Master not found — driver compliance page will show limited data.")
    samba = compute_sambasafety(samba_sheets) if samba_sheets else None
    csa = compute_csa_scorecard(samba_sheets) if samba_sheets else None

    # Alvys Pipeline (optional — graceful fallback if missing)
    pipeline_path = os.environ.get("ALVYS_PIPELINE_PATH", "Alvys Pipeline.xlsx")
    pipeline_sheets = _safe_read(tok, upn, pipeline_path, [], "Alvys Pipeline")
    equipment = None
    alvys_drivers = None
    if pipeline_sheets:
        equipment = compute_alvys_equipment(pipeline_sheets,
                                            samsara_sheets=samsara_sheets)
        alvys_drivers = compute_alvys_drivers(pipeline_sheets)
    else:
        log.warning("Alvys Pipeline.xlsx not found — equipment pages will show placeholder.")

    html = _build_html_report(
        samsara, samsara_sheets, samba, csa, equipment, alvys_drivers, date_str)
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
