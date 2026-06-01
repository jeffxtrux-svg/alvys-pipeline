"""LLM-based review of the rendered scorecard HTML, layered on top of
the rule-based `scorecard_lint` checks.

Catches regressions the hand-written rules miss — tiles showing n/a in
a section that should always populate, drivers showing literal "0",
empty tables, format drift, MTD vs last-30d mismatches, etc. — by
sending the rendered email body to Claude with a structured-output
schema and merging any returned findings into the existing lint
pipeline.

Opt-in via ANTHROPIC_API_KEY. If the env var isn't set (or the
`anthropic` package isn't importable), the function returns an empty
list and logs an info line — the rule-based lint and the email send
both still happen.

Wiring:

    from src.scorecard_review import review as llm_review
    findings.extend(llm_review(html, **lint_ctx))

The findings returned are `scorecard_lint.Finding` objects, so they
flow through `format_findings()` and `subject_prefix()` alongside the
rule-based ones — a `[LINT N]` subject prefix counts errors from both
sources.
"""
from __future__ import annotations

import datetime
import logging
import os

log = logging.getLogger(__name__)


# Stable across runs — paid once and read from cache (~0.1x) on every
# subsequent invocation. Keep ALL volatile content (today's date,
# HTML) out of this string.
_SYSTEM_PROMPT = """You are a senior fleet operations analyst reviewing \
XFreight's daily executive-brief email before it ships to leadership. The \
brief is a 10-page HTML report covering revenue / cost / margin (X-Trux + \
X-Linx), Samsara fleet ops (MPG, idle, safety scores), QuickBooks AR, and \
several reconciliations. It is computed from live pipeline data — Alvys \
(TMS), Samsara (telematics), QuickBooks (accounting), and a manually \
maintained Power BI workbook.

Your job: catch problems before the brief goes out. You are a backstop \
for the hand-written rule-based checks that run before you, so focus on \
issues those rules miss.

# CATEGORIES TO WATCH FOR

1. **Empty / placeholder values.** Tiles showing "n/a", "$0", "—", or \
"0" where a real number is expected. The brief is computed every morning; \
genuinely-zero values are rare outside the first 2-3 days of a new month.

2. **Wrong data type in a cell.** Driver columns showing literal "0", \
"nan", "None", or a 15-digit number (Samsara vehicleId leaking through \
the id-to-truck-number resolver). Truck columns showing the same kind of \
leakage. Numbers showing as "45209.0" instead of "45209" (pandas float \
coercion that wasn't cleaned up).

3. **Empty tables.** Sections labelled "Idlers", "Driver safety scores", \
"Best MPG", "Worst MPG", etc. but rendering "(no data)" when data should \
exist. EXCEPTIONS that are usually OK: "Top Speeders · last 7 days" \
(speeding events are intermittent — empty is plausible); "SambaSafety" \
sections (the optional sheet is often absent).

4. **Format regressions.** Currency without "$", percentages without "%", \
numbers in scientific notation, wrong thousand separators, dates in the \
wrong format (the brief uses MM-DD-YYYY and "May 1-7" style ranges).

5. **Numerical implausibility.** Negative gallons or miles. MPG > 15 or \
< 3 (heavy diesel trucks aren't outside that range). Idle hours > engine \
hours. Safety score > 100 or < 0. Margin % > 50% or < -20% across an \
entity total. Idle % > 100%.

6. **Label / scope drift.** A tile says "MTD" but a sibling says "last \
30 days". A section says "IFTA" — XFreight migrated off IFTA, so the \
label should be "MTD (Based on Samsara)". A tile says "X-Trux + X-Linx" \
but the underlying number looks like one entity only.

7. **AR reconciliation gap.** Page 1's AR Past Due tile shows QB + Alvys \
side by side with a gap. If either number is None / "$0" while the other \
is meaningful, flag it.

# SEVERITY

- `error`: needs fixing before the next run. Wrong data, broken joins, \
placeholder leakage, anything that would embarrass leadership if it went \
out as-is.
- `warning`: looks suspicious but might be legitimate. Surface it for \
the operator to check, but don't block.

# OUTPUT

JSON matching the supplied schema. For each issue:
- `section`: name the page and section as it appears in the rendered \
HTML (e.g. "Page 1 · XFreight Overview tiles", "Page 4 · Idlers table").
- `finding`: describe the issue crisply. Quote the actual offending text \
when possible.
- `suggested_fix`: if the fix is obvious, say so in one sentence. \
Otherwise omit.

If everything looks fine: return an empty `issues` list with \
`overall_status: "clean"`. Do NOT manufacture findings to look thorough.

# DATE CONTEXT MATTERS

The user message includes today's date. On the 1st-3rd of a month, \
sparse MTD figures are EXPECTED — don't flag those as errors. After the \
4th of the month, any "n/a" / "$0" tile in a section that's supposed to \
populate (Revenue, Cost, Margin, Loads) is suspect.

# WHAT YOU ARE NOT ASKED TO DO

You're not asked to validate whether the numbers are *correct* — only \
whether they're *plausible and well-rendered*. You can't check whether \
$542,934 of revenue is the right answer; you can check that it isn't \
"n/a" or "$nan" or a 15-digit Samsara vehicleId.

You're not asked to suggest UX improvements or restructure the brief. \
Stay narrowly focused on regressions and bugs.
"""


def review(html: str, **ctx) -> list:
    """Send the rendered HTML to Claude for review.

    Returns a list of `scorecard_lint.Finding` objects (possibly empty).
    Skipped silently — empty list, info-level log — when:

      * `ANTHROPIC_API_KEY` is not set
      * the `anthropic` package is not installed
      * the API call fails for any reason

    The lint pipeline still runs in all of those cases.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.info("Scorecard review skipped (ANTHROPIC_API_KEY not set)")
        return []
    try:
        import anthropic
        from pydantic import BaseModel, Field
    except ImportError as e:
        log.warning("Scorecard review skipped (missing dep: %s — `pip install anthropic pydantic`)", e)
        return []
    try:
        from src.scorecard_lint import Finding
    except ImportError as e:
        log.warning("Scorecard review skipped (scorecard_lint not importable: %s)", e)
        return []

    # Schema defined inside the function so the import failure above
    # doesn't block module load when the SDK isn't present.
    from typing import Literal, Optional

    class Issue(BaseModel):
        severity: Literal["error", "warning"] = Field(
            description="error = must fix before next run; warning = check but don't block")
        section: str = Field(
            description="Page and section name as rendered, e.g. 'Page 4 · Idlers table'")
        finding: str = Field(description="Crisp description of the problem; quote offending text if possible")
        suggested_fix: Optional[str] = Field(
            default=None,
            description="One-sentence fix if obvious; omit otherwise")

    class ReviewResult(BaseModel):
        overall_status: Literal["clean", "warnings_only", "has_errors"]
        issues: list[Issue] = Field(default_factory=list)

    client = anthropic.Anthropic()
    today = datetime.date.today().isoformat()
    user_msg = (f"Today's date: {today}\n\n"
                f"Rendered HTML of the brief follows. Review it against your "
                f"instructions and return the structured JSON.\n\n"
                f"---\n\n{html}")

    try:
        response = client.with_options(timeout=180.0).messages.parse(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            system=[{
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            output_format=ReviewResult,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as e:
        log.warning("Scorecard review API error (%s): %s", type(e).__name__, e)
        return []
    except Exception as e:
        log.warning("Scorecard review failed: %s: %s", type(e).__name__, e)
        return []

    result = response.parsed_output
    usage = getattr(response, "usage", None)
    if usage:
        log.info("Scorecard review: %d issues (%s) — input=%d cache_read=%d output=%d",
                 len(result.issues), result.overall_status,
                 usage.input_tokens, getattr(usage, "cache_read_input_tokens", 0),
                 usage.output_tokens)
    else:
        log.info("Scorecard review: %d issues (%s)", len(result.issues), result.overall_status)

    out: list[Finding] = []
    for i in result.issues:
        msg = i.finding
        if i.suggested_fix:
            msg = f"{msg} | fix: {i.suggested_fix}"
        out.append(Finding(severity=i.severity, check=f"llm:{i.section}", message=msg))
    return out
