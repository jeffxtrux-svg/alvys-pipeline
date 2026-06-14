"""Decision grader — Phase 2C active loop (decision-journal → brief).

Reads the machine-readable outcome predictions from
`Karpathy-Wiki/wiki/decision-outcomes.yml`, evaluates each decision's
predicted outcome against the live compute dicts the scorecard already
builds, and returns a list of grades the brief can summarize and the
librarian can stamp onto the decision-journal page.

Grades:
  pending    — earlier than check_after OR underlying metric not yet
               available. The decision hasn't had time to play out.
  confirmed  — actual outcome matched the prediction.
  mixed      — outcome differed, but in a non-fatal direction (e.g.,
               margin landed slightly above the predicted band).
  wrong      — outcome contradicted the prediction in a way the
               decision should be revisited for.

Design intent: same fail-soft pattern as risk_watch — a missing metric
or a malformed check silently downgrades to pending rather than
crashing the brief. The point is to close the feedback loop on
decisions; if we can't grade one yet, we just say so.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src import risk_watch  # reuse _walk, _load_yaml, _coerce

log = logging.getLogger("decision_grader")

_OUTCOMES_PATH = Path(__file__).resolve().parent.parent / "Karpathy-Wiki" / "wiki" / "decision-outcomes.yml"


def load_outcomes(path: Path | None = None) -> list[dict]:
    """Return the list of outcome-check definitions, or [] if missing."""
    p = path or _OUTCOMES_PATH
    try:
        doc = risk_watch._load_yaml(p)
    except Exception as exc:
        log.warning("decision_grader: failed to parse %s (%s) — grading skipped.", p, exc)
        return []
    decisions = doc.get("decisions") if isinstance(doc, dict) else None
    if not isinstance(decisions, list):
        return []
    return [d for d in decisions if isinstance(d, dict)]


def _parse_date(s: Any) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _grade_range(value: float, check: dict) -> str:
    """Range check: confirmed if min <= value <= max. Out-of-range is
    wrong/mixed depending on which side and whether wrong_below/above
    is set."""
    lo = check.get("min")
    hi = check.get("max")
    if lo is not None and value < float(lo):
        return "wrong" if check.get("wrong_below") else "mixed"
    if hi is not None and value > float(hi):
        return "wrong" if check.get("wrong_above") else "mixed"
    return "confirmed"


def _grade_comparison(value: float, check: dict) -> str:
    """Comparison check: pass/fail with explicit grade for each side."""
    threshold = float(check.get("threshold", 0))
    direction = check.get("direction", ">=")
    passed = risk_watch._compare(value, threshold, direction)
    on_pass = check.get("on_pass", "confirmed")
    on_fail = check.get("on_fail", "wrong")
    return on_pass if passed else on_fail


_VALID_GRADES = {"confirmed", "mixed", "wrong"}


def _grade_one(decision: dict, data: dict, today: date | None = None) -> dict:
    """Evaluate a single decision. Always returns a grade dict — falls
    back to 'pending' when we can't actually grade yet."""
    today = today or date.today()
    out = {
        "id": decision.get("id"),
        "title": decision.get("title"),
        "journal_date": decision.get("journal_date"),
        "check_after": decision.get("check_after"),
        "grade": "pending",
        "value": None,
        "reason": "",
    }
    check_after = _parse_date(decision.get("check_after"))
    if check_after is not None and today < check_after:
        out["reason"] = f"check_after {check_after.isoformat()} not yet reached"
        return out
    check = decision.get("check") or {}
    metric = check.get("metric")
    if not metric:
        out["reason"] = "no check.metric defined"
        return out
    raw = risk_watch._walk(data, metric)
    if raw is None:
        out["reason"] = f"metric {metric} not present in compute dicts"
        return out
    try:
        value = float(raw)
    except (TypeError, ValueError):
        out["reason"] = f"metric {metric} not numeric"
        return out
    out["value"] = value
    kind = check.get("kind", "range")
    if kind == "range":
        grade = _grade_range(value, check)
    elif kind == "comparison":
        grade = _grade_comparison(value, check)
    else:
        out["reason"] = f"unknown check.kind={kind}"
        return out
    out["grade"] = grade if grade in _VALID_GRADES else "mixed"
    out["reason"] = f"kind={kind} value={value}"
    out["format"] = check.get("format", "int")
    return out


def evaluate(data: dict, *, today: date | None = None,
             path: Path | None = None) -> list[dict]:
    """Grade every decision in the outcomes file against `data`.
    Returns one entry per decision (including pending ones)."""
    decisions = load_outcomes(path)
    return [_grade_one(d, data, today=today) for d in decisions]


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
    """Compact chip summarizing decision grades. Hidden when there's
    nothing tracked (the outcomes file is empty)."""
    if not results:
        return ""
    counts = summary_counts(results)
    total = sum(counts.values())
    if total == 0:
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

    # Show the first 1-2 most recently graded (non-pending) decisions inline
    # so the strip is actionable, not just a count.
    recent_graded = [r for r in results if r.get("grade") != "pending"]
    recent_graded.sort(key=lambda r: r.get("journal_date", ""), reverse=True)
    inline_text = ""
    if recent_graded:
        r = recent_graded[0]
        gmark = {"confirmed": "✓", "mixed": "~", "wrong": "✗"}.get(r["grade"], "?")
        gcolor = {"confirmed": green, "mixed": mute, "wrong": red}.get(r["grade"], mute)
        inline_text = (
            f"<span style='color:{mute};font-size:12px;'>most recent: "
            f"<span style='color:{gcolor};font-weight:700;'>{gmark}</span> "
            f"{r.get('title', '')}</span>"
        )

    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fcfcfc;"
        f"border:1px solid {line};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{mute};text-transform:uppercase;margin-bottom:6px;'>"
        f"Decisions Graded</div>"
        f"<div>{chips}</div>"
        + (f"<div style='margin-top:6px;'>{inline_text}</div>" if inline_text else "")
        + f"</div>"
    )


def write_grades_snapshot(results: list[dict], path: Path | None = None) -> None:
    """Write a small JSON snapshot of the current grades so the librarian
    can pick it up on its next compile and stamp badges into
    wiki/decision-journal.md."""
    import json
    target = path or (_OUTCOMES_PATH.parent / "decision-grades.json")
    snap = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "grades": [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "journal_date": r.get("journal_date"),
                "grade": r.get("grade"),
                "value": r.get("value"),
                "reason": r.get("reason"),
            }
            for r in results
        ],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snap, indent=2, default=str))
    except Exception as exc:
        log.warning("decision_grader: failed to write grades snapshot (%s)", exc)
