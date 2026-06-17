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
import json
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
    compute_inspection_compliance, compute_speed_comment,
    # Page builders reused from the executive brief
    build_page9, build_page_equipment, build_page_coached,
    build_page2, build_page2b, build_csa_scorecard_page,
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


_SCORES_NAME_TPL = "scores-{}.json"


def _read_prev_scores(tok: str, upn: str, d: datetime.date) -> dict:
    """Return {driver: score} from the score file for date d, or {} if absent."""
    path = f"{_MARKER_FOLDER}/{_SCORES_NAME_TPL.format(d.isoformat())}"
    try:
        data = download_file(tok, upn, path)
        return json.loads(data).get("scores", {})
    except Exception:
        return {}


def _write_scores(tok: str, upn: str, d: datetime.date, scores_all: list) -> None:
    """Persist per-driver scores for trend comparison on the next run."""
    scores = {r["driver"]: r["score"]
              for r in scores_all if r.get("driver") and r.get("score") is not None}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump({"scores": scores}, tf, indent=2)
        tmp = Path(tf.name)
    ensure_folder(tok, upn, _MARKER_FOLDER)
    upload_file(tok, upn,
                folder_path=_MARKER_FOLDER,
                filename=_SCORES_NAME_TPL.format(d.isoformat()),
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
        "dvir_open":   len(_dedup_dvirs(detail.get("dvir", []) or [])),
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

_SAFETY_DATE_COLS = ["time", "Event Time", "Time", "occurredAtTime", "startTime", "Start Time"]


def _events_in_window(samsara_sheets: dict | None, hours: int) -> int:
    """Count SafetyEvents rows recorded in the last `hours` hours."""
    if not samsara_sheets:
        return 0
    df = samsara_sheets.get("SafetyEvents")
    if df is None or df.empty:
        return 0
    dc = _find_col(df, _SAFETY_DATE_COLS)
    if not dc:
        return 0
    dates = _to_naive_dt(df[dc])
    cutoff = pd.Timestamp.now() - pd.Timedelta(hours=hours)
    return int((dates >= cutoff).sum())

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
                                f"Score {int(round(fs))} — below 90 threshold"))
    elif fs is not None:
        items.append(_risk_item("Fleet Safety Score", "OK", f"Score {int(round(fs))}"))
    else:
        items.append(_risk_item("Fleet Safety Score", "OK", "No score data available"))

    if samba and samba.get("invalid_licenses"):
        n = len(samba["invalid_licenses"])
        nms = ", ".join(d.get("name", "?") for d in samba["invalid_licenses"][:2])
        items.append(_risk_item("Invalid / Disqualified CDL", "TRIPPED",
                                f"{n} driver{'s' if n != 1 else ''} with invalid license — pull from dispatch: {nms}"))
    elif samba:
        items.append(_risk_item("Invalid / Disqualified CDL", "OK", "No invalid or disqualified licenses"))

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


def _pd(text: str) -> str:
    """Muted progressive-discipline sub-line appended to relevant action items."""
    return (f"<br><em style='color:#888;font-size:11px;'>&#9656; Progressive discipline: "
            f"{text}</em>")


def _build_action_items(m: dict, samsara: dict | None, samba, equipment,
                        alvys_drivers=None, samsara_sheets=None,
                        prev_scores=None) -> str:
    """Action Items block derived from live data."""
    detail = (samsara or {}).get("detail", {}) or {}
    unique_dvirs = _dedup_dvirs(detail.get("dvir", []) or [])
    fleet = (samsara or {}).get("fleet", {}) or {}
    scores_all = fleet.get("scores_all") or []

    urgent: list[str] = []
    today_items: list[str] = []

    # CDL disqualified → Safety Mgr
    if samba and samba.get("invalid_licenses"):
        for d in samba["invalid_licenses"][:3]:
            nm = d.get("name") or "Unknown"
            status = (d.get("status") or "INVALID").upper()
            urgent.append(_action_row("URGENT", "Safety Mgr",
                                      f"PULL FROM SERVICE: {nm} — CDL {status} — cannot legally operate CMV"))

    # Driver's license expiration — 2-tier escalation (SambaSafety feed)
    if samba and samba.get("license_issues"):
        for d in samba["license_issues"]:
            days = d.get("days_to_exp")
            if days is None or days < 0:
                continue  # expired/invalid handled by CDL disqualified block above
            nm  = d.get("name", "Unknown")
            exp = d.get("exp")
            try:
                exp_fmt = pd.Timestamp(exp).strftime("%-m/%-d/%y")
            except Exception:
                exp_fmt = str(exp)[:10] if exp else "?"
            if days <= 5:
                urgent.append(_action_row("URGENT", "Safety Mgr",
                                          f"{nm}: driver's license expires in {days}d ({exp_fmt}) — "
                                          f"confirm appointment is scheduled to renew and document appointment date"))
                today_items.append(_action_row("TODAY", "Dispatch",
                                               f"{nm}: driver's license expires in {days}d ({exp_fmt}) — "
                                               f"confirm driver can make their renewal appointment on time"))
            elif days <= 15:
                today_items.append(_action_row("TODAY", "Safety Mgr",
                                               f"{nm}: driver's license expires in {days}d ({exp_fmt}) — "
                                               f"when is this being renewed? Confirm renewal plan with driver."))

    # DOT medical card — 3-tier escalation (expired / ≤3d / ≤7d / ≤14d)
    if alvys_drivers:
        med14_list = alvys_drivers.get("medical_critical_14") or []
        for d in med14_list:
            nm = d.get("name") or "Unknown"
            days = d.get("medical_days", 0)
            exp = d.get("medical_exp") or ""
            if days <= 0:
                urgent.append(_action_row("URGENT", "Safety Mgr",
                                          f"{nm}: DOT medical card EXPIRED — pull from service immediately"))
            elif days <= 3:
                urgent.append(_action_row("URGENT", "Safety Mgr",
                                          f"{nm}: DOT physical in {days}d ({exp}) — confirm appointment is booked, "
                                          f"document appointment date"))
                today_items.append(_action_row("TODAY", "Dispatch",
                                               f"{nm}: DOT physical in {days}d ({exp}) — coordinate driver return "
                                               f"to ensure they are present for the appointment"))
            elif days <= 7:
                urgent.append(_action_row("URGENT", "Safety Mgr",
                                          f"{nm}: DOT medical expires in {days}d ({exp}) — confirm appointment "
                                          f"is scheduled and document appointment date in driver file"))
            else:
                urgent.append(_action_row("URGENT", "Safety Mgr",
                                          f"{nm}: DOT medical expires in {days}d ({exp}) — schedule appointment "
                                          f"now and document appointment date in driver file"))

    # Open DVIR defects → Safety Mgr / Dispatch
    for r in unique_dvirs[:3]:
        unit = r.get("unit") or "?"
        defect = r.get("defect") or "unspecified defect"
        driver = r.get("driver") or "?"
        urgent.append(_action_row("URGENT", "Safety Mgr / Dispatch",
                                  f"Resolve DVIR defect on unit {unit}: {defect} (reported by {driver})"))

    # HOS violations in last 24h → Safety Mgr
    if m["hos_24h"] > 0:
        urgent.append(_action_row("URGENT", "Safety Mgr",
                                  f"{m['hos_24h']} HOS violation"
                                  f"{'s' if m['hos_24h'] != 1 else ''} in last 24h — pull logs"
                                  + _pd("Step 2 — coaching conversation within 5 business days. "
                                        "Two violations in 30 days → written warning (Step 3).")))

    # SambaSafety risk flags → Safety Mgr
    if samba and samba.get("high_risk"):
        for d in (samba["high_risk"] or [])[:2]:
            nm = d.get("name") or d.get("driver") or "Unknown"
            today_items.append(_action_row("TODAY", "Safety Mgr",
                                           f"Review SambaSafety risk flag for {nm}"))

    # MVR violations (90-day window) → Safety Mgr per driver
    # Decision tree: challenge the violation OR acknowledge as factual.
    if samba and samba.get("violations"):
        for v in samba["violations"]:
            nm   = v.get("name", "Unknown")
            vtyp = v.get("type", "violation")
            pts  = v.get("points")
            sev  = (v.get("severity") or "").strip()
            vd   = v.get("date")
            try:
                date_fmt = pd.Timestamp(vd).strftime("%-m/%-d/%y")
            except Exception:
                date_fmt = str(vd)[:10] if vd else "?"
            pts_note = f" | {int(pts)} pts" if _isnum(pts) else ""
            sev_note = f" | {sev}" if sev else ""
            today_items.append(_action_row("TODAY", "Safety Mgr",
                                           f"{nm}: MVR violation — {vtyp} ({date_fmt}{pts_note}{sev_note}). "
                                           f"Speak with driver about what happened. Decision: "
                                           f"challenge the violation OR acknowledge as factual violation against "
                                           f"equipment/driver. Document decision and action taken."
                                           + _pd("Step 1 — document violation in driver file today. "
                                                 "Step 2 — coaching conversation within 5 business days "
                                                 "with outcome of challenge/factual decision recorded.")))

    # Overdue annual inspections — tractors → Safety Mgr, trailers → Dispatch
    if equipment:
        od_t = [r for r in (equipment.get("tractors") or [])
                if isinstance(r.get("annual_days"), int) and r["annual_days"] < 0]
        od_r = [r for r in (equipment.get("trailers") or [])
                if isinstance(r.get("annual_days"), int) and r["annual_days"] < 0]
        for r in od_t[:3]:
            unit = r.get("unit", "?")
            days = abs(r.get("annual_days", 0))
            today_items.append(_action_row("TODAY", "Safety Mgr",
                                           f"Schedule inspection: unit {unit} ({days}d past 120-day policy)"))
        for r in od_r[:3]:
            unit = r.get("unit", "?")
            days = abs(r.get("annual_days", 0))
            today_items.append(_action_row("TODAY", "Dispatch",
                                           f"Schedule inspection: unit {unit} ({days}d past 120-day policy)"))

    # DVIR compliance <90% last 7d → Safety Mgr per driver
    if samsara_sheets:
        try:
            comp_rows = compute_inspection_compliance(samsara_sheets, days=7)
            for row in comp_rows:
                exp  = row.get("expected_total", 0)
                done = row.get("done_total", 0)
                if exp <= 0:
                    continue
                comp_pct = round(done / exp * 100)
                if comp_pct < 90:
                    drv = row.get("driver", "Unknown")
                    wd  = row.get("working_days", 0)
                    today_items.append(_action_row("TODAY", "Safety Mgr",
                                                   f"{drv}: DVIR compliance {comp_pct}% last 7d "
                                                   f"({done}/{exp}, {wd} working day{'s' if wd != 1 else ''}) "
                                                   f"— discuss with driver, document corrective action"
                                                   + _pd("Step 2 — coaching conversation on pre/post-trip "
                                                         "inspection expectations within 5 business days. "
                                                         "Repeat within 60 days → written warning (Step 3).")))
        except Exception:
            pass

    # Safety score <90 → Safety Mgr per driver (action plan + document)
    for r in scores_all:
        score = r.get("score")
        if score is None or score >= 90:
            continue
        drv = r.get("driver", "Unknown")
        today_items.append(_action_row("TODAY", "Safety Mgr",
                                       f"{drv}: safety score {score} (below 90 threshold) "
                                       f"— meet with driver, develop improvement plan, document outcome"
                                       + _pd("Step 2 — coaching conversation + written improvement plan "
                                             "within 5 business days. No improvement after 30 days → "
                                             "Step 4 (performance improvement period).")))

    # Safety score trends vs yesterday → Safety Mgr (decline = plan; improve = kudos)
    if prev_scores:
        for r in scores_all:
            drv = r.get("driver")
            curr = r.get("score")
            if not drv or curr is None:
                continue
            prev = prev_scores.get(drv)
            if prev is None:
                continue
            delta = curr - prev
            if delta < 0:
                today_items.append(_action_row("TODAY", "Safety Mgr",
                                               f"{drv}: safety score dropped {prev}→{curr} "
                                               f"— identify root cause, develop action plan, "
                                               f"document steps taken"
                                               + _pd("Step 2 — coaching conversation within 5 business days "
                                                     "if this reflects a pattern. Document root cause and "
                                                     "corrective steps taken.")))
            elif delta > 0:
                today_items.append(_action_row("TODAY", "Safety Mgr",
                                               f"{drv}: safety score improved {prev}→{curr} "
                                               f"— recognize driver, reinforce positive behavior"))

    # Coaching sessions past due (manager-led) → Safety Mgr per driver
    cs = (samsara or {}).get("coaching_sessions", {}) or {}
    for r in (cs.get("manager_past_due") or []):
        drv  = r.get("driver", "Unknown")
        due  = r.get("due_at", "")
        ovrd = r.get("days_overdue", 0)
        bhv  = r.get("behaviors", "")
        note = f" ({bhv})" if bhv else ""
        today_items.append(_action_row("TODAY", "Safety Mgr",
                                       f"{drv}: coaching session overdue {ovrd}d (due {due}){note}"
                                       f" — conduct session and document outcome"
                                       + _pd("This IS Step 2 — overdue means it must be completed today. "
                                             "If second incident of same type within 60 days → "
                                             "written warning required (Step 3).")))

    # Safety events needing coaching (needsCoaching / unacknowledged) → Safety Mgr
    coaching_list = (samsara or {}).get("coaching_list") or []
    for c in coaching_list:
        if c.get("acked"):
            continue
        drv   = c.get("driver", "Unknown")
        n     = c.get("events", 1)
        types = ", ".join(c.get("types") or []) or "safety event"
        sevs  = ", ".join(c.get("severities") or []) or ""
        units = ", ".join(c.get("units") or []) or ""
        unit_note = f" on unit {units}" if units else ""
        sev_note  = f" (severity: {sevs})" if sevs else ""
        today_items.append(_action_row("TODAY", "Safety Mgr",
                                       f"{drv}: {n} safety event{'s' if n != 1 else ''} need coaching — "
                                       f"{types}{unit_note}{sev_note}. "
                                       f"Conduct coaching session with driver and document "
                                       f"type of action taken to prevent recurrence."
                                       + _pd("Step 2 — coaching conversation within 5 business days. "
                                             "Same event type repeated within 60 days → "
                                             "written warning (Step 3).")))

    # Speeding ≥1% last 7 days → Safety Mgr per driver with coaching directive
    for r in scores_all:
        pct_7d  = r.get("speed_pct_7d")
        pct_6mo = r.get("speed_pct")
        pct_3mo = r.get("speed_pct_3mo")
        if not _isnum(pct_7d) or pct_7d < 1.0:
            continue
        drv = r.get("driver", "Unknown")
        comment = compute_speed_comment(pct_6mo, pct_3mo, pct_7d)
        comment = comment.rstrip(". ").lower()
        today_items.append(_action_row("TODAY", "Safety Mgr",
                                       f"{drv}: speeding {pct_7d:.1f}% last 7d — {comment} "
                                       f"— document coaching session and outcome"
                                       + _pd("Step 2 — coaching conversation within 5 business days. "
                                             "Record session outcome in Samsara. "
                                             "Repeat within 60 days → written warning (Step 3).")))

    # On-duty today with uncertified prior-day logs → Dispatch per driver
    uncert = detail.get("hos_uncert", []) or []
    _today_d = pd.Timestamp.now().date()
    _yesterday = _today_d - pd.Timedelta(days=1)
    def _span_end_ai(r: dict):
        s = r.get("span", "")
        end = s.split("–")[-1].strip() if "–" in s else s.strip()
        try:
            return pd.to_datetime(end).date()
        except Exception:
            return None
    on_duty_now = sorted(
        [r for r in uncert if (_span_end_ai(r) or pd.Timestamp.min.date()) >= _yesterday],
        key=lambda x: -x.get("days_missing", 0))
    for r in on_duty_now:
        drv  = r.get("driver", "Unknown Driver")
        days = r.get("days_missing", 1)
        today_items.append(_action_row("TODAY", "Dispatch",
                                       f"{drv}: certify prior-day logs before next dispatch "
                                       f"({days}d outstanding)"))

    # Count items by owner for the action-items header summary tile.
    # total = distinct action items (each row counts once regardless of owner).
    # sm/di counts include shared "Safety Mgr / Dispatch" items in both buckets.
    all_items = urgent + today_items
    total_count = len(all_items)
    sm_count = sum(1 for h in all_items if "<b>Safety Mgr" in h)
    di_count = sum(1 for h in all_items if "Dispatch" in h)

    if not urgent and not today_items:
        return (
            f"<div style='padding:0 24px 18px;color:{MUTE};font-size:13px;'>"
            f"No action items — all risk indicators within normal thresholds.</div>",
            0, 0, 0,
        )

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
    return html, sm_count, di_count, total_count


# ----------------------------------------------------------------------
# Structured accountability items — for Teams Adaptive Cards + JSON output
# ----------------------------------------------------------------------

_ACC_FOLDER = "Safety"


def _acc_onedrive_path(d: datetime.date) -> str:
    return f"{_ACC_FOLDER}/accountability-{d.isoformat()}.json"


def _acc_local_path(d: datetime.date) -> Path:
    return Path(f"output/accountability-{d.isoformat()}.json")


def _accountability_key(item: dict) -> str:
    cat  = (item.get("category") or "").lower().strip()
    drv  = (item.get("driver") or "").lower().strip()
    unit = (item.get("unit") or "").lower().strip()
    if "dvir defect" in cat:
        detail = (item.get("detail") or "").lower().strip()
        return f"{cat}|{drv or unit}|{detail}"
    if "needs disposition" in cat:
        detail = (item.get("detail") or "").lower().strip()
        return f"{cat}|{drv}|{detail}"
    return f"{cat}|{drv or unit}"


def _load_accountability_history(tok: str, upn: str, today: datetime.date,
                                 days_back: int = 30) -> list:
    """Return flat list of all items from last N days with _date added."""
    all_items: list[dict] = []
    for d in range(1, days_back + 1):
        date = today - datetime.timedelta(days=d)
        data = None
        local = _acc_local_path(date)
        if local.exists():
            try:
                data = json.loads(local.read_text())
            except Exception:
                pass
        if data is None:
            try:
                raw = download_file(tok, upn, _acc_onedrive_path(date))
                data = json.loads(raw)
            except Exception:
                pass
        if data:
            for item in (data.get("audra") or []) + (data.get("ops") or []):
                cp = dict(item)
                cp["_date"] = date.isoformat()
                all_items.append(cp)
    return all_items


def _count_occurrences(history: list, driver_or_unit: str, category: str) -> int:
    """Count unique days this driver/unit had this category in history."""
    cat_norm = category.lower().strip()
    du_norm  = (driver_or_unit or "").lower().strip()
    seen_dates: set[str] = set()
    for item in history:
        item_cat  = (item.get("category") or "").lower().strip()
        item_du   = (item.get("driver") or item.get("unit") or "").lower().strip()
        item_date = item.get("_date", "")
        if item_cat == cat_norm and item_du == du_norm and item_date not in seen_dates:
            seen_dates.add(item_date)
    return len(seen_dates)


def _occurrence_label(n: int, category: str) -> str:
    """Return escalation label for occurrence count > 1."""
    if n <= 1:
        return ""
    cat = category.lower()
    if "inspection" in cat or "dvir defect" in cat:
        return f" ({n}x this unit in 30d — escalate if no action)"
    if n == 2:
        return " ⚠️ 2nd occurrence in 30d — verbal warning required"
    if n == 3:
        return " 🔴 3rd occurrence in 30d — written warning required"
    return f" 🚨 {n}th occurrence in 30d — escalate to JB immediately"


def _build_accountability_structured(
    m: dict,
    samsara: dict | None,
    samba,
    equipment,
    alvys_drivers=None,
    samsara_sheets=None,
) -> tuple[list[dict], list[dict]]:
    """Build structured accountability items for Teams Adaptive Cards.

    Returns (audra_items, ops_items).  Each item is a dict with keys:
        category, severity, driver, unit, detail, prompt
    This mirrors the HTML built by _build_action_items() but in machine-readable form.
    """
    detail     = (samsara or {}).get("detail", {}) or {}
    fleet      = (samsara or {}).get("fleet", {}) or {}
    scores_all = fleet.get("scores_all") or []

    audra_items: list[dict] = []
    ops_items:   list[dict] = []

    # HOS violations in last 24h
    if m.get("hos_24h", 0) > 0:
        n = m["hos_24h"]
        item = {
            "category": "HOS Violation",
            "severity": "high",
            "driver":   None,
            "unit":     None,
            "detail":   f"{n} violation{'s' if n != 1 else ''} in last 24h",
            "prompt":   "Has driver been counseled? What corrective action was taken?",
        }
        ops_items.append(item)
        audra_items.append(item)

    # Open DVIR defects
    unique_dvirs = _dedup_dvirs(detail.get("dvir", []) or [])
    for r in unique_dvirs:
        unit   = r.get("unit") or "?"
        defect = r.get("defect") or "unspecified defect"
        item = {
            "category": "DVIR Defect",
            "severity": "critical",
            "driver":   r.get("driver") or None,
            "unit":     unit,
            "detail":   defect,
            "prompt":   "Has defect been repaired and cleared in Samsara?",
        }
        audra_items.append(item)
        ops_items.append(item)

    # Safety events needing coaching (coaching_list, not yet acked)
    coaching_list = (samsara or {}).get("coaching_list") or []
    for c in coaching_list:
        if c.get("acked"):
            continue
        drv   = c.get("driver", "Unknown")
        n     = c.get("events", 1)
        types = ", ".join(c.get("types") or []) or "safety event"
        ops_items.append({
            "category": "Safety Event — Coaching Needed",
            "severity": "high",
            "driver":   drv,
            "unit":     None,
            "detail":   f"{n} event{'s' if n != 1 else ''}: {types}",
            "prompt":   "When will coaching be completed? What corrective action was taken?",
        })

    # Safety events needing disposition (from detail.events where status needs action)
    _needs_disp_statuses = {
        "needsCoaching", "needs_coaching", "NEEDS_COACHING",
        "needsDisposition", "needs_disposition", "NEEDS_DISPOSITION",
    }
    for ev in (detail.get("events") or []):
        if ev.get("status") not in _needs_disp_statuses:
            continue
        drv   = ev.get("driver") or "Unknown"
        etype = ev.get("type") or ev.get("event_type") or "safety event"
        edate = ""
        raw_ts = ev.get("time") or ev.get("event_time") or ev.get("date") or ""
        if raw_ts:
            try:
                edate = " on " + pd.Timestamp(raw_ts).strftime("%-m/%-d/%y")
            except Exception:
                pass
        ops_items.append({
            "category": "Safety Event — Needs Disposition",
            "severity": "high",
            "driver":   drv,
            "unit":     None,
            "detail":   f"{etype}{edate}",
            "prompt":   "Has this event been dispositioned in Samsara? What coaching action was taken?",
        })

    # DOT inspection — Tractors (annual_days < 0 → overdue); both audra + ops
    if equipment:
        for r in (equipment.get("tractors") or []):
            annual_days = r.get("annual_days")
            if not isinstance(annual_days, int) or annual_days >= 0:
                continue
            unit = r.get("unit", "?")
            over = abs(annual_days)
            if over >= 120:
                sev        = "critical"
                prompt     = "UNIT IS OUT OF SERVICE. Must be inspected before moving."
                detail_str = f"{over}d past 120d policy — DEADLINED"
            elif over > 60:
                sev        = "critical"
                prompt     = "Inspection must be scheduled immediately. When is appointment?"
                detail_str = f"{over}d past 120d policy"
            else:
                sev        = "high"
                prompt     = "Inspection must be scheduled immediately. When is appointment?"
                detail_str = f"{over}d past 120d policy"
            item = {
                "category": "DOT Inspection — Tractor",
                "severity": sev,
                "driver":   None,
                "unit":     unit,
                "detail":   detail_str,
                "prompt":   prompt,
            }
            audra_items.append(item)
            ops_items.append(item)

        # DOT inspection — Trailers (ops only)
        for r in (equipment.get("trailers") or []):
            annual_days = r.get("annual_days")
            if not isinstance(annual_days, int) or annual_days >= 0:
                continue
            unit = r.get("unit", "?")
            over = abs(annual_days)
            if over >= 120:
                sev        = "critical"
                prompt     = "UNIT IS OUT OF SERVICE. Must be inspected before moving."
                detail_str = f"{over}d past 120d policy — DEADLINED"
            elif over > 60:
                sev        = "critical"
                prompt     = "Inspection must be scheduled immediately. When is appointment?"
                detail_str = f"{over}d past 120d policy"
            else:
                sev        = "high"
                prompt     = "Inspection must be scheduled immediately. When is appointment?"
                detail_str = f"{over}d past 120d policy"
            ops_items.append({
                "category": "DOT Inspection — Trailer",
                "severity": sev,
                "driver":   None,
                "unit":     unit,
                "detail":   detail_str,
                "prompt":   prompt,
            })

    # DVIR compliance <90% last 7d
    if samsara_sheets:
        try:
            comp_rows = compute_inspection_compliance(samsara_sheets, days=7)
            for row in comp_rows:
                exp  = row.get("expected_total", 0)
                done = row.get("done_total", 0)
                if exp <= 0:
                    continue
                pct = round(done / exp * 100)
                if pct < 90:
                    drv = row.get("driver", "Unknown")
                    if pct == 0:
                        sev = "critical"
                    elif pct < 50:
                        sev = "high"
                    else:
                        sev = "medium"
                    ops_items.append({
                        "category": "DVIR Compliance",
                        "severity": sev,
                        "driver":   drv,
                        "unit":     None,
                        "detail":   f"{pct}% completion last 7d ({done}/{exp})",
                        "prompt":   "Has driver been notified? What corrective action was taken?",
                    })
        except Exception:
            pass

    # Prior-day logs not certified (on duty yesterday/today)
    uncert       = detail.get("hos_uncert", []) or []
    _today_d     = pd.Timestamp.now().date()
    _yesterday_d = _today_d - pd.Timedelta(days=1)

    def _span_end_ac(r: dict):
        s   = r.get("span", "")
        end = s.split("–")[-1].strip() if "–" in s else s.strip()
        try:
            return pd.to_datetime(end).date()
        except Exception:
            return None

    on_duty_now = [
        r for r in uncert
        if (_span_end_ac(r) or pd.Timestamp.min.date()) >= _yesterday_d
    ]
    for r in on_duty_now:
        drv  = r.get("driver", "Unknown Driver")
        days = r.get("days_missing", 1)
        ops_items.append({
            "category": "Prior Day Logs Not Certified",
            "severity": "medium",
            "driver":   drv,
            "unit":     None,
            "detail":   f"{days}d outstanding",
            "prompt":   "Has driver been notified to certify logs? What corrective action was taken?",
        })

    # Low safety score (<90)
    for r in scores_all:
        score = r.get("score")
        if score is None or score >= 90:
            continue
        drv = r.get("driver", "Unknown")
        ops_items.append({
            "category": "Low Safety Score",
            "severity": "high",
            "driver":   drv,
            "unit":     None,
            "detail":   f"Score {score}",
            "prompt":   "When will coaching be completed? Improvement plan documented?",
        })

    # Speeding (speed_pct_7d >= 1%)
    for r in scores_all:
        pct_7d = r.get("speed_pct_7d")
        if not _isnum(pct_7d) or pct_7d < 1.0:
            continue
        drv = r.get("driver", "Unknown")
        ops_items.append({
            "category": "Speeding",
            "severity": "high",
            "driver":   drv,
            "unit":     None,
            "detail":   f"{pct_7d:.1f}% time speeding last 7d",
            "prompt":   "Has driver been coached on speeding? What corrective action was taken?",
        })

    return audra_items, ops_items


def _write_accountability_json(
    today: datetime.date,
    audra_items: list[dict],
    ops_items: list[dict],
    history: list[dict],
    tok: str,
    upn: str,
) -> None:
    """Enrich items with carry-forward (days_open) and occurrence counts,
    then write to output/ and upload to OneDrive/Safety/."""
    yesterday = today - datetime.timedelta(days=1)

    # Build yesterday's key→days_open map for carry-forward
    yesterday_keys: dict[str, int] = {}
    for item in history:
        if item.get("_date") == yesterday.isoformat():
            key = _accountability_key(item)
            yesterday_keys[key] = item.get("days_open", 1)

    def _enrich(items: list[dict]) -> list[dict]:
        enriched = []
        for item in items:
            item = dict(item)
            key = _accountability_key(item)
            prev_days = yesterday_keys.get(key, 0)
            item["days_open"] = prev_days + 1 if prev_days else 1

            drv_or_unit = item.get("driver") or item.get("unit") or ""
            occ = _count_occurrences(history, drv_or_unit, item.get("category", ""))
            item["occurrence"] = occ + 1  # +1 for today

            label = _occurrence_label(item["occurrence"], item.get("category", ""))
            if label:
                item["prompt"] = item.get("prompt", "") + label

            # Auto-escalate severity for repeat driver-based offenders
            cat = (item.get("category") or "").lower()
            if "inspection" not in cat and "dvir defect" not in cat:
                if item["occurrence"] >= 3 and item.get("severity") != "critical":
                    item["severity"] = "critical"
                elif item["occurrence"] == 2 and item.get("severity") == "medium":
                    item["severity"] = "high"

            enriched.append(item)
        return enriched

    audra_enriched = _enrich(audra_items)
    ops_enriched   = _enrich(ops_items)

    payload = {
        "date":  today.isoformat(),
        "audra": audra_enriched,
        "ops":   ops_enriched,
    }

    # Write locally (teams_adaptive_cards.py reads from output/)
    local = _acc_local_path(today)
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(json.dumps(payload, indent=2))
    log.info("Accountability JSON written locally: %s (%d audra, %d ops)",
             local, len(audra_enriched), len(ops_enriched))

    # Upload to OneDrive/Safety/
    try:
        ensure_folder(tok, upn, _ACC_FOLDER)
        upload_file(
            tok, upn,
            folder_path=_ACC_FOLDER,
            filename=f"accountability-{today.isoformat()}.json",
            file_path=local,
        )
        log.info("Accountability JSON uploaded to OneDrive/%s", _acc_onedrive_path(today))
    except Exception as exc:
        log.warning("Could not upload accountability JSON: %s", exc)


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
                        total: int, date_str: str, samba, equipment,
                        alvys_drivers=None, samsara_sheets=None,
                        prev_scores=None) -> str:
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

    # Build action items first to get owner counts for the header summary
    ai_html, sm_count, di_count, total_count = _build_action_items(
        metrics, samsara, samba, equipment,
        alvys_drivers=alvys_drivers,
        samsara_sheets=samsara_sheets,
        prev_scores=prev_scores,
    )

    # Safety event counts for 24h / 48h / 72h windows
    ev_24h = metrics.get("events_24h", 0)
    ev_48h = _events_in_window(samsara_sheets, 48)
    ev_72h = _events_in_window(samsara_sheets, 72)

    def _ai_chip(label: str, val: int, kind: str = "mute") -> str:
        colors = {
            "bad":  (BAD,  BADBG),
            "warn": (WARN, WARNBG),
            "mute": (MUTE, "#eef2f7"),
        }
        fg, bg = colors.get(kind, colors["mute"])
        return (f"<span style='display:inline-block;background:{bg};color:{fg};"
                f"font-size:10.5px;font-weight:700;padding:3px 9px;border-radius:10px;"
                f"margin-left:6px;white-space:nowrap;'>{label}: {val}</span>")

    ai_chips = (
        _ai_chip("Total Outstanding", total_count, "bad" if total_count else "mute")
        + _ai_chip("Safety Mgr", sm_count, "bad" if sm_count else "mute")
        + _ai_chip("Dispatch", di_count, "warn" if di_count else "mute")
        + "&nbsp;&nbsp;"
        + _ai_chip("24h events", ev_24h, "warn" if ev_24h else "mute")
        + _ai_chip("48h events", ev_48h, "warn" if ev_48h else "mute")
        + _ai_chip("72h events", ev_72h, "warn" if ev_72h else "mute")
    )

    ai_title = (
        f"<div style='padding:18px 24px 4px;'>"
        f"<table width='100%' cellpadding='0' cellspacing='0'><tr>"
        f"<td valign='bottom'>"
        f"<div style='{FONT_SERIF}font-size:17px;font-weight:400;color:{INK};"
        f"letter-spacing:-0.3px;'>Action Items</div>"
        f"<div style='width:36px;height:2px;background:{INK};margin-top:6px;'></div>"
        f"</td>"
        f"<td align='right' valign='bottom' style='padding-bottom:2px;'>{ai_chips}</td>"
        f"</tr></table>"
        f"</div>"
    )

    return (header
            + bottom_line_block
            + urgent_block
            + rw_title
            + _build_risk_watch(metrics, samsara, samba, equipment)
            + ai_title
            + ai_html)


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
            out[state_key] = _monthly_counts(pd.Series([], dtype=object))
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
            out[state_key] = _monthly_counts(pd.Series([], dtype=object))

    # DVIR compliance % — inspections done / expected (working_days × 2)
    # Uses DVIR_Inspections (all inspections incl. safe) + HOS_DailyLogs (working days).
    _fallback_labels, _fallback_zeros = _monthly_counts(pd.Series([], dtype=object))
    insp_df  = (samsara_sheets or {}).get("DVIR_Inspections")
    hos_df   = (samsara_sheets or {}).get("HOS_DailyLogs")

    def _working_days_by_month(hos: "pd.DataFrame | None") -> dict:
        """Return {(yr, mo): driver_day_count} from HOS daily logs."""
        if hos is None or hos.empty:
            return {}
        dc  = _find_col(hos, ["log date", "starttime", "start time", "date"])
        drv = _find_col(hos, ["driver name", "driver"])
        if not dc or not drv:
            return {}
        # Include ALL drive/onduty columns — both certified (dutyStatusDurations.*)
        # and pending (pendingDutyStatusDurations.*) so recent uncertified log days
        # (where certified driveDurationMs=0 but pending > 0) are counted correctly.
        drive_cols = [c for c in hos.columns if "drivedurationms" in str(c).lower()]
        onduty_cols = [c for c in hos.columns if "ondutydurationms" in str(c).lower()]
        activity_cols = drive_cols + onduty_cols
        h = hos[[dc, drv] + activity_cols].copy()
        h["_dt"] = _to_naive_dt(h[dc])
        h["_drv"] = h[drv].astype(str).str.strip()
        if activity_cols:
            active = pd.Series([False] * len(h), index=h.index)
            for col in activity_cols:
                active |= pd.to_numeric(h[col], errors="coerce").fillna(0) > 0
            h = h[active]
        h = h[h["_drv"].ne("") & h["_dt"].notna()]
        result: dict = {}
        for _, row in h.iterrows():
            key = (row["_dt"].year, row["_dt"].month)
            result[key] = result.get(key, 0) + 1
        return result

    if insp_df is not None and not insp_df.empty:
        idc = _find_col(insp_df, ["reported", "createdat"])
        drv_col_i = _find_col(insp_df, ["driver"])
        if idc:
            cols_i = [idc] + ([drv_col_i] if drv_col_i else [])
            di = insp_df[cols_i].copy()
            di["_dt"] = _to_naive_dt(di[idc])
            if drv_col_i:
                di["_drv"] = di[drv_col_i].astype(str).str.strip()
            wd_by_month = _working_days_by_month(hos_df)
            months6 = _last_6_months()
            labels, pcts = [], []
            for i, (yr, mo) in enumerate(months6):
                mask  = (di["_dt"].dt.year == yr) & (di["_dt"].dt.month == mo)
                done  = int(mask.sum())
                wd    = wd_by_month.get((yr, mo), 0)
                exp   = wd * 4  # 4 expected per working day: pre+post × tractor+trailer
                lab = pd.Timestamp(year=yr, month=mo, day=1).strftime("%b")
                if i == len(months6) - 1:
                    lab += "*"
                labels.append(lab)
                if exp > 0:
                    pcts.append(min(round(done / exp * 100), 100))
                else:
                    pcts.append(0)
            out["dvir_pct"] = (labels, pcts)
            # Last-7d KPI — use the same source as the compliance table
            # (compute_inspection_compliance) so the KPI matches the table exactly.
            _comp_rows_7d = compute_inspection_compliance(samsara_sheets, days=7)
            if _comp_rows_7d:
                _td = sum(r.get("done_total", 0) for r in _comp_rows_7d)
                _te = sum(r.get("expected_total", 0) for r in _comp_rows_7d)
                out["dvir_comp_7d"] = min(round(_td / _te * 100), 100) if _te > 0 else None
            else:
                out["dvir_comp_7d"] = None
        else:
            out["dvir_pct"] = (_fallback_labels, _fallback_zeros)
            out["dvir_comp_7d"] = None
    else:
        out["dvir_pct"] = (fallback_months, [0] * len(fallback_months))
        out["dvir_comp_7d"] = None

    # Speed over limit — fleet avg % drive time per calendar month.
    # samsara_main now makes per-month API calls and stores them in speeds_monthly.
    # Current month uses MTD; completed months use actual per-month API results.
    scores_all = ((samsara or {}).get("fleet") or {}).get("scores_all") or []
    speeds_monthly = ((samsara or {}).get("fleet") or {}).get("speeds_monthly") or {}
    months6 = _last_6_months()
    _n6 = len(months6)
    labels = [
        pd.Timestamp(year=yr, month=mo, day=1).strftime("%b") + ("*" if i == _n6 - 1 else "")
        for i, (yr, mo) in enumerate(months6)
    ]
    pcts = []
    for i, (yr, mo) in enumerate(months6):
        if i == _n6 - 1:
            mtd_vals = [r.get("speed_pct_mtd") for r in scores_all if _isnum(r.get("speed_pct_mtd"))]
            spd_vals = [r.get("speed_pct") for r in scores_all if _isnum(r.get("speed_pct"))]
            if mtd_vals:
                pcts.append(round(sum(mtd_vals) / len(mtd_vals), 2))
            elif spd_vals:
                pcts.append(round(sum(spd_vals) / len(spd_vals), 2))
            else:
                pcts.append(0.0)
        else:
            pcts.append(speeds_monthly.get((yr, mo), 0.0))
    out["speed_pct"] = (labels, pcts)

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
    elif dvir_pct_c and dvir_pct_c[-1]:
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
                _pill("Samsara · 0–100 · higher is safer", score_kind), width="33%")
        + _tile("DVIR open defects", num(metrics["dvir_open"]),
                _pill("pending mechanic repair",
                      "warn" if metrics["dvir_open"] else "good"), width="33%")
        + _tile("DVIR compliance", dvir_comp_txt,
                _pill("completed / required · last 7d", dvir_comp_kind), width="34%")
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
                     "% inspections completed · *MTD · done÷(HOS days×4)",
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
                     fmt=lambda v: f"{v:.2f}%", y_max=2.0)
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

    # Missing log certifications (full 7-day window — leading indicator)
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
        "No missing log certifications in the last 7 days — all logs signed.",
        span=4)

    # On-duty today — uncertified prior-day logs
    # Filter uncert for drivers whose span ends yesterday or today:
    # these are the drivers who started their current shift without certifying yesterday.
    def _span_end(r: dict):
        s = r.get("span", "")
        end = s.split("–")[-1].strip() if "–" in s else s.strip()
        try:
            return pd.to_datetime(end).date()
        except Exception:
            return None

    today_date  = pd.Timestamp.now().date()
    yesterday   = today_date - pd.Timedelta(days=1)
    on_duty_now = sorted(
        [r for r in uncert if (_span_end(r) or pd.Timestamp.min.date()) >= yesterday],
        key=lambda x: -x.get("days_missing", 0))

    if on_duty_now:
        items_html = ""
        for r in on_duty_now:
            drv  = r.get("driver", "Unknown Driver").upper()
            days = r.get("days_missing", 1)
            items_html += (
                f"<div style='display:flex;align-items:center;gap:12px;"
                f"padding:11px 0;border-bottom:1px solid {LINE};'>"
                f"<span style='background:{BAD};color:#fff;font-size:9px;font-weight:800;"
                f"letter-spacing:1.2px;padding:3px 8px;border-radius:4px;"
                f"white-space:nowrap;'>TODAY</span>"
                f"<span style='font-size:12.5px;color:{INK};'>"
                f"<b>Dispatch:</b> {drv}: {days}d missing log certifications</span>"
                f"</div>"
            )
        on_duty_tr = (
            _section("On-duty today — uncertified prior-day logs"
                     " · started this shift without certifying yesterday")
            + f"<tr><td colspan='4' style='padding:0 6px 10px;'>{items_html}</td></tr>"
        )
    else:
        on_duty_tr = (
            _section("On-duty today — uncertified prior-day logs"
                     " · started this shift without certifying yesterday")
            + f"<tr><td colspan='4' style='padding:0 6px 10px;'>"
            f"<div style='border-left:4px solid {GOOD};background:{GOODBG};"
            f"border-radius:6px;padding:10px 14px;'>"
            f"<div style='font-size:10px;letter-spacing:1.5px;font-weight:800;"
            f"color:{GOOD};margin-bottom:4px;'>&#10003; ALL CLEAR</div>"
            f"<div style='font-size:12.5px;color:{INK};'>"
            f"Every driver working today has certified their prior-day logs"
            f" — no audit risk from missed start-of-shift certifications.</div>"
            f"</div></td></tr>"
        )

    return (header
            + f"<table width='100%' cellpadding='0' cellspacing='0' style='padding:8px 18px 0;'>"
            + _section("Safety events — last 7 days")
            + _table(["Driver", "Unit", "Reported", "Event type", "Severity", "Status"],
                     ["left"] * 6, ev_rows)
            + _section("HOS violations — last 7 days (driving-rule breaches)")
            + _table(["Driver", "Reported", "Violation type", "Status"],
                     ["left"] * 4, hos_rows)
            + on_duty_tr
            + _section("Missing log certifications — last 7 days // leading indicator")
            + _table(["Driver", "Days missing", "Date range", "Status"],
                     ["left", "right", "left", "left"], uc_rows)
            + "</table>"
            + f"<div style='padding:14px 24px 22px;color:{MUTE};font-size:11px;"
            f"border-top:1px solid {LINE};margin-top:14px;'>"
            f"Source: Samsara SafetyEvents, HOS_Violations, HOS_DailyLogs (7-day window). "
            f"HOS = driving-rule breaches only (form-and-manner excluded). "
            f"On-duty today = uncertified drivers whose latest missing log is from yesterday. "
            f"Missing certifications = 7-day historical view (leading indicator).</div>")


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


def build_page_dvir_compliance(samsara_sheets: dict | None, pg: int,
                               total: int, date_str: str) -> str:
    """DVIR inspection compliance — last 7 days, per driver.

    Columns: Driver · Worked (days) · Tractor Done/Exp · Tractor Defects
             · Trailer Done/Exp · Trailer Defects · Total Done/Exp
             · Total Defects · Compliance %

    Working days, done counts and defects all come from
    ``compute_inspection_compliance`` (defined in scorecard_email.py).
    That function counts working days from HOS_DailyLogs using the
    actual column names that ship in the sheet
    (``dutystatusdurations.drivedurationms`` / ``ondutydurationms``)
    and EXCLUDES drivers with 0 working days — restoring the
    pre-2026-06-16 behaviour after a column-name regression caused
    every driver to appear with WKD=7.
    """
    header = _sc_header(
        "Safety &amp; Compliance · Inspection compliance",
        pg, total, date_str, section="EQUIPMENT")

    methodology = (
        f"<div style='padding:8px 24px 18px;font-size:11px;color:{MUTE};'>"
        f"Expected inspections = working days &times; 4 (pre-trip + post-trip &times; "
        f"tractor + trailer, per FMCSA 396.11/396.13). Working days from HOS logs "
        f"(drive or on-duty time &gt; 0). Chart uses same formula over the last 6 months.</div>"
    )

    # Single source of truth for working-days + done + defects.
    # Drivers with 0 working days are already filtered out inside.
    rows = compute_inspection_compliance(samsara_sheets, days=7)

    def _frac(done: int, exp: int) -> str:
        color = ""
        if done == 0 and exp > 0:
            color = f"color:{BAD};font-weight:700;"
        elif done >= exp and exp > 0:
            color = f"color:{GOOD};font-weight:700;"
        elif done < exp and exp > 0:
            color = f"color:{WARN};font-weight:700;"
        return f"<span style='{color}'>{done} / {exp}</span>"

    def _comp_cell(done: int, exp: int) -> tuple[str, str | None]:
        if exp == 0:
            return "&mdash;", None
        pct = round(done / exp * 100)
        txt = f"{pct}%"
        kind = "bad" if pct < 50 else ("warn" if pct < 95 else "good")
        return txt, kind

    driver_rows = []
    for r in rows:
        drv = r["driver"]
        if drv.lower().startswith("temp"):  # exclude Temp Driver placeholders
            continue
        days       = r["working_days"]
        td         = r["done_tractor"]
        rd         = r["done_trailer"]
        exp        = r["expected_tractor"]      # = days * 2
        tdef       = r["defects_tractor"]
        rdef       = r["defects_trailer"]
        total_done = r["done_total"]
        total_exp  = r["expected_total"]        # = exp + exp
        sort_pct   = round(total_done / total_exp * 100) if total_exp > 0 else 0
        driver_rows.append((sort_pct, drv, days, exp, td, rd, tdef, rdef, total_done, total_exp))

    driver_rows.sort(key=lambda r: r[0])  # worst compliance first

    tbody = ""
    tot_worked = tot_t_done = tot_t_exp = tot_t_def = 0
    tot_r_done = tot_r_exp = tot_r_def = 0

    CS = "padding:6px 4px;font-size:10px;border-bottom:1px solid " + LINE + ";"  # cell style

    for sort_pct, drv, days, exp, td, rd, tdef, rdef, total_done, total_exp in driver_rows:
        comp_txt, comp_kind = _comp_cell(total_done, total_exp)

        tot_worked += days
        tot_t_done += td;  tot_t_exp += exp;  tot_t_def += tdef
        tot_r_done += rd;  tot_r_exp += exp;  tot_r_def += rdef

        def_color = f"color:{BAD};font-weight:700;" if (tdef + rdef) > 0 else ""
        tbody += (
            f"<tr>"
            f"<td style='{CS}'>{drv}</td>"
            f"<td style='{CS}text-align:right;'>{days}</td>"
            f"<td style='{CS}text-align:right;'>{_frac(td, exp)}</td>"
            f"<td style='{CS}text-align:right;'><span style='{def_color}'>{tdef}</span></td>"
            f"<td style='{CS}text-align:right;'>{_frac(rd, exp)}</td>"
            f"<td style='{CS}text-align:right;'><span style='{def_color}'>{rdef}</span></td>"
            f"<td style='{CS}text-align:right;'>{_frac(total_done, total_exp)}</td>"
            f"<td style='{CS}text-align:right;'><span style='{def_color}'>{tdef + rdef}</span></td>"
            f"<td style='{CS}text-align:right;'>"
            + (_pill(comp_txt, comp_kind) if comp_kind else comp_txt)
            + "</td></tr>"
        )

    # Totals footer
    n_drv = len(driver_rows)
    total_done_all = tot_t_done + tot_r_done
    total_exp_all  = tot_t_exp  + tot_r_exp
    total_def_all  = tot_t_def  + tot_r_def
    comp_all_txt, comp_all_kind = _comp_cell(total_done_all, total_exp_all)
    def_all_color = f"color:{BAD};font-weight:700;" if total_def_all > 0 else ""
    FS = "padding:8px 4px;font-size:10px;border-top:2px solid " + INK + ";"  # footer style
    tbody += (
        f"<tr style='background:{TILEBG};font-weight:700;'>"
        f"<td style='{FS}'>TOTAL ({n_drv} drivers)</td>"
        f"<td style='{FS}text-align:right;'>{tot_worked}</td>"
        f"<td style='{FS}text-align:right;'>{tot_t_done} / {tot_t_exp}</td>"
        f"<td style='{FS}text-align:right;'><span style='{def_all_color}'>{tot_t_def}</span></td>"
        f"<td style='{FS}text-align:right;'>{tot_r_done} / {tot_r_exp}</td>"
        f"<td style='{FS}text-align:right;'><span style='{def_all_color}'>{tot_r_def}</span></td>"
        f"<td style='{FS}text-align:right;'>{total_done_all} / {total_exp_all}</td>"
        f"<td style='{FS}text-align:right;'><span style='{def_all_color}'>{total_def_all}</span></td>"
        f"<td style='{FS}text-align:right;'>{comp_all_txt}</td>"
        f"</tr>"
    )

    if not driver_rows:
        tbody = (_all_clear_row(
            "No DVIR inspection data available for the last 7 days — "
            "DVIR_Inspections sheet may not yet be populated (run the Samsara refresh first).",
            span=9))

    # Two-line headers + explicit % widths to force all 9 cols onto the page
    hdrs   = ["DRIVER", "WKD", "TRACTOR<br>DONE/EXP", "TRACTOR<br>DEFECTS",
              "TRAILER<br>DONE/EXP", "TRAILER<br>DEFECTS", "TOTAL<br>DONE/EXP",
              "TOTAL<br>DEFECTS", "COMP %"]
    widths = ["20%", "5%", "12%", "9%", "12%", "9%", "12%", "8%", "8%"]
    aligns = ["left", "right", "right", "right", "right", "right", "right", "right", "right"]
    thead = "".join(
        f"<th style='padding:5px 4px;font-size:9px;letter-spacing:0.5px;"
        f"text-transform:uppercase;color:{MUTE};font-weight:700;"
        f"border-bottom:2px solid {LINE};text-align:{a};width:{w};'>{h}</th>"
        for h, a, w in zip(hdrs, aligns, widths))
    table = (f"<table width='100%' cellpadding='0' cellspacing='0' "
             f"style='border-collapse:collapse;table-layout:fixed;'>"
             f"<thead><tr>{thead}</tr></thead>"
             f"<tbody>{tbody}</tbody></table>")

    return (header
            + methodology
            + f"<div style='padding:0 24px 4px;'>"
            + _section("DVIR inspection compliance — last 7 days")
            + f"</div>"
            + f"<div style='padding:4px 24px 24px;'>{table}</div>")


def build_page_dvir_detail(samsara_sheets: dict | None, pg: int,
                           total: int, date_str: str) -> str:
    """DVIR inspection detail — last 14 days, grouped by driver.

    Per-driver header shows name, inspection count, required/completed/missing/%.
    Row columns: Date/Time · Location · Vehicle · Trailer · Type · Safe · Defects
                 · Mechanic Notes.
    Data source: DVIR_Inspections sheet (one row per inspection leg).
    """
    header = _sc_header(
        "DVIR Inspection Detail — last 14 days", pg, total, date_str, section="EQUIPMENT")

    now = pd.Timestamp.now()
    cutoff_14d = now - pd.Timedelta(days=14)

    # ── Load DVIR_Inspections ────────────────────────────────────────────────
    insp_df = (samsara_sheets or {}).get("DVIR_Inspections")
    driver_inspections: dict[str, list[dict]] = {}

    if insp_df is not None and not insp_df.empty:
        dc  = _find_col(insp_df, ["reported", "createdat"])
        drv = _find_col(insp_df, ["driver"])
        typ = _find_col(insp_df, ["unittype"])
        dvc = _find_col(insp_df, ["dvirtype"])
        unt = _find_col(insp_df, ["unit"])
        loc = _find_col(insp_df, ["location"])
        saf = _find_col(insp_df, ["safe"])
        def_ = _find_col(insp_df, ["defectcount"])
        mec = _find_col(insp_df, ["mechanicnotes"])

        if dc and drv:
            df_i = insp_df.copy()
            df_i["_dt"] = pd.to_datetime(df_i[dc], errors="coerce", utc=True).dt.tz_localize(None)
            df_i["_drv"] = df_i[drv].astype(str).str.strip()
            df_i = df_i[(df_i["_dt"] >= cutoff_14d) & df_i["_drv"].ne("")]
            df_i = df_i.sort_values("_dt", ascending=False)

            for _, row in df_i.iterrows():
                d = row["_drv"]
                dt_str = row["_dt"].strftime("%Y-%m-%d %H:%M") if pd.notna(row["_dt"]) else "&mdash;"
                unit_val = str(row[unt]).strip() if unt and pd.notna(row[unt]) else ""
                unit_type = str(row[typ]).strip().lower() if typ else "tractor"
                vehicle = unit_val if unit_type == "tractor" else "&mdash;"
                trailer = unit_val if unit_type == "trailer" else "&mdash;"
                loc_val = str(row[loc]).strip() if loc and pd.notna(row[loc]) else "&mdash;"
                if not loc_val or loc_val in ("nan", "none", ""):
                    loc_val = "&mdash;"
                dvir_type = str(row[dvc]).strip() if dvc and pd.notna(row[dvc]) else "&mdash;"
                safe_val = row[saf] if saf and pd.notna(row[saf]) else True
                is_safe = safe_val is True or str(safe_val).lower() in ("true", "1", "yes")
                defects = int(row[def_]) if def_ and pd.notna(row[def_]) else 0
                notes = str(row[mec]).strip() if mec and pd.notna(row[mec]) else ""
                if not notes or notes in ("nan", "none", ""):
                    notes = "&mdash;"

                driver_inspections.setdefault(d, []).append({
                    "dt": dt_str, "loc": loc_val, "vehicle": vehicle,
                    "trailer": trailer, "type": dvir_type,
                    "safe": is_safe, "defects": defects, "notes": notes,
                })

    # ── Load worked days for expected calculation ────────────────────────────
    worked: dict[str, int] = {}
    hos_df = (samsara_sheets or {}).get("HOS_DailyLogs")
    if hos_df is not None and not hos_df.empty:
        hdc  = _find_col(hos_df, ["log date", "starttime", "date"])
        hdrv = _find_col(hos_df, ["driver name", "driver"])
        hdrvc = _find_col(hos_df, ["drivems", "drive ms"])
        hdutc = _find_col(hos_df, ["ondutytime", "on duty ms"])
        if hdc and hdrv:
            h7 = hos_df.copy()
            h7["_dt"] = pd.to_datetime(h7[hdc], errors="coerce", utc=True).dt.tz_localize(None)
            h7["_drv"] = h7[hdrv].astype(str).str.strip()
            h7 = h7[(h7["_dt"] >= cutoff_14d) & h7["_drv"].ne("")]
            if hdrvc or hdutc:
                act = pd.Series([False] * len(h7), index=h7.index)
                for col in [hdrvc, hdutc]:
                    if col:
                        act |= pd.to_numeric(h7[col], errors="coerce").fillna(0) > 0
                h7 = h7[act]
            for d, grp in h7.groupby("_drv"):
                worked[d] = grp["_dt"].dt.date.nunique()

    # ── Render per-driver blocks ─────────────────────────────────────────────
    HDRS  = ["DATE / TIME", "LOCATION", "VEHICLE", "TRAILER",
             "TYPE", "SAFE", "DEFECTS", "MECHANIC NOTES"]
    ALIGNS = ["left", "left", "right", "right", "left", "center", "right", "left"]
    COL_W  = ["12%", "28%", "8%", "8%", "8%", "6%", "6%", "24%"]

    thead_cells = "".join(
        f"<th style='padding:6px 8px;font-size:9.5px;letter-spacing:0.8px;"
        f"text-transform:uppercase;color:{MUTE};font-weight:700;"
        f"border-bottom:2px solid {LINE};text-align:{a};width:{w};white-space:nowrap;'>{h}</th>"
        for h, a, w in zip(HDRS, ALIGNS, COL_W))
    thead = f"<thead><tr>{thead_cells}</tr></thead>"

    def _driver_block(drv: str, rows: list[dict]) -> str:
        days    = worked.get(drv, 0)
        exp     = days * 2
        done    = len(rows)
        missing = max(0, exp - done)
        pct     = round(done / exp * 100) if exp > 0 else 0
        pct_color = BAD if pct < 80 else (WARN if pct < 95 else GOOD)
        summary = (
            f"Required: <b>{exp}</b>&nbsp;&nbsp;"
            f"Completed: <b>{done}</b>&nbsp;&nbsp;"
            f"Missing: <b>{missing}</b>&nbsp;&nbsp;"
            f"<span style='color:{pct_color};font-weight:800;'>{pct}%</span>"
        )
        drv_header = (
            f"<div style='display:flex;justify-content:space-between;align-items:baseline;"
            f"padding:18px 0 6px;border-bottom:2px solid {INK};margin-bottom:0;'>"
            f"<span style='font-size:13px;font-weight:700;color:{INK};letter-spacing:0.3px;'>"
            f"{drv}</span>"
            f"<span style='font-size:9.5px;color:{MUTE};margin-left:10px;'>"
            f"·&nbsp;{done} inspection{'s' if done != 1 else ''}</span>"
            f"<span style='flex:1;'></span>"
            f"<span style='font-size:11px;color:{INK};'>{summary}</span>"
            f"</div>"
        )
        tbody_rows = ""
        for r in rows:
            safe_cell = (
                f"<span style='color:{GOOD};font-weight:700;'>&#10003;</span>"
                if r["safe"] else
                f"<span style='color:{BAD};font-weight:700;'>&#9888;</span>"
            )
            def_color = f"color:{BAD};font-weight:700;" if r["defects"] > 0 else ""
            tbody_rows += (
                f"<tr>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};'>{r['dt']}</td>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'>{r['loc']}</td>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};text-align:right;'>{r['vehicle']}</td>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};text-align:right;'>{r['trailer']}</td>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};'>{r['type']}</td>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};text-align:center;'>{safe_cell}</td>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};text-align:right;'><span style='{def_color}'>{r['defects']}</span></td>"
                f"<td style='padding:7px 8px;font-size:11px;border-bottom:1px solid {LINE};color:{MUTE};'>{r['notes']}</td>"
                f"</tr>"
            )
        table = (
            f"<table width='100%' cellpadding='0' cellspacing='0' "
            f"style='border-collapse:collapse;margin-bottom:6px;'>"
            f"{thead}<tbody>{tbody_rows}</tbody></table>"
        )
        return drv_header + table

    if not driver_inspections:
        body = (
            f"<div style='padding:24px;'>"
            + _all_clear_row(
                "No DVIR inspection data for the last 14 days — "
                "DVIR_Inspections sheet will populate after the next Samsara refresh.",
                span=8)
            + f"</div>"
        )
    else:
        blocks = "".join(
            _driver_block(drv, rows)
            for drv, rows in sorted(driver_inspections.items()))
        body = f"<div style='padding:0 24px 24px;'>{blocks}</div>"

    return (
        header
        + f"<div style='padding:0 24px 4px;'>"
        + _section("DVIR inspection log — last 14 days")
        + f"</div>"
        + body
    )


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
                       date_str: str, prev_scores: dict | None = None) -> str:
    """Assemble the full safety report HTML matching the June 15 2026 format.

    Page order:
      1  Overview               (custom)
      2  Safety Metrics         (custom)
      3  Safety Events & HOS    (custom)
      4  DVIR Defects           (custom)
      5-6 Driver Compliance     (build_page9 from scorecard_email)
      7  Speed over Limit       (custom)
      8  Methodology            (custom)
      9  DVIR Inspection Compliance (custom)
      10-11 Tractor Inspections (build_page_equipment kind=tractors)
      12-13 Trailer Inspections (build_page_equipment kind=trailers)
      14 FMCSA CSA Scorecard    (build_csa_scorecard_page)
      15 Driver Safety Scores   (build_page2b)
      16+ Coached Events        (build_page_coached)
      N   DVIR Inspection Detail (custom — per-driver log last 7d)
      Last Knowledge Base       (custom)

    PDF page numbers come from the CSS @page counter(pages) automatically.
    The 'total' value in _sc_header is approximate for the email screen view.
    """
    metrics = compute_metrics(samsara)
    total = 23  # approximate for the email screen header

    pages: list[str] = []

    # 1 — Overview
    pages.append(build_page_overview(
        samsara, metrics, 1, total, date_str, samba, equipment,
        alvys_drivers=alvys_drivers, samsara_sheets=samsara_sheets,
        prev_scores=prev_scores))

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

    # 7 — Speed over Posted Limit (rich version: 6mo/3mo/MTD + driver comments)
    p2 = build_page2(samsara, date_str, pg=7)
    pages.append(_patch_pg_total(p2, total))

    # 8 — DVIR Inspection Compliance (per-driver done/expected/defects table)
    pages.append(build_page_dvir_compliance(samsara_sheets, 8, total, date_str))

    # 10-11 — Tractor Inspections (build_page_equipment accepts pg param)
    if equipment:
        tractor_html = build_page_equipment(equipment, date_str, kind="tractors", pg=10)
        pages.append(_patch_pg_total(tractor_html, total))
        trailer_html = build_page_equipment(equipment, date_str, kind="trailers", pg=12)
        pages.append(_patch_pg_total(trailer_html, total))
    else:
        pages.append(
            _sc_header("Equipment Compliance — Tractor Inspections",
                       10, total, date_str, "SAFETY")
            + _brief("Alvys Pipeline.xlsx not found on OneDrive — "
                     "equipment inspection data unavailable this run.", "mute"))
        pages.append(
            _sc_header("Equipment Compliance — Trailer Inspections",
                       12, total, date_str, "SAFETY")
            + _brief("Alvys Pipeline.xlsx not found on OneDrive — "
                     "equipment inspection data unavailable this run.", "mute"))

    # 14 — FMCSA CSA Scorecard
    csa_html = build_csa_scorecard_page(csa, date_str)
    pages.append(_patch_pg_total(csa_html, total))

    # 15 — Driver Safety Scores (build_page2b accepts pg param)
    scores_html = build_page2b(samsara, date_str, pg=15)
    pages.append(_patch_pg_total(scores_html, total))

    # 15+ — Coached Events (scorecard builder; pg=14 in its header, PDF correct)
    coached_html = build_page_coached(samsara, date_str)
    pages.append(_patch_pg_total(coached_html, total))

    # DVIR Inspection Detail (per-driver log, last 14 days)
    pages.append(build_page_dvir_detail(samsara_sheets, len(pages) + 1, total, date_str))

    # Second-to-last — Methodology & Data Sources
    pages.append(build_page_footnote(len(pages) + 1, total, date_str))

    # Last — Knowledge Base & Playbooks
    pages.append(build_page_knowledge_base(len(pages) + 1, total, date_str))

    pb = "<div class='page-break' style='page-break-after:always;break-after:page;height:0;'></div>"
    _head = (
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
    )
    _tail = "</body></html>"
    # Email body: first 6 pages only (overview → DVIR defects → driver compliance).
    # Full report goes in the PDF attachment — keeps email concise and scannable.
    email_html = _head + pb.join(pages[:6]) + _tail
    pdf_html   = _head + pb.join(pages)     + _tail
    return email_html, pdf_html


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
    cc_emails = [e.strip() for e in
                 os.environ.get("SAFETY_CC_EMAILS", "").split(",")
                 if e.strip()]
    log.info("Recipients: TO=%s CC=%s", to_emails, cc_emails)

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

    # Read yesterday's scores for trend comparison (missing = first run, no items generated)
    yesterday = today - datetime.timedelta(days=1)
    prev_scores = _read_prev_scores(tok, upn, yesterday)
    log.info("Previous scores loaded: %d drivers", len(prev_scores))

    # Build structured accountability items (for Teams cards + history)
    m_dict = compute_metrics(samsara)
    audra_items, ops_items = _build_accountability_structured(
        m_dict, samsara, samba, equipment, alvys_drivers, samsara_sheets)
    log.info("Accountability items: %d audra, %d ops", len(audra_items), len(ops_items))

    # Load history for carry-forward + occurrence counting
    acc_history = _load_accountability_history(tok, upn, today)
    log.info("Accountability history loaded: %d items over 30d", len(acc_history))

    # Write accountability JSON (local output/ + OneDrive/Safety/)
    _write_accountability_json(today, audra_items, ops_items, acc_history, tok, upn)

    email_html, pdf_html = _build_html_report(
        samsara, samsara_sheets, samba, csa, equipment, alvys_drivers,
        date_str, prev_scores=prev_scores)
    pdf = _render_pdf(pdf_html)

    subj = f"XFreight Safety & Compliance Report — {today.strftime('%B %-d, %Y')}"
    attachments = None
    if pdf:
        log.info("Generated PDF (%.1f KB)", len(pdf) / 1024)
        attachments = [{
            "name": f"safety-compliance-{today.isoformat()}.pdf",
            "content_bytes": pdf,
            "mime": "application/pdf",
        }]
    send_email(tok, upn, to_emails, subj, email_html, attachments=attachments,
               cc_emails=cc_emails or None)

    # Persist today's scores so tomorrow's run can detect improvements / declines
    scores_all = ((samsara or {}).get("fleet") or {}).get("scores_all") or []
    _write_scores(tok, upn, today, scores_all)
    log.info("Scores written: %d drivers", len(scores_all))

    _write_marker(tok, upn, today,
                  f"sent={len(to_emails)} pdf={'yes' if pdf else 'no'}")
    log.info("Marker written: %s", _marker_path(today))
    return 0


if __name__ == "__main__":
    sys.exit(main())
