# JW Logistics exclusion policy (seeded 2026-06-05 from repo)

> Source: `CLAUDE.md` (multiple references), `_is_ar_excluded()` in
> `src/scorecard_email.py`, commit history.

## The rule

**JW Logistics is excluded from every XFreight report and tile.**

This is a permanent, hard-coded policy. JW Logistics is treated as if it doesn't exist for the purposes of:

- Page 1 entity tiles (revenue, margin, loads, miles).
- AR aging tiles (all five buckets: current / 1–30 / 31–60 / 61–90 / 91+).
- The QB-vs-Alvys reconciliation (page 12).
- The bill-by-bill match (page 13).
- The 90+ collections list.
- All Samsara safety + fleet metrics where unit labels carry the JW prefix.

## How it's enforced

A hardened name matcher: `_is_ar_excluded()` in `src/scorecard_email.py`. The matcher is hardened (case-insensitive, handles whitespace, handles common spellings) so the policy can't be bypassed by a typo in QB's customer list or Alvys's carrier list.

A parallel matcher `_is_excluded_truck()` filters JW Logistics truck units out of Samsara aggregations (e.g. Fleet miles · MTD on page 8). This was reinforced in PR #88 — until then the per-truck list was filtered but the headline aggregate wasn't, leaving JW miles inflating the fleet total.

## Why the policy exists

Not documented in code comments — treated as a standing business decision. The matcher comment in CLAUDE.md just says "JW Logistics excluded throughout via a hardened name matcher in `_is_ar_excluded`."

If the policy changes, the matchers in `src/scorecard_email.py` are the single point of update. The exclusion is testable via `python tests/test_rpm_goal.py` and similar contract tests.

## What this means for new reports

Any new page, tile, or report that aggregates XFreight customer / carrier / truck data MUST route through `_is_ar_excluded()` or `_is_excluded_truck()` (whichever applies). Adding raw `for x in customers` loops without the filter will silently include JW Logistics and break the policy.
