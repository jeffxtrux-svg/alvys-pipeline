"""Forecast grader — Phase 2D (predictions → brief).

Reads Little X's MTD-landing forecasts from
`Karpathy-Wiki/wiki/jb-mtd-forecasts.yml`, evaluates each against the live
compute dicts the scorecard already builds, and returns a list of grades
the brief can summarize.

Sibling to `src/decision_grader.py` (Phase 2C). Same fail-soft pattern:
missing metric or malformed check silently downgrades to pending rather
than crashing the brief.

Grades:
  pending    — earlier than check_after OR metric not yet available
  confirmed  — actual landed within ±tolerance_pct of the forecast
  mixed      — actual missed by 1×–2× tolerance (close but off)
  wrong      — actual missed by >2× tolerance (systematic miss)

The grades feed Little X's track record over time. After enough monthly
forecasts, the brief can show their Brier-style accuracy and flag
systematic bias (consistently under-shoots by 5%, etc.).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src import risk_watch  # reuse _walk, _load_yaml

log = logging.getLogger("forecast_grader")

_FORECASTS_PATH = (Path(__file__).resolve().parent.parent
                   / "Karpathy-Wiki" / "wiki" / "jb-mtd-forecasts.yml")


def load_forecasts(path: Path | None = None) -> list[dict]:
    """Return the list of forecast definitions, or [] if missing."""
    p = path or _FORECASTS_PATH
    try:
        doc = risk_watch._load_yaml(p)
    except Exception as exc:
        log.warning("forecast_grader: failed to parse %s (%s) — grading skipped.", p, exc)
        return []
    forecasts = doc.get("forecasts") if isinstance(doc, dict) else None
    if not isinstance(forecasts, list):
        return []
    return [f for f in forecasts if isinstance(f, dict)]


def _parse_date(s: Any) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


_VALID_GRADES = {"confirmed", "mixed", "wrong"}


def _grade_tolerance(actual: float, forecast: float, tolerance_pct: float) -> str:
    """Compare actual to forecast using a ±tolerance band.

    Within tolerance_pct → confirmed.
    Within 2× tolerance_pct → mixed (close but off).
    Outside 2× tolerance_pct → wrong (systematic miss).

    Skip placeholders: a forecast of 0 (or near-0) makes the % math
    meaningless and is almost always a template entry waiting to be
    filled in. Returns 'mixed' so it's visible but not flagged as
    a real miss.
    """
    if forecast == 0:
        return "mixed"
    pct_off = abs(actual - forecast) / abs(forecast) * 100
    if pct_off <= tolerance_pct:
        return "confirmed"
    if pct_off <= tolerance_pct * 2:
        return "mixed"
    return "wrong"


def _grade_one(forecast: dict, data: dict, today: date | None = None) -> dict:
    """Evaluate one forecast. Always returns a grade dict — falls back to
    'pending' when we can't grade yet."""
    today = today or date.today()
    out = {
        "id": forecast.get("id"),
        "title": forecast.get("title"),
        "month": forecast.get("month"),
        "captured": forecast.get("captured"),
        "captured_by": forecast.get("captured_by"),
        "check_after": forecast.get("check_after"),
        "grade": "pending",
        "forecast_value": None,
        "actual_value": None,
        "pct_off": None,
        "reason": "",
    }
    check_after = _parse_date(forecast.get("check_after"))
    if check_after is not None and today < check_after:
        out["reason"] = f"check_after {check_after.isoformat()} not yet reached"
        return out

    f_dict = forecast.get("forecast") or {}
    metric = f_dict.get("metric")
    if not metric:
        out["reason"] = "no forecast.metric defined"
        return out

    raw_actual = risk_watch._walk(data, metric)
    if raw_actual is None:
        out["reason"] = f"metric {metric} not present in compute dicts"
        return out
    try:
        actual = float(raw_actual)
    except (TypeError, ValueError):
        out["reason"] = f"metric {metric} not numeric"
        return out

    try:
        f_value = float(f_dict.get("value"))
    except (TypeError, ValueError):
        out["reason"] = "forecast.value not numeric"
        return out

    tolerance = float(f_dict.get("tolerance_pct", 5))
    grade = _grade_tolerance(actual, f_value, tolerance)
    out["grade"] = grade if grade in _VALID_GRADES else "mixed"
    out["forecast_value"] = f_value
    out["actual_value"] = actual
    out["pct_off"] = (
        (actual - f_value) / f_value * 100 if f_value else None
    )
    out["unit"] = f_dict.get("unit", "money")
    out["tolerance_pct"] = tolerance
    out["reason"] = (
        f"forecast={f_value} actual={actual} "
        f"off={out['pct_off']:+.1f}% (tol ±{tolerance:.0f}%)"
        if out["pct_off"] is not None else "—"
    )
    return out


def evaluate(data: dict, *, today: date | None = None,
             path: Path | None = None) -> list[dict]:
    """Grade every forecast in the file against `data`.
    Returns one entry per forecast (including pending ones)."""
    forecasts = load_forecasts(path)
    return [_grade_one(f, data, today=today) for f in forecasts]


def summary_counts(results: list[dict]) -> dict[str, int]:
    """Aggregate grade counts for the brief's summary chip."""
    counts = {"confirmed": 0, "mixed": 0, "wrong": 0, "pending": 0}
    for r in results:
        g = r.get("grade", "pending")
        counts[g] = counts.get(g, 0) + 1
    return counts


def render_summary_html(results: list[dict],
                         *,
                         green: str = "#0f6b3d",
                         red: str = "#c41e2a",
                         mute: str = "#6b6b6b",
                         line: str = "#ececec") -> str:
    """Compact chip summarizing JB forecast accuracy. Hidden when nothing
    is tracked yet (file empty or only placeholders pending)."""
    if not results:
        return ""
    counts = summary_counts(results)
    total = sum(counts.values())
    if total == 0:
        return ""
    # Only show the chip if at least one forecast has been GRADED (non-pending).
    # A panel of all-pending isn't useful and clutters the page.
    if (counts["confirmed"] + counts["mixed"] + counts["wrong"]) == 0:
        return ""

    def _chip(label: str, n: int, color: str) -> str:
        if n == 0:
            return ""
        return (f"<span style='display:inline-block;padding:2px 8px;border-radius:3px;"
                f"background:#fafafa;color:{color};font-size:11px;font-weight:600;"
                f"margin-right:6px;'>{label}: {n}</span>")

    chips = (
        _chip("✓ confirmed", counts["confirmed"], green)
        + _chip("~ mixed", counts["mixed"], mute)
        + _chip("✗ wrong", counts["wrong"], red)
        + _chip("⏳ pending", counts["pending"], mute)
    )

    # Show the most recently graded forecast inline so the strip is actionable.
    recent_graded = [r for r in results if r.get("grade") != "pending"]
    recent_graded.sort(key=lambda r: r.get("month", ""), reverse=True)
    inline_text = ""
    if recent_graded:
        r = recent_graded[0]
        gmark = {"confirmed": "✓", "mixed": "~", "wrong": "✗"}.get(r["grade"], "?")
        gcolor = {"confirmed": green, "mixed": mute, "wrong": red}.get(r["grade"], mute)
        off = r.get("pct_off")
        off_str = f" ({off:+.1f}%)" if off is not None else ""
        inline_text = (
            f"<span style='color:{mute};font-size:12px;'>most recent: "
            f"<span style='color:{gcolor};font-weight:700;'>{gmark}</span> "
            f"{r.get('title', '')}{off_str}</span>"
        )

    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fcfcfc;"
        f"border:1px solid {line};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{mute};text-transform:uppercase;margin-bottom:6px;'>"
        f"Forecast Accuracy &middot; Little X MTD Calls</div>"
        f"<div>{chips}</div>"
        + (f"<div style='margin-top:6px;'>{inline_text}</div>" if inline_text else "")
        + f"</div>"
    )


# ----------------------------------------------------------------------
# Weekly retros — qualitative, no grader. Helper to surface most recent.
# ----------------------------------------------------------------------

_RETROS_PATH = (Path(__file__).resolve().parent.parent
                / "Karpathy-Wiki" / "wiki" / "weekly-retros.yml")


def load_recent_retro(path: Path | None = None) -> dict | None:
    """Return the most recent retro entry (or None if file empty/missing)."""
    p = path or _RETROS_PATH
    try:
        doc = risk_watch._load_yaml(p)
    except Exception as exc:
        log.warning("forecast_grader: failed to parse %s (%s)", p, exc)
        return None
    retros = doc.get("retros") if isinstance(doc, dict) else None
    if not isinstance(retros, list) or not retros:
        return None
    # Pick the one with the latest week_of
    valid = [r for r in retros if isinstance(r, dict) and r.get("week_of")]
    if not valid:
        return None
    valid.sort(key=lambda r: r.get("week_of", ""), reverse=True)
    return valid[0]


def render_retro_html(retro: dict | None,
                      *,
                      ink: str = "#1a1a1a",
                      mute: str = "#6b6b6b",
                      line: str = "#ececec",
                      accent: str = "#1a3a6b") -> str:
    """Render the latest weekly retro as a compact panel for the brief.
    Returns "" when no retro is available (panel hidden)."""
    if not retro:
        return ""

    def _para(label: str, body: str) -> str:
        if not body:
            return ""
        body = body.strip().replace("\n", " ")
        return (f"<div style='margin-bottom:6px;'>"
                f"<span style='font-weight:700;color:{accent};font-size:11px;'>"
                f"{label}:</span> "
                f"<span style='color:{ink};font-size:12px;'>{body}</span></div>")

    week = retro.get("week_of", "?")
    by = retro.get("captured_by", "")
    surprised = retro.get("surprised_by", "")
    worked = retro.get("worked", "")
    didnt = retro.get("didnt_work", "")
    lessons = retro.get("lessons") or []

    lessons_html = ""
    if lessons:
        items = "".join(
            f"<li style='margin-bottom:3px;'>{lsn}</li>"
            for lsn in lessons if lsn
        )
        lessons_html = (
            f"<div style='margin-top:6px;'>"
            f"<span style='font-weight:700;color:{accent};font-size:11px;'>"
            f"Lessons:</span>"
            f"<ul style='margin:4px 0 0 18px;padding:0;color:{ink};font-size:12px;'>"
            f"{items}</ul></div>"
        )

    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fcfcfc;"
        f"border:1px solid {line};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{mute};text-transform:uppercase;margin-bottom:8px;'>"
        f"This Week's Lessons &middot; Week of {week}"
        + (f" &middot; <span style='font-weight:400;'>captured by {by}</span>" if by else "")
        + "</div>"
        + _para("Surprised by", surprised)
        + _para("Worked", worked)
        + _para("Didn't work", didnt)
        + lessons_html
        + "</div>"
    )
