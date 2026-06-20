"""Weekly Risk & Decisions report — a SECONDARY email, separate from the daily
executive brief.

v2: reads KPI_History/KPI_Trend.xlsx from OneDrive and renders a 4-week trend
table at the top of the email.  If ANTHROPIC_API_KEY is set, calls claude-haiku
to generate 3 tailored decision prompts from the live numbers; otherwise falls
back to the static prompts.

    python -m src.decision_report          # build + send
    python -m src.decision_report --dry     # build + write /tmp preview, no send
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
from datetime import datetime, date
from operator import ge as _op_ge, gt as _op_gt, le as _op_le, lt as _op_lt, eq as _op_eq
from zoneinfo import ZoneInfo

import yaml

from dotenv import load_dotenv

from src.onedrive_upload import download_file as _od_download, get_token
from src.scorecard_email import (send_email, XFREIGHT_RED, INK, MUTE, LINE,
                                  GOOD, GOODBG, WARN, WARNBG, BAD, BADBG,
                                  FONT, FONT_SERIF,
                                  TARGET_RPM, TARGET_DEADHEAD)

log = logging.getLogger("decision_report")

WIKI_DIR = os.environ.get("DECISION_REPORT_WIKI_DIR", "Karpathy-Wiki/wiki")

_XF_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 220 38' width='150' height='26' "
    "role='img' aria-label='XFreight'><rect width='220' height='38' rx='2' fill='#c41e2a'/>"
    "<g fill='#fff'><rect x='8' y='6' width='38' height='2.4'/><rect x='10' y='10' width='34' height='2.4'/>"
    "<rect x='6' y='14' width='42' height='2.4'/><rect x='12' y='18' width='30' height='2.4'/>"
    "<rect x='8' y='22' width='38' height='2.4'/><rect x='10' y='26' width='34' height='2.4'/>"
    "<rect x='6' y='30' width='42' height='2.4'/></g><text x='56' y='27' "
    "font-family='Helvetica,Arial,sans-serif' font-weight='900' font-style='italic' "
    "font-size='22' letter-spacing='-0.5' fill='#fff'>XFREIGHT</text></svg>"
)

# Scenario modeling constants.  RPM + deadhead targets imported from scorecard_email
# (where they're pulled from the Goals workbooks) so the scenario cards stay in sync
# with the official goals automatically.  Override via env only if you need to test.
_RPM_TARGET          = float(os.environ.get("SCENARIO_RPM_TARGET",          str(TARGET_RPM)))
# 5.75% is the operational goal (buffer below the 6% ceiling in TARGET_DEADHEAD)
_DH_TARGET_PCT       = float(os.environ.get("SCENARIO_DH_TARGET_PCT",       "5.75"))
_COST_PER_EMPTY_MILE = float(os.environ.get("SCENARIO_COST_PER_EMPTY_MILE", "1.20"))
_AR_COLLECT_RATE     = float(os.environ.get("SCENARIO_AR_COLLECT_RATE",      "0.50"))

# Fallback static prompts — used when ANTHROPIC_API_KEY is absent.
_STATIC_PROMPTS = [
    ("Review my top risks",
     "Walk me through XFreight's current top risks from the risk register and what I should do about each this week."),
    ("Grade open decisions",
     "Help me grade the open decisions in XFreight's decision journal — which assumptions should I re-check, and which outcomes can we measure now?"),
    ("Quantify customer concentration",
     "Help me quantify XFreight's customer concentration — what share of X-Trux + X-Linx revenue each top customer represents, and at what point it becomes a real risk."),
]


def _claude_link(prompt: str) -> str:
    from urllib.parse import quote
    return f"https://claude.ai/new?q={quote(prompt)}"


# ----------------------------------------------------------------------
# KPI trend — load from OneDrive + render 4-week table
# ----------------------------------------------------------------------

import pandas as pd  # noqa: E402 (after stdlib imports above)


def _load_kpi_trend(tok: str, upn: str) -> pd.DataFrame | None:
    try:
        raw = _od_download(tok, upn, "KPI_History/KPI_Trend.xlsx")
        df = pd.read_excel(io.BytesIO(raw))
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).sort_values("Date")
        return df
    except Exception as exc:
        log.info("KPI trend not yet available: %s", exc)
        return None


def _delta_arrow(current, prior) -> str:
    """↑ / ↓ / — based on numeric direction."""
    try:
        c, p = float(current), float(prior)
        if c > p:
            return f"<span style='color:{GOOD};'>&#9650;</span>"
        if c < p:
            return f"<span style='color:{BAD};'>&#9660;</span>"
        return "—"
    except (TypeError, ValueError):
        return "—"


def _fmt(val, fmt: str = ".0f", prefix: str = "", suffix: str = "") -> str:
    try:
        return f"{prefix}{float(val):{fmt}}{suffix}"
    except (TypeError, ValueError):
        return "—"


_KPI_DEFS = [
    # (column, label, fmt, prefix, suffix, lower_is_better)
    ("LoadsMTD",        "Loads MTD",          ".0f",  "",  "",   False),
    ("RevenueTotalMTD", "Revenue MTD",         ",.0f", "$", "",   False),
    ("RPM_OwnFleet",    "RPM (own fleet)",     ".4f",  "$", "",   False),
    ("DeadheadPct",     "Deadhead %",          ".2f",  "",  "%",  True),
    ("AR_Open",         "AR Open",             ",.0f", "$", "",   True),
    ("AR_60Plus",       "AR 60+ Days",         ",.0f", "$", "",   True),
    ("AP_GapCount",     "Ramp AP Gap (bills)", ".0f",  "",  "",   True),
    ("AP_GapAmount",    "Ramp AP Gap ($)",     ",.0f", "$", "",   True),
    ("FleetSafetyScore","Fleet Safety Score",  ".1f",  "",  "",   False),
]


def _render_kpi_table(trend: pd.DataFrame) -> str:
    """4-week snapshot table with week-over-week delta arrows."""
    if trend is None or trend.empty:
        return ""
    # Take the last 4 distinct Friday-ish snapshots (one per week).
    # Since we append daily, group by ISO week and take the last row each week.
    trend = trend.copy()
    trend["Week"] = trend["Date"].dt.isocalendar().week.astype(str) + "-" + \
                    trend["Date"].dt.isocalendar().year.astype(str)
    by_week = trend.groupby("Week", sort=False).last().reset_index()
    by_week = by_week.sort_values("Date").tail(4).reset_index(drop=True)

    if len(by_week) < 1:
        return ""

    # Header row: metric name + one column per week
    week_labels = [row["Date"].strftime("%-m/%-d") for _, row in by_week.iterrows()]
    th_cells = "".join(
        f"<th style='text-align:right;padding:6px 10px;font-size:11px;"
        f"text-transform:uppercase;letter-spacing:.4px;color:{MUTE};"
        f"border-bottom:2px solid {LINE};'>{w}</th>"
        for w in week_labels
    )
    header = (
        f"<tr>"
        f"<th style='text-align:left;padding:6px 10px;font-size:11px;"
        f"text-transform:uppercase;letter-spacing:.4px;color:{MUTE};"
        f"border-bottom:2px solid {LINE};'>Metric</th>"
        + th_cells + "</tr>"
    )

    rows_html = ""
    for col, label, fmt, prefix, suffix, lower_better in _KPI_DEFS:
        if col not in by_week.columns:
            continue
        vals = by_week[col].tolist()
        cells = ""
        for i, v in enumerate(vals):
            formatted = _fmt(v, fmt, prefix, suffix)
            arrow = ""
            if i > 0:
                better = (v < vals[i-1]) if lower_better else (v > vals[i-1])
                worse  = (v > vals[i-1]) if lower_better else (v < vals[i-1])
                if better:
                    arrow = f"&nbsp;<span style='color:{GOOD};font-size:10px;'>&#9650;</span>"
                elif worse:
                    arrow = f"&nbsp;<span style='color:{BAD};font-size:10px;'>&#9660;</span>"
            cells += (
                f"<td style='text-align:right;padding:6px 10px;font-size:13px;"
                f"border-bottom:1px solid {LINE};'>{formatted}{arrow}</td>"
            )
        bg = "#f8fafc" if len(rows_html) % 200 < 100 else "#fff"
        rows_html += (
            f"<tr style='background:#fff;'>"
            f"<td style='padding:6px 10px;font-size:13px;color:{INK};"
            f"border-bottom:1px solid {LINE};font-weight:500;'>{label}</td>"
            + cells + "</tr>"
        )

    table = (
        f"<h2 style='{FONT_SERIF}font-size:16px;font-weight:400;color:{INK};"
        f"margin:22px 0 8px;border-bottom:1px solid {LINE};padding-bottom:4px;'>"
        f"KPI Snapshot — last 4 weeks</h2>"
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-collapse:collapse;margin:0 0 18px;'>"
        f"<thead>{header}</thead><tbody>{rows_html}</tbody></table>"
        f"<div style='font-size:11px;color:{MUTE};margin-bottom:18px;'>"
        f"&#9650; = improved vs prior week &nbsp;&nbsp; &#9660; = declined. "
        f"Deadhead % and AP gap: lower is better.</div>"
    )
    return table


# ----------------------------------------------------------------------
# Scenario modeling — 3 forward-looking what-if calculations
# ----------------------------------------------------------------------

def _safe_float(v) -> "float | None":
    try:
        f = float(v)
        return None if f != f else f  # NaN guard
    except (TypeError, ValueError):
        return None


def _build_scenarios(trend: "pd.DataFrame | None") -> list:
    """Compute 3 scenarios from the latest KPI row.
    Returns an empty list if data is insufficient."""
    if trend is None or trend.empty:
        return []
    latest = trend.iloc[-1]
    out = []

    rpm    = _safe_float(latest.get("RPM_OwnFleet"))
    rev    = _safe_float(latest.get("RevenueXTruxMTD"))
    dh     = _safe_float(latest.get("DeadheadPct"))
    ar60   = _safe_float(latest.get("AR_60Plus"))

    # 1. RPM lift — only if below target
    if rpm and rpm > 0 and rev and rev > 0 and _RPM_TARGET > rpm:
        miles = rev / rpm
        delta = (_RPM_TARGET - rpm) * miles
        out.append({
            "kind": "Revenue",
            "label": f"Raise RPM to ${_RPM_TARGET:.2f}",
            "impact": f"+${delta:,.0f}/mo",
            "desc": (f"Rate gap ${rpm:.4f} → ${_RPM_TARGET:.2f}/mi "
                     f"on {miles:,.0f} est. own-fleet miles MTD"),
        })

    # 2. Deadhead cut — only if above target
    if dh and dh > _DH_TARGET_PCT and rpm and rpm > 0 and rev:
        miles = rev / rpm
        saved = (dh - _DH_TARGET_PCT) / 100 * miles
        savings = saved * _COST_PER_EMPTY_MILE
        out.append({
            "kind": "Cost",
            "label": f"Cut Deadhead {dh:.1f}% → {_DH_TARGET_PCT}%",
            "impact": f"+${savings:,.0f}/mo",
            "desc": (f"{saved:,.0f} fewer empty miles "
                     f"× ${_COST_PER_EMPTY_MILE:.2f}/mi cost saved"),
        })

    # 3. AR 60+ collection
    if ar60 and ar60 > 0:
        cash = ar60 * _AR_COLLECT_RATE
        out.append({
            "kind": "Cash",
            "label": f"Collect {int(_AR_COLLECT_RATE*100)}% of 60+ AR",
            "impact": f"+${cash:,.0f} cash",
            "desc": (f"${ar60:,.0f} overdue × "
                     f"{int(_AR_COLLECT_RATE*100)}% assumed collectible"),
        })

    return out


def _build_scenario_text(scenarios: list) -> str:
    if not scenarios:
        return ""
    lines = ["Scenario modeling (this month's opportunity set):"]
    for s in scenarios:
        lines.append(f"  {s['label']}: {s['impact']} — {s['desc']}")
    return "\n".join(lines)


def _render_scenario_table(scenarios: list) -> str:
    if not scenarios:
        return ""
    n = len(scenarios)
    col_w = f"{100 // n}%"

    def _card(s: dict, i: int) -> str:
        pad = (
            "0 8px 0 0" if i == 0
            else "0 0 0 8px" if i == n - 1
            else "0 4px"
        )
        return (
            f"<td width='{col_w}' style='padding:{pad};vertical-align:top;'>"
            f"<div style='background:#f8fafc;border:1px solid {LINE};"
            f"border-radius:8px;padding:12px 14px;'>"
            f"<div style='font-size:10px;text-transform:uppercase;letter-spacing:.5px;"
            f"color:{MUTE};margin-bottom:6px;'>{s['kind']}</div>"
            f"<div style='font-size:22px;font-weight:700;color:{GOOD};line-height:1.1;"
            f"margin-bottom:4px;'>{s['impact']}</div>"
            f"<div style='font-size:12px;font-weight:600;color:{INK};margin-bottom:6px;'>"
            f"{s['label']}</div>"
            f"<div style='font-size:11px;color:{MUTE};border-top:1px solid {LINE};"
            f"padding-top:6px;'>{s['desc']}</div>"
            f"</div></td>"
        )

    tds = "".join(_card(s, i) for i, s in enumerate(scenarios))
    heading = (
        f"<h2 style='{FONT_SERIF}font-size:16px;font-weight:400;color:{INK};"
        f"margin:22px 0 10px;border-bottom:1px solid {LINE};padding-bottom:4px;'>"
        f"What-If Scenarios — this month</h2>"
    )
    table = (
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-collapse:collapse;margin:0 0 6px;'>"
        f"<tr>{tds}</tr></table>"
    )
    note = (
        f"<div style='font-size:11px;color:{MUTE};margin-bottom:18px;'>"
        f"RPM target ${_RPM_TARGET:.2f}/mi &middot; deadhead target {_DH_TARGET_PCT}% &middot; "
        f"AR collect rate {int(_AR_COLLECT_RATE*100)}% &middot; "
        f"empty-mile cost est. ${_COST_PER_EMPTY_MILE:.2f}/mi.</div>"
    )
    return heading + table + note


# ----------------------------------------------------------------------
# Claude synthesis — generate 3 tailored decision prompts from live data
# ----------------------------------------------------------------------

def _build_kpi_snapshot_text(trend: pd.DataFrame | None) -> str:
    """Flat text summary of the latest KPI row for Claude's context window."""
    if trend is None or trend.empty:
        return "KPI data not yet available."
    latest = trend.iloc[-1]
    prior  = trend.iloc[-2] if len(trend) >= 2 else None
    lines  = [f"XFreight KPI snapshot as of {latest['Date'].strftime('%Y-%m-%d')}:"]
    for col, label, fmt, prefix, suffix, _ in _KPI_DEFS:
        val = latest.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        formatted = _fmt(val, fmt, prefix, suffix)
        delta = ""
        if prior is not None:
            prev = prior.get(col)
            try:
                pct = (float(val) - float(prev)) / abs(float(prev)) * 100 if prev else 0
                delta = f" ({pct:+.1f}% vs prior week)"
            except (TypeError, ValueError):
                pass
        lines.append(f"  {label}: {formatted}{delta}")
    return "\n".join(lines)


def _generate_decision_prompts(trend: "pd.DataFrame | None",
                                risk_md: str,
                                scenarios: list | None = None) -> list[tuple[str, str]]:
    """Call claude-haiku to generate 3 tailored decision prompts.
    Falls back to _STATIC_PROMPTS if ANTHROPIC_API_KEY is absent or the call fails."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.info("ANTHROPIC_API_KEY not set — using static decision prompts.")
        return _STATIC_PROMPTS

    snapshot_text = _build_kpi_snapshot_text(trend)
    # Trim risk register to first 3000 chars so it fits in haiku's context cheaply
    risk_excerpt = risk_md[:3000] if risk_md else "Risk register not available."

    system = (
        "You are a strategic advisor to XFreight, a small trucking company with two "
        "operating entities (X-Trux asset carrier + X-Linx brokerage). Your job is to "
        "generate exactly 3 short, specific, actionable decision prompts for the owner "
        "this week based on current KPI data and the risk register. Each prompt should "
        "be 10-20 words, start with an action verb, and reference a real number from "
        "the KPI snapshot. Return ONLY a JSON array of 3 objects: "
        '[{"label": "short button label (3-5 words)", "prompt": "full question for Claude"}].'
        " Do not include any explanation outside the JSON array."
    )
    scenario_text = _build_scenario_text(scenarios or [])
    user = (
        f"{snapshot_text}\n\n"
        + (f"{scenario_text}\n\n" if scenario_text else "")
        + f"Risk register excerpt:\n{risk_excerpt}\n\n"
        + "Generate 3 decision prompts for this week — "
        + "reference specific scenario dollar amounts where relevant."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        import json
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.DOTALL).strip()
        items = json.loads(raw)
        result = [(str(i.get("label", "")).strip(),
                   str(i.get("prompt", "")).strip()) for i in items[:3]]
        if all(label and prompt for label, prompt in result):
            log.info("Claude generated %d tailored decision prompts.", len(result))
            return result
    except Exception as exc:
        log.warning("Claude API call failed — using static prompts: %s", exc)

    return _STATIC_PROMPTS


# ----------------------------------------------------------------------
# Decision grading — reads decision-outcomes.yml, grades against KPI trend
# ----------------------------------------------------------------------

_OUTCOMES_YML  = "Karpathy-Wiki/wiki/decision-outcomes.yml"
_GRADE_JSON    = "Karpathy-Wiki/wiki/decision-grades.json"

# Maps metric dot-paths from decision-outcomes.yml to KPI trend column names.
# Add entries here as new metrics land in the KPI trend.
_METRIC_MAP = {
    "DeadheadPct":                      "DeadheadPct",
    "RPM_OwnFleet":                     "RPM_OwnFleet",
    "AR_Open":                          "AR_Open",
    "AR_60Plus":                        "AR_60Plus",
    "AP_GapCount":                      "AP_GapCount",
    "AP_GapAmount":                     "AP_GapAmount",
    "FleetSafetyScore":                 "FleetSafetyScore",
    "LoadsMTD":                         "LoadsMTD",
    "RevenueTotalMTD":                  "RevenueTotalMTD",
    # Legacy dot-path aliases in the original outcomes.yml
    "alvys.dead_head_pct":              "DeadheadPct",
    # Not yet in KPI trend — grade stays pending until added
    "alvys_entities.X-Trux.margin_pct": None,
    "equipment.tractors_overdue_annual": None,
}

_GRADE_EMOJI = {"confirmed": "✓", "mixed": "~", "wrong": "✗", "pending": "⏳"}
_GRADE_COLOR = {"confirmed": GOOD, "mixed": WARN, "wrong": BAD, "pending": MUTE}

_OPS = {">=": _op_ge, ">": _op_gt, "<=": _op_le, "<": _op_lt, "==": _op_eq}


def _load_outcomes() -> list:
    try:
        with open(_OUTCOMES_YML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return (data or {}).get("decisions", [])
    except Exception as exc:
        log.info("decision-outcomes.yml not readable: %s", exc)
        return []


def _grade_one(decision: dict, latest: dict) -> "tuple[str, str]":
    try:
        check_after = date.fromisoformat(str(decision.get("check_after", "")))
    except ValueError:
        return "pending", "Invalid check_after date"

    if date.today() < check_after:
        return "pending", f"{(check_after - date.today()).days}d until check"

    check  = decision.get("check", {})
    metric = check.get("metric", "")
    col    = _METRIC_MAP.get(metric)
    if col is None:
        return "pending", f"'{metric}' not yet in KPI trend"

    raw = latest.get(col)
    if raw is None or (isinstance(raw, float) and raw != raw):
        return "pending", f"No data for {col}"

    value = float(raw)
    kind  = check.get("kind", "")

    if kind == "range":
        lo, hi = check.get("min"), check.get("max")
        if lo is not None and value < float(lo):
            return ("wrong" if check.get("wrong_below") else "mixed"), \
                   f"{col}={value:.4g} below min {lo}"
        if hi is not None and value > float(hi):
            return ("wrong" if check.get("wrong_above") else "mixed"), \
                   f"{col}={value:.4g} above max {hi}"
        return "confirmed", f"{col}={value:.4g} in [{lo}, {hi}]"

    if kind == "comparison":
        direction  = check.get("direction", ">=")
        threshold  = float(check.get("threshold", 0))
        passes     = _OPS.get(direction, _op_ge)(value, threshold)
        grade      = check.get("on_pass" if passes else "on_fail", "pending")
        arrow      = "✓" if passes else "✗"
        return grade, f"{col}={value:.4g} {direction} {threshold} {arrow}"

    return "pending", "Unknown check kind"


def _grade_decisions(trend: "pd.DataFrame | None", outcomes: list) -> dict:
    """Grade every outcome entry against the latest KPI row."""
    if not outcomes:
        return {}
    latest: dict = {}
    if trend is not None and not trend.empty:
        row = trend.iloc[-1]
        latest = {c: row.get(c) for c in trend.columns}

    grades = {}
    for d in outcomes:
        did         = d.get("id", "unknown")
        grade, why  = _grade_one(d, latest)
        grades[did] = {
            "title":        d.get("title", did),
            "journal_date": d.get("journal_date", ""),
            "grade":        grade,
            "reason":       why,
        }
    return grades


def _write_grades(grades: dict) -> None:
    try:
        payload = {"generated": date.today().isoformat(), "grades": grades}
        with open(_GRADE_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        log.info("Wrote decision grades → %s", _GRADE_JSON)
    except Exception as exc:
        log.warning("Could not write decision-grades.json: %s", exc)


def _render_grades_section(grades: dict) -> str:
    if not grades:
        return ""
    rows_html = ""
    for g in grades.values():
        grade = g["grade"]
        emoji = _GRADE_EMOJI.get(grade, "⏳")
        color = _GRADE_COLOR.get(grade, MUTE)
        rows_html += (
            f"<tr style='background:#fff;'>"
            f"<td style='padding:6px 10px;font-size:12px;color:{MUTE};"
            f"border-bottom:1px solid {LINE};white-space:nowrap;'>{g['journal_date']}</td>"
            f"<td style='padding:6px 10px;font-size:13px;border-bottom:1px solid {LINE};'>"
            f"{g['title']}</td>"
            f"<td style='padding:6px 10px;font-size:13px;font-weight:700;color:{color};"
            f"text-align:center;border-bottom:1px solid {LINE};'>{emoji} {grade}</td>"
            f"<td style='padding:6px 10px;font-size:11px;color:{MUTE};"
            f"border-bottom:1px solid {LINE};'>{g['reason']}</td>"
            f"</tr>"
        )
    th_style = (f"text-align:left;padding:6px 10px;font-size:11px;text-transform:uppercase;"
                f"letter-spacing:.4px;color:{MUTE};border-bottom:2px solid {LINE};")
    header = (
        f"<h2 style='{FONT_SERIF}font-size:16px;font-weight:400;color:{INK};"
        f"margin:22px 0 8px;border-bottom:1px solid {LINE};padding-bottom:4px;'>"
        f"Decision grades</h2>"
        f"<table width='100%' cellpadding='0' cellspacing='0' "
        f"style='border-collapse:collapse;margin:0 0 6px;'>"
        f"<thead><tr>"
        f"<th style='{th_style}'>Date</th>"
        f"<th style='{th_style}'>Decision</th>"
        f"<th style='{th_style}text-align:center;'>Grade</th>"
        f"<th style='{th_style}'>Basis (live KPI data)</th>"
        f"</tr></thead><tbody>{rows_html}</tbody></table>"
    )
    note = (
        f"<div style='font-size:11px;color:{MUTE};margin-bottom:18px;'>"
        f"✓ confirmed &nbsp;&nbsp; ~ mixed &nbsp;&nbsp; ✗ wrong &nbsp;&nbsp; ⏳ pending. "
        f"Graded from KPI trend. Metrics not yet in the trend remain pending.</div>"
    )
    return header + note


# ----------------------------------------------------------------------
# CFO narrative — Claude writes a 3-4 sentence executive summary
# ----------------------------------------------------------------------

def _compute_kpi_deltas(trend: "pd.DataFrame | None") -> list:
    """Week-over-week delta for each KPI, sorted by alert severity then magnitude."""
    if trend is None or len(trend) < 2:
        return []
    latest, prior = trend.iloc[-1], trend.iloc[-2]
    deltas = []
    for col, label, fmt, prefix, suffix, lower_better in _KPI_DEFS:
        curr = _safe_float(latest.get(col))
        prev = _safe_float(prior.get(col))
        if curr is None or prev is None or prev == 0:
            continue
        delta_pct = (curr - prev) / abs(prev)
        # A movement is an "alert" if it worsened by >10%
        worsened_pct = delta_pct if lower_better else -delta_pct
        deltas.append({
            "label":       label,
            "current":     curr,
            "prior":       prev,
            "delta_pct":   delta_pct,
            "direction":   ("improved" if (delta_pct < 0 if lower_better else delta_pct > 0)
                            else "declined"),
            "is_alert":    worsened_pct > 0.10,
            "fmt": fmt, "prefix": prefix, "suffix": suffix,
        })
    deltas.sort(key=lambda d: (not d["is_alert"], -abs(d["delta_pct"])))
    return deltas


def _generate_cfo_narrative(trend: "pd.DataFrame | None",
                             scenarios: list,
                             grades: dict) -> str:
    """Call Claude haiku for a 3-4 sentence CFO executive summary. Returns plain text."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or trend is None or trend.empty:
        return ""

    snapshot = _build_kpi_snapshot_text(trend)
    deltas   = _compute_kpi_deltas(trend)

    delta_lines = []
    for d in deltas[:7]:
        curr_s = _fmt(d["current"], d["fmt"], d["prefix"], d["suffix"])
        prev_s = _fmt(d["prior"],   d["fmt"], d["prefix"], d["suffix"])
        delta_lines.append(
            f"  {d['label']}: {prev_s} → {curr_s} "
            f"({d['delta_pct']:+.1%}, {d['direction']}"
            + (" ⚠ ALERT" if d["is_alert"] else "") + ")"
        )

    grade_lines = [
        f"  {g['title']}: {g['grade']} — {g['reason']}"
        for g in grades.values() if g["grade"] != "pending"
    ]

    user_parts = [snapshot]
    if delta_lines:
        user_parts.append("Week-over-week changes:\n" + "\n".join(delta_lines))
    scenario_text = _build_scenario_text(scenarios or [])
    if scenario_text:
        user_parts.append(scenario_text)
    if grade_lines:
        user_parts.append("Decision grades this week:\n" + "\n".join(grade_lines))
    user_parts.append("Write the executive briefing.")

    system = (
        "You are the CFO of XFreight, a small trucking company "
        "(X-Trux asset carrier + X-Linx brokerage, Sioux Falls SD). "
        "Write a 3-4 sentence executive briefing for the Monday morning meeting. "
        "Be specific: name the metric, the direction, and the dollar or percentage impact. "
        "Call out any ⚠ ALERT items first. End with the single most important action this week. "
        "Plain business prose only — no bullet points, no markdown headers."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=280,
            system=system,
            messages=[{"role": "user", "content": "\n\n".join(user_parts)}],
        )
        narrative = msg.content[0].text.strip()
        log.info("Claude generated CFO narrative (%d chars).", len(narrative))
        return narrative
    except Exception as exc:
        log.warning("CFO narrative failed: %s", exc)
        return ""


def _render_cfo_narrative(narrative: str) -> str:
    if not narrative:
        return ""
    return (
        f"<div style='background:#f8f9fc;border-left:4px solid {XFREIGHT_RED};"
        f"border-radius:0 6px 6px 0;padding:14px 16px;margin:16px 0 20px;'>"
        f"<div style='font-size:10px;text-transform:uppercase;letter-spacing:.5px;"
        f"color:{MUTE};margin-bottom:8px;'>Executive summary — this week</div>"
        f"<div style='font-size:14px;color:{INK};line-height:1.65;'>{narrative}</div>"
        f"</div>"
    )


# ----------------------------------------------------------------------
# Minimal markdown -> inline-styled HTML (the subset our wiki pages use).
# Inline styles + table layout keep it email-client safe (Outlook/Gmail).
# ----------------------------------------------------------------------
def _inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                  rf"<a href='\2' style='color:{XFREIGHT_RED};'>\1</a>", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)          # KB-internal links -> plain
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", rf"<em style='color:{MUTE};'>\1</em>", text)
    text = re.sub(r"`([^`]+)`",
                  r"<code style='background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:12px;'>\1</code>", text)
    return text


def _split_row(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _render_table(rows: list[str]) -> str:
    header = _split_row(rows[0])
    th = "".join(
        f"<th style='text-align:left;padding:7px 10px;font-size:11px;text-transform:uppercase;"
        f"letter-spacing:.4px;color:{MUTE};border-bottom:2px solid {LINE};'>{_inline(h)}</th>"
        for h in header)
    trs = []
    for k, r in enumerate(rows[2:]):           # skip header + |---| separator
        bg = "#f8fafc" if k % 2 == 0 else "#fff"
        tds = "".join(
            f"<td style='padding:7px 10px;font-size:13px;border-bottom:1px solid {LINE};"
            f"vertical-align:top;'>{_inline(c)}</td>" for c in _split_row(r))
        trs.append(f"<tr style='background:{bg};'>{tds}</tr>")
    return (f"<table width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;"
            f"margin:10px 0 16px;'><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>")


_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _md_to_html(md: str) -> str:
    lines = md.split("\n")
    if lines and lines[0].strip() == "---":                 # strip YAML frontmatter
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is not None:
            lines = lines[end + 1:]
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s.startswith("|") and i + 1 < n and _SEP_RE.match(lines[i + 1]) and "-" in lines[i + 1]:
            tbl = []
            while i < n and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            out.append(_render_table(tbl))
            continue
        if s == "---":
            out.append(f"<hr style='border:none;border-top:1px solid {LINE};margin:20px 0;'>")
            i += 1
            continue
        if s.startswith("### "):
            out.append(f"<h3 style='{FONT_SERIF}font-size:15px;font-weight:600;color:{INK};margin:16px 0 4px;'>{_inline(s[4:])}</h3>")
            i += 1
            continue
        if s.startswith("## "):
            out.append(f"<h2 style='{FONT_SERIF}font-size:18px;font-weight:400;color:{INK};margin:22px 0 6px;border-bottom:1px solid {LINE};padding-bottom:4px;'>{_inline(s[3:])}</h2>")
            i += 1
            continue
        if s.startswith("# "):
            out.append(f"<h1 style='{FONT_SERIF}font-size:21px;font-weight:400;color:{INK};margin:6px 0 8px;'>{_inline(s[2:])}</h1>")
            i += 1
            continue
        if s.startswith(">"):
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<div style='background:#f8fafc;border-left:3px solid {LINE};padding:10px 14px;"
                       f"margin:10px 0;font-size:12px;color:{MUTE};'>{_inline(' '.join(quote))}</div>")
            continue
        if s.startswith("- "):
            items = []
            while i < n and lines[i].strip().startswith("- "):
                items.append(f"<li style='margin:3px 0;'>{_inline(lines[i].strip()[2:])}</li>")
                i += 1
            out.append(f"<ul style='font-size:13px;color:{INK};line-height:1.5;margin:8px 0;padding-left:20px;'>{''.join(items)}</ul>")
            continue
        out.append(f"<p style='font-size:13px;color:{INK};line-height:1.6;margin:8px 0;'>{_inline(s)}</p>")
        i += 1
    return "\n".join(out)


# ----------------------------------------------------------------------
# Report shell
# ----------------------------------------------------------------------
def _claude_section(prompts: list[tuple[str, str]] | None = None) -> str:
    prompts = prompts or _STATIC_PROMPTS
    btns = []
    for label, prompt in prompts:
        href = _claude_link(prompt)
        btns.append(
            f"<a href='{href}' style='display:inline-block;background:{XFREIGHT_RED};color:#fff;"
            f"text-decoration:none;font-size:12px;font-weight:700;padding:8px 14px;border-radius:6px;"
            f"margin:0 8px 8px 0;'>{label} &rarr;</a>")
    return (f"<div style='background:{GOODBG};border:1px solid #cfe6d8;border-radius:8px;padding:14px 16px;margin:14px 0 18px;'>"
            f"<div style='font-size:13px;font-weight:700;color:{INK};margin-bottom:8px;'>Decisions to consider this week</div>"
            f"<div>{''.join(btns)}</div>"
            f"<div style='font-size:11px;color:{MUTE};margin-top:4px;'>Each opens a new Claude chat with a starter question you can edit. "
            f"If the prompt doesn't carry over, it's listed at the bottom of this email to copy.</div></div>")


def _prompt_appendix(prompts: list[tuple[str, str]] | None = None) -> str:
    prompts = prompts or _STATIC_PROMPTS
    rows = "".join(
        f"<div style='margin:6px 0;'><span style='font-weight:700;color:{INK};font-size:12px;'>{label}:</span> "
        f"<span style='color:{MUTE};font-size:12px;'>{prompt}</span></div>"
        for label, prompt in prompts)
    return (f"<div style='margin-top:18px;border-top:1px solid {LINE};padding-top:12px;'>"
            f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:{MUTE};margin-bottom:6px;'>"
            f"Starter prompts (copy into Claude)</div>{rows}</div>")


def build_decision_report(date_str: str, risk_md: str, decision_md: str,
                           kpi_trend: "pd.DataFrame | None" = None,
                           prompts: "list[tuple[str, str]] | None" = None,
                           scenarios: "list | None" = None,
                           grades: "dict | None" = None,
                           narrative: str = "") -> str:
    header = (
        f"<table width='100%' cellpadding='0' cellspacing='0' style='border-bottom:4px solid {XFREIGHT_RED};padding:6px 0 14px;'>"
        f"<tr><td valign='middle'>{_XF_SVG}"
        f"<div style='{FONT_SERIF}font-style:italic;font-size:16px;color:{INK};margin-top:8px;'>Risk &amp; Decisions Report</div>"
        f"<div style='font-size:12px;color:{MUTE};margin-top:2px;'>Weekly &middot; separate from the daily executive brief</div></td>"
        f"<td align='right' valign='middle' style='font-size:11px;color:{MUTE};'>{date_str}</td></tr></table>")
    kpi_html      = _render_kpi_table(kpi_trend)
    scenario_html = _render_scenario_table(scenarios or [])
    grades_html   = _render_grades_section(grades or {})
    narrative_html = _render_cfo_narrative(narrative)
    risk_html     = _md_to_html(risk_md) if risk_md else f"<p style='color:{MUTE};'>Risk register not found.</p>"
    decision_html = _md_to_html(decision_md) if decision_md else f"<p style='color:{MUTE};'>Decision journal not found.</p>"
    return (
        f"<div style=\"max-width:720px;margin:0 auto;padding:8px 18px 24px;{FONT}\">"
        f"{header}"
        f"{narrative_html}"
        f"{kpi_html}"
        f"{scenario_html}"
        f"{grades_html}"
        f"{_claude_section(prompts)}"
        f"{risk_html}"
        f"<div style='height:8px;'></div>"
        f"{decision_html}"
        f"{_prompt_appendix(prompts)}"
        f"<div style='margin-top:18px;border-top:1px solid {LINE};padding-top:10px;font-size:11px;color:{MUTE};'>"
        f"Source: Karpathy-Wiki knowledge base (Risk Register + Decision Journal). "
        f"KPI data from OneDrive pipeline. "
        f"This is a standalone weekly report — the daily executive brief is unchanged.</div>"
        f"</div>")


def _read_wiki(name: str) -> str:
    path = os.path.join(WIKI_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        log.warning("decision_report: could not read %s: %s", path, exc)
        return ""


def _today_central() -> str:
    return datetime.now(ZoneInfo("America/Chicago")).strftime("%A, %B %d, %Y")


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    load_dotenv()

    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    upn    = os.environ.get("ONEDRIVE_USER_UPN")

    date_str   = _today_central()
    risk_md    = _read_wiki("risk-register.md")
    decision_md = _read_wiki("decision-journal.md")

    # KPI trend + scenarios + grading + narrative + Claude prompts (all optional)
    kpi_trend = None
    scenarios = None
    grades    = None
    narrative = ""
    prompts   = None
    if all([tenant, client, secret, upn]):
        token     = get_token(tenant, client, secret)
        kpi_trend = _load_kpi_trend(token, upn)
        scenarios = _build_scenarios(kpi_trend)
        outcomes  = _load_outcomes()
        grades    = _grade_decisions(kpi_trend, outcomes)
        if grades:
            _write_grades(grades)
        narrative = _generate_cfo_narrative(kpi_trend, scenarios or [], grades or {})
        prompts   = _generate_decision_prompts(kpi_trend, risk_md, scenarios=scenarios)
    else:
        token = None

    html    = build_decision_report(date_str, risk_md, decision_md,
                                    kpi_trend=kpi_trend, prompts=prompts,
                                    scenarios=scenarios, grades=grades,
                                    narrative=narrative)
    subject = f"XFreight Risk & Decisions — {date_str}"

    if "--dry" in sys.argv:
        out = "/tmp/decision_report.html"
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        log.info("Dry run — wrote %s (%d bytes), no email sent.", out, len(html))
        return 0

    if not all([tenant, client, secret, upn]):
        sys.exit("ERROR: AZURE_TENANT_ID/CLIENT_ID/CLIENT_SECRET and ONEDRIVE_USER_UPN are required")
    from_upn  = os.environ.get("SCORECARD_FROM_UPN", upn)
    to_emails = [e.strip() for e in
                 os.environ.get("DECISION_REPORT_TO_EMAILS", "jeff@xfreight.net").split(",")
                 if e.strip()]

    send_email(token, from_upn, to_emails, subject, html)
    log.info("Risk & Decisions report sent to %s", ", ".join(to_emails))
    return 0


if __name__ == "__main__":
    sys.exit(main())
