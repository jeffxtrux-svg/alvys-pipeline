"""Risk Watch — Phase 2B active loop (KB → brief).

Reads the machine-readable signal definitions from
`Karpathy-Wiki/wiki/risk-signals.yml`, evaluates each signal against
the live data dicts the scorecard already builds, and returns a list
of {risk, status, current, threshold, ...} that the brief renders as
a "Risk Watch" strip on page 1.

Design intent: the risk register stays the source of human-readable
context (what the risk is, why it matters, who owns it). The
signals file is the executable companion — one machine-readable
threshold per risk — so the brief can light up automatically when a
threshold is crossed instead of waiting for a human to notice.

Signal evaluation is intentionally simple: dot-path lookup into the
brief's data dicts, single numeric comparison. No DSL, no eval()
on user-supplied expressions. Adding a new signal type means
extending this file with code, not making the YAML more powerful.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("risk_watch")

_SIGNALS_PATH = Path(__file__).resolve().parent.parent / "Karpathy-Wiki" / "wiki" / "risk-signals.yml"


def _walk(obj: Any, path: str) -> Any:
    """Drill into nested dicts following a dotted path. Returns None on
    any missing key or non-dict intermediate — fail soft so a renamed
    field doesn't crash the brief."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _load_yaml(path: Path) -> dict:
    """Tiny YAML reader — only the subset risk-signals.yml uses
    (nested mappings, lists of mappings, scalars). Avoids adding a
    PyYAML dependency to the scorecard runtime."""
    if not path.exists():
        return {}
    text = path.read_text()
    # Strip comments + blank lines.
    lines = []
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        # Inline comments: keep everything before " #" (not inside quotes).
        in_quote = False
        out = []
        i = 0
        while i < len(line):
            ch = line[i]
            if ch in ('"', "'"):
                in_quote = not in_quote
            if ch == "#" and not in_quote and (i == 0 or line[i - 1].isspace()):
                break
            out.append(ch)
            i += 1
        lines.append("".join(out).rstrip())
    return _parse_block(lines, 0, 0)[0]


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _coerce(val: str) -> Any:
    v = val.strip()
    if not v:
        return ""
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if v.lower() in ("null", "none", "~"):
        return None
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        return v


def _parse_block(lines: list[str], start: int, base_indent: int) -> tuple[Any, int]:
    """Parse a block at the given indent. Returns (value, next_index)."""
    if start >= len(lines):
        return {}, start
    first = lines[start]
    first_indent = _indent_of(first)
    if first_indent < base_indent:
        return {}, start
    if first.lstrip().startswith("- "):
        return _parse_list(lines, start, first_indent)
    return _parse_dict(lines, start, first_indent)


def _parse_dict(lines: list[str], start: int, indent: int) -> tuple[dict, int]:
    result: dict = {}
    i = start
    while i < len(lines):
        line = lines[i]
        cur_indent = _indent_of(line)
        if cur_indent < indent:
            break
        if cur_indent > indent:
            # Belongs to a deeper block we didn't expect — skip safely.
            i += 1
            continue
        content = line.strip()
        if ":" not in content:
            i += 1
            continue
        key, _, rhs = content.partition(":")
        key = key.strip()
        rhs = rhs.strip()
        if rhs:
            result[key] = _coerce(rhs)
            i += 1
        else:
            # Nested block on the next line(s).
            child, next_i = _parse_block(lines, i + 1, indent + 1)
            result[key] = child
            i = next_i
    return result, i


def _parse_list(lines: list[str], start: int, indent: int) -> tuple[list, int]:
    result: list = []
    i = start
    while i < len(lines):
        line = lines[i]
        cur_indent = _indent_of(line)
        if cur_indent < indent or not line.lstrip().startswith("- "):
            break
        rest = line.lstrip()[2:]
        if ":" in rest:
            # The "- " starts a dict element. Re-tokenize the rest as the
            # first key of a dict at indent + 2.
            stub = " " * (indent + 2) + rest
            patched = lines[:i] + [stub] + lines[i + 1:]
            child, next_i = _parse_dict(patched, i, indent + 2)
            result.append(child)
            i = next_i
        else:
            result.append(_coerce(rest))
            i += 1
    return result, i


def load_signals(path: Path | None = None) -> list[dict]:
    """Return the list of signal definitions, or [] if the file is missing."""
    p = path or _SIGNALS_PATH
    try:
        doc = _load_yaml(p)
    except Exception as exc:
        log.warning("risk_watch: failed to parse %s (%s) — strip will be empty.", p, exc)
        return []
    risks = doc.get("risks") if isinstance(doc, dict) else None
    if not isinstance(risks, list):
        return []
    return [r for r in risks if isinstance(r, dict)]


def _compare(value: float, threshold: float, direction: str) -> bool:
    if direction == ">=":
        return value >= threshold
    if direction == ">":
        return value > threshold
    if direction == "<=":
        return value <= threshold
    if direction == "<":
        return value < threshold
    if direction == "==":
        return value == threshold
    return False


def _eval_one(signal: dict, data: dict) -> dict | None:
    """Evaluate a single signal. Returns a dict ready for rendering, or
    None when the underlying metric is missing entirely (so the strip
    silently omits signals that can't yet be evaluated rather than
    showing spurious 'OK')."""
    metric = signal.get("metric")
    if not metric:
        return None
    raw = _walk(data, metric)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    threshold = signal.get("threshold", 0)
    direction = signal.get("direction", ">=")
    tripped = _compare(value, float(threshold), direction)
    paired = signal.get("paired") or {}
    paired_value = None
    paired_tripped = False
    if isinstance(paired, dict) and paired.get("metric"):
        praw = _walk(data, paired["metric"])
        if praw is not None:
            try:
                paired_value = float(praw)
                paired_tripped = _compare(paired_value, float(paired.get("threshold", 0)),
                                           paired.get("direction", ">="))
            except (TypeError, ValueError):
                paired_value = None
    return {
        "id": signal.get("id"),
        "title": signal.get("title"),
        "page": signal.get("page"),
        "severity": signal.get("severity", "medium"),
        "tripped": tripped or paired_tripped,
        "value": value,
        "threshold": threshold,
        "format": signal.get("format", "int"),
        "ok_text": signal.get("ok_text") or signal.get("title"),
        "tripped_text": signal.get("tripped_text") or signal.get("title"),
        "paired_value": paired_value,
        "paired_tripped_text": (paired or {}).get("tripped_text"),
    }


def evaluate(data: dict, path: Path | None = None) -> list[dict]:
    """Evaluate all signals in the file against `data` (a dict whose keys
    are the top-level dict names used in the brief: equipment, qb_ar,
    csa, samsara, alvys_entities, etc.). Returns one entry per signal
    that could be evaluated."""
    signals = load_signals(path)
    out: list[dict] = []
    for sig in signals:
        result = _eval_one(sig, data)
        if result is not None:
            out.append(result)
    return out


def _fmt(value: float | None, fmt: str) -> str:
    if value is None:
        return "—"
    if fmt == "money":
        return f"${value:,.0f}"
    if fmt == "days":
        return f"{value:.0f}d"
    if fmt == "pct":
        return f"{value:.1%}"
    return f"{int(value):,}" if value == int(value) else f"{value:,.2f}"


def render_strip_html(results: list[dict],
                       *,
                       red: str = "#c41e2a",
                       redbg: str = "#fde8ea",
                       green: str = "#0f6b3d",
                       greenbg: str = "#e7f3ec",
                       mute: str = "#6b6b6b",
                       line: str = "#ececec") -> str:
    """Render the Risk Watch strip as an HTML snippet suitable for
    inlining near the top of page 1. Returns empty string when there
    are no evaluatable signals."""
    if not results:
        return ""

    def _pill(text: str, kind: str) -> str:
        if kind == "tripped":
            bg, fg = redbg, red
        elif kind == "ok":
            bg, fg = greenbg, green
        else:
            bg, fg = "#fafafa", mute
        return (f"<span style='display:inline-block;background:{bg};color:{fg};"
                f"font-size:11px;padding:3px 8px;border-radius:4px;font-weight:600;"
                f"margin-right:6px;'>{text}</span>")

    rows = []
    for r in results:
        if r["tripped"]:
            text = r["tripped_text"].format(value=_fmt(r["value"], r["format"]))
            if r.get("paired_value") is not None and r.get("paired_tripped_text"):
                text += " " + r["paired_tripped_text"].format(
                    value=_fmt(r["paired_value"], r["format"])
                )
            kind = "tripped"
            badge = "TRIPPED"
        else:
            text = r["ok_text"]
            kind = "ok"
            badge = "OK"
        rows.append(
            f"<div style='padding:6px 0;border-bottom:1px solid {line};font-size:12.5px;'>"
            f"{_pill(badge, kind)}<b>{r['title']}</b> &mdash; "
            f"<span style='color:{mute};'>{text}</span>"
            f"</div>"
        )

    return (
        f"<div style='margin:14px 0 18px;padding:12px 16px;background:#fcfcfc;"
        f"border:1px solid {line};border-radius:6px;'>"
        f"<div style='font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{mute};text-transform:uppercase;margin-bottom:6px;'>Risk Watch</div>"
        + "".join(rows) +
        f"</div>"
    )


def write_signals_snapshot(results: list[dict], path: Path | None = None) -> None:
    """Write the current evaluated signals to a JSON snapshot the Slack
    digest (and other downstream consumers) can read without re-running
    the full scorecard. Same pattern as decision_grader.write_grades_snapshot.

    `Karpathy-Wiki/wiki/` IS committed to git (unlike `raw/`), but the
    scorecard workflow's commit step only stages `Karpathy-Wiki/raw` — so
    this file never reaches main from CI either. Also best-effort mirrors
    it to OneDrive (Scorecard/risk-watch-latest.json) so the digest has a
    source that's actually populated."""
    import json
    from datetime import datetime
    target = path or (_SIGNALS_PATH.parent / "risk-watch-latest.json")
    snap = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "signals": [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "page": r.get("page"),
                "severity": r.get("severity"),
                "tripped": r.get("tripped"),
                "value": r.get("value"),
                "threshold": r.get("threshold"),
                "format": r.get("format"),
                "ok_text": r.get("ok_text"),
                "tripped_text_template": r.get("tripped_text"),
                "paired_value": r.get("paired_value"),
                "paired_tripped_text_template": r.get("paired_tripped_text"),
            }
            for r in results
        ],
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snap, indent=2, default=str))
    except Exception as exc:
        log.warning("risk_watch: failed to write signals snapshot (%s)", exc)
        return
    try:
        from src.onedrive_upload import ensure_folder, get_token_from_env, upload_file
        token, upn = get_token_from_env()
        if token:
            ensure_folder(token, upn, "Scorecard")
            upload_file(token=token, user_upn=upn, folder_path="Scorecard",
                       filename="risk-watch-latest.json", file_path=target)
            log.info("risk_watch: signals snapshot mirrored to OneDrive")
    except Exception as exc:
        log.warning("risk_watch: OneDrive mirror failed (%s)", exc)
