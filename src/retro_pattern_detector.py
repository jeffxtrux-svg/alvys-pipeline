"""Retro pattern detector — Phase 2D supporting automation.

Scans `Karpathy-Wiki/wiki/weekly-retros.yml` for lessons and observations
that recur across multiple weeks, surfaces them as a "Recurring Patterns"
panel on page 1 of the executive brief. This is the "week-4 review"
mechanism — automated so it happens every morning instead of waiting for
a manual review that may or may not happen.

Detection is intentionally conservative:
  - A "pattern" is a lesson (or normalized phrase from surprised_by /
    didnt_work) that appears in 2+ different weeks within the last 90 days
  - Matching uses normalized text (lowercase + stripped punctuation) and
    a first-K-words key so paraphrased lessons still match
  - Single-week observations are NOT patterns — by design, the panel only
    fires when there's evidence of repetition

The point is to make institutional learning compound: if the same root
cause keeps surfacing, the team should see it on every brief until it's
addressed (or de-prioritized as "we know, accepting the risk").

Fail-soft: parse errors, missing file, empty list — all return [] and the
brief silently omits the panel.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src import risk_watch  # reuse _load_yaml

log = logging.getLogger("retro_pattern_detector")

_RETROS_PATH = (Path(__file__).resolve().parent.parent
                / "Karpathy-Wiki" / "wiki" / "weekly-retros.yml")

# Detection knobs
_LOOKBACK_DAYS = 90       # only count weeks within this window
_MIN_OCCURRENCES = 2      # at least N weeks to count as a pattern
_KEY_WORD_COUNT = 6       # use first K normalized words as the dedup key
_MAX_PATTERNS_SHOWN = 5   # cap the panel to top N patterns


def _parse_date(s: Any) -> date | None:
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.
    Empty / NaN-ish inputs return empty string."""
    if not text or not isinstance(text, str):
        return ""
    s = text.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _key(text: str) -> str:
    """First K normalized words — the dedup key for pattern matching."""
    norm = _normalize(text)
    if not norm:
        return ""
    return " ".join(norm.split()[:_KEY_WORD_COUNT])


def _extract_observations(retro: dict) -> list[tuple[str, str]]:
    """From one retro, pull every observation worth checking for recurrence.
    Returns [(source_field, original_text), ...].

    surprised_by + didnt_work get split into sentences (so a multi-line
    observation block contributes multiple potential patterns). Each
    lesson is its own item."""
    out: list[tuple[str, str]] = []
    for field in ("surprised_by", "didnt_work"):
        val = retro.get(field) or ""
        if not val:
            continue
        # Split into sentences by period/newline; keep meaningful ones only
        for sent in re.split(r"[.\n]", val):
            sent = sent.strip()
            if len(sent.split()) >= 4:  # ignore trivially short fragments
                out.append((field, sent))
    for lsn in (retro.get("lessons") or []):
        if isinstance(lsn, str) and lsn.strip():
            out.append(("lessons", lsn.strip()))
    return out


def load_retros(path: Path | None = None) -> list[dict]:
    """Return the list of retro entries, or [] if file missing/empty."""
    p = path or _RETROS_PATH
    try:
        doc = risk_watch._load_yaml(p)
    except Exception as exc:
        log.warning("retro_pattern_detector: failed to parse %s (%s)", p, exc)
        return []
    retros = doc.get("retros") if isinstance(doc, dict) else None
    if not isinstance(retros, list):
        return []
    return [r for r in retros if isinstance(r, dict)]


def find_patterns(retros: list[dict] | None = None,
                  *,
                  today: date | None = None,
                  lookback_days: int = _LOOKBACK_DAYS,
                  min_occurrences: int = _MIN_OCCURRENCES) -> list[dict]:
    """Scan retros for observations recurring across 2+ weeks within the
    lookback window. Returns one entry per pattern, sorted by recurrence
    count desc."""
    retros = retros if retros is not None else load_retros()
    if not retros:
        return []

    today = today or date.today()
    cutoff = today - timedelta(days=lookback_days)

    # Bucket observations by their normalized key. For each key we track:
    #   - all weeks it appeared in (deduped)
    #   - the most recent original text (so the panel reads naturally)
    #   - which field (lessons / surprised_by / didnt_work)
    by_key: dict[str, dict] = defaultdict(lambda: {
        "weeks": set(),
        "latest_text": "",
        "latest_week": None,
        "source_field": "",
    })

    for retro in retros:
        wk = _parse_date(retro.get("week_of"))
        if wk is None or wk < cutoff:
            continue
        wk_iso = wk.isoformat()
        for source_field, text in _extract_observations(retro):
            k = _key(text)
            if not k:
                continue
            slot = by_key[k]
            slot["weeks"].add(wk_iso)
            # Keep the latest version of the text (most recent paraphrase)
            if slot["latest_week"] is None or wk > _parse_date(slot["latest_week"]):
                slot["latest_text"] = text
                slot["latest_week"] = wk_iso
                slot["source_field"] = source_field

    patterns = []
    for k, slot in by_key.items():
        if len(slot["weeks"]) >= min_occurrences:
            patterns.append({
                "key": k,
                "text": slot["latest_text"],
                "source_field": slot["source_field"],
                "weeks_seen": sorted(slot["weeks"], reverse=True),
                "occurrence_count": len(slot["weeks"]),
            })

    # Sort: most recurrences first, then most recent occurrence
    patterns.sort(key=lambda p: (-p["occurrence_count"], p["weeks_seen"][0]),
                  reverse=False)
    patterns.sort(key=lambda p: -p["occurrence_count"])
    return patterns[:_MAX_PATTERNS_SHOWN]


def render_patterns_html(patterns: list[dict],
                          *,
                          ink: str = "#1a1a1a",
                          mute: str = "#6b6b6b",
                          line: str = "#ececec",
                          warn: str = "#a86700") -> str:
    """Render the recurring-patterns panel for page 1. Returns "" when
    nothing is recurring yet (single-retro state, or no matches)."""
    if not patterns:
        return ""

    field_label = {
        "lessons": "lesson",
        "surprised_by": "surprise",
        "didnt_work": "didn't work",
    }

    items_html = ""
    for p in patterns:
        n = p["occurrence_count"]
        weeks = ", ".join(p["weeks_seen"][:3])
        if len(p["weeks_seen"]) > 3:
            weeks += f", +{len(p['weeks_seen']) - 3} more"
        src = field_label.get(p["source_field"], p["source_field"])
        items_html += (
            f"<li style='margin-bottom:6px;'>"
            f"<span style='color:{warn};font-weight:700;'>{n}× &middot;</span> "
            f"<span style='color:{ink};font-size:12px;'>{p['text']}</span>"
            f"<div style='color:{mute};font-size:10px;margin-top:2px;'>"
            f"({src}) &middot; weeks: {weeks}</div>"
            f"</li>"
        )

    return (
        f"<div style='margin:0 0 14px;padding:10px 14px;background:#fffaf0;"
        f"border:1px solid {warn};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{warn};text-transform:uppercase;margin-bottom:8px;'>"
        f"Recurring Patterns &middot; from past retros</div>"
        f"<ul style='margin:0;padding-left:20px;'>"
        f"{items_html}"
        f"</ul>"
        f"<div style='margin-top:6px;color:{mute};font-size:10px;'>"
        f"Observations that have appeared in {_MIN_OCCURRENCES}+ weekly retros "
        f"within the last {_LOOKBACK_DAYS} days. If a pattern is no longer "
        f"relevant, edit or remove the older retro entries it stems from."
        f"</div>"
        f"</div>"
    )


def main() -> int:
    """Manual CLI for debugging — prints detected patterns."""
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                         datefmt="%H:%M:%S")
    patterns = find_patterns()
    if not patterns:
        print("No recurring patterns detected.")
        return 0
    for p in patterns:
        print(f"{p['occurrence_count']}× [{p['source_field']}] {p['text']}")
        print(f"  weeks: {', '.join(p['weeks_seen'])}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
