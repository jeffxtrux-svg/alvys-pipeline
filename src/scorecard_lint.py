"""Pre-flight checks for the executive scorecard email.

Runs after `build_report` returns the HTML but before `send_email`. Inspects
the rendered HTML (and a few computed values passed in) for the regressions
we've actually hit in production — driver column showing "0", MPG column
all em-dashes, retired trucks still listed, etc.

Two severity levels:
  * warning — surfaces in the workflow log so a human notices on the
    next morning's run. Email still ships clean.
  * error   — same log surfacing PLUS the email subject is prefixed
    with "[LINT N issues]" so it's visible in the operator's inbox.

Add a new check by writing a function that takes (html, ctx) and returns
a list[Finding]. Register it in CHECKS. ctx is whatever extra data the
caller passes — currently the per-section compute dicts.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, Iterable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Finding:
    severity: str   # "error" or "warning"
    check: str
    message: str


def _isnum(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# ----------------------------------------------------------------------
# Individual checks. Each returns a list[Finding].
# ----------------------------------------------------------------------

def check_driver_zero_in_html(html: str, ctx: dict) -> list[Finding]:
    """No table cell should display the literal text '0' or 'nan' as a
    driver name — those slip through when a raw driverId or NaN got
    through the resolver."""
    out: list[Finding] = []
    # Look for <td ...>0</td> patterns appearing in any settlement-week
    # or idle table. Crude but the rendered HTML is consistent enough that
    # a literal "0" in a left-aligned cell is always a bug.
    for m in re.finditer(r"<td[^>]*align=['\"]left['\"][^>]*>\s*(0|nan|NaN)\s*</td>", html):
        out.append(Finding("error", "driver_zero",
                           f"literal '{m.group(1)}' in a left-aligned cell — "
                           "likely an unresolved driver id"))
    return out


def check_idle_mpg_join(html: str, ctx: dict) -> list[Finding]:
    """The Idlers table joins MPG by truck label. If every row's MPG cell
    is em-dash but the MPG list itself is populated, the join is broken."""
    out: list[Finding] = []
    samsara = ctx.get("samsara") or {}
    fleet = samsara.get("fleet") or {}
    idle = fleet.get("idle") or []
    mpg = fleet.get("mpg") or []
    if not idle or not mpg:
        return out
    with_mpg = sum(1 for r in idle if _isnum(r.get("mpg")))
    if with_mpg == 0 and len(mpg) >= 5:
        # Build keyset samples so the operator can diff them at a glance.
        idle_keys = [r.get("unit") for r in idle[:5]]
        mpg_keys = [m.get("unit") for m in mpg[:5]]
        out.append(Finding("error", "mpg_join",
                           f"MPG missing for ALL {len(idle)} idle rows but the MPG "
                           f"list has {len(mpg)} entries — join is broken. "
                           f"idle_keys={idle_keys!r} mpg_keys={mpg_keys!r}"))
    return out


def check_mpg_units_are_truck_numbers(html: str, ctx: dict) -> list[Finding]:
    """MPG list entries should be keyed by short truck numbers ('45209'),
    not by Samsara's 15-digit vehicleId. Long-numeric units mean the
    id->truck resolver didn't fire."""
    out: list[Finding] = []
    samsara = ctx.get("samsara") or {}
    fleet = samsara.get("fleet") or {}
    mpg = fleet.get("mpg") or []
    for m in mpg:
        u = str(m.get("unit") or "")
        if u.isdigit() and len(u) > 10:
            out.append(Finding("error", "mpg_units",
                               f"MPG unit '{u}' looks like a Samsara vehicleId — "
                               "id_to_truck resolution missed this entry"))
    return out


def check_excluded_truck_absent(html: str, ctx: dict) -> list[Finding]:
    """If a truck is on the _TRUCK_EXCLUDE list it should not appear in
    the Idlers table at all."""
    out: list[Finding] = []
    try:
        from src.scorecard_email import _TRUCK_EXCLUDE
    except Exception:
        return out
    samsara = ctx.get("samsara") or {}
    idle = ((samsara.get("fleet") or {}).get("idle") or [])
    units = {str(r.get("unit") or "") for r in idle}
    leaked = units & set(_TRUCK_EXCLUDE)
    if leaked:
        out.append(Finding("error", "excluded_truck_leaked",
                           f"excluded trucks still in Idlers: {sorted(leaked)}"))
    return out


def check_excluded_driver_absent(html: str, ctx: dict) -> list[Finding]:
    """Placeholder drivers (currently 'tempd') shouldn't appear in any
    table. The brief scopes them out — if one slips into the rendered
    HTML the filter regressed."""
    out: list[Finding] = []
    try:
        from src.scorecard_email import _DRIVER_EXCLUDE
    except Exception:
        return out
    low = (html or "").lower()
    for name in _DRIVER_EXCLUDE:
        # word-boundary so 'tempd' doesn't match 'tempdrive'
        if re.search(rf"\b{re.escape(name)}\b", low):
            out.append(Finding("error", "excluded_driver_leaked",
                               f"excluded driver '{name}' appears in rendered HTML"))
    return out


def check_ar_past_due_both_sources(html: str, ctx: dict) -> list[Finding]:
    """The AR past-due tile should always carry both QB and Alvys numbers
    (the entire reason we surfaced both)."""
    out: list[Finding] = []
    qb_ar = ctx.get("qb_ar") or {}
    alvys_ar = ctx.get("alvys_ar") or {}
    if qb_ar and qb_ar.get("total_past_due") is None:
        out.append(Finding("warning", "ar_qb_missing", "QB past-due is None"))
    if alvys_ar and alvys_ar.get("overdue") is None:
        out.append(Finding("warning", "ar_alvys_missing", "Alvys past-due is None"))
    return out


def check_idle_gallons_present(html: str, ctx: dict) -> list[Finding]:
    """If every idle row has zero/missing idle gallons but the underlying
    EngineIdle sheet has idle hours, the OBD fuel-counter integration in
    samsara_main isn't flowing (probably reading stale workbook before
    Samsara finished updating it)."""
    out: list[Finding] = []
    samsara = ctx.get("samsara") or {}
    idle = ((samsara.get("fleet") or {}).get("idle") or [])
    if not idle:
        return out
    rows_with_hours = sum(1 for r in idle if (r.get("idle_hours") or 0) > 0)
    rows_with_gal = sum(1 for r in idle
                        if r.get("idle_gallons") and r.get("idle_gallons") > 0)
    if rows_with_hours >= 5 and rows_with_gal == 0:
        out.append(Finding("error", "idle_gallons_empty",
                           f"{rows_with_hours} trucks have idle hours but zero "
                           f"have idle gallons — OBD fuel column missing from "
                           f"EngineIdle sheet (Samsara workbook out of date?)"))
    return out


def check_mpg_table_has_drivers(html: str, ctx: dict) -> list[Finding]:
    """Best/Worst MPG entries should carry a driver name (em-dash is fine
    for unassigned trucks, but never a literal missing/None)."""
    out: list[Finding] = []
    samsara = ctx.get("samsara") or {}
    mpg = ((samsara.get("fleet") or {}).get("mpg") or [])
    if not mpg:
        return out
    missing_key = sum(1 for m in mpg if "driver" not in m)
    if missing_key == len(mpg):
        out.append(Finding("error", "mpg_no_driver_key",
                           "MPG entries lack 'driver' key — backfill step skipped?"))
    return out


def check_safety_scores_complete(html: str, ctx: dict) -> list[Finding]:
    """Every driver in scores_all needs a name and a numeric score."""
    out: list[Finding] = []
    samsara = ctx.get("samsara") or {}
    scores = ((samsara.get("fleet") or {}).get("scores_all") or [])
    for row in scores:
        name = str(row.get("driver") or "").strip()
        if not name or name.lower() in ("0", "nan", "none"):
            out.append(Finding("error", "safety_name",
                               f"safety row has invalid driver name: {row!r}"))
        if not _isnum(row.get("score")):
            out.append(Finding("error", "safety_score",
                               f"safety row has non-numeric score: {row!r}"))
    return out


# Registry. Add a check by writing a function above and appending it here.
CHECKS: list[Callable[[str, dict], list[Finding]]] = [
    check_driver_zero_in_html,
    check_idle_mpg_join,
    check_mpg_units_are_truck_numbers,
    check_excluded_truck_absent,
    check_excluded_driver_absent,
    check_ar_past_due_both_sources,
    check_safety_scores_complete,
    check_idle_gallons_present,
    check_mpg_table_has_drivers,
]


def lint(html: str, **ctx) -> list[Finding]:
    """Run every registered check and return the combined findings."""
    findings: list[Finding] = []
    for chk in CHECKS:
        try:
            findings.extend(chk(html, ctx))
        except Exception as e:
            findings.append(Finding("warning", chk.__name__,
                                    f"check raised {type(e).__name__}: {e}"))
    return findings


def format_findings(findings: Iterable[Finding]) -> str:
    """Pretty-print findings as a multi-line string for logs / emails."""
    by_sev: dict[str, list[Finding]] = {"error": [], "warning": []}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)
    lines: list[str] = []
    for sev in ("error", "warning"):
        for f in by_sev[sev]:
            lines.append(f"  [{sev.upper()}] {f.check}: {f.message}")
    return "\n".join(lines) if lines else "  (no findings)"


def subject_prefix(findings: Iterable[Finding]) -> str:
    """Return a 'LINT N' prefix to prepend to the email subject when
    there are errors, or '' when clean."""
    errs = sum(1 for f in findings if f.severity == "error")
    return f"[LINT {errs}] " if errs else ""
