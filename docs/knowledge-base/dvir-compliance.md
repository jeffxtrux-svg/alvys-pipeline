# DVIR compliance math

> **In one sentence:** the Safety & Compliance brief computes a single
> fleet-wide "% of required DVIRs that were actually completed" — both a
> live 7-day snapshot and a 6-month trend — using working days from HOS
> as the denominator and DVIR rows from Samsara as the numerator.

It surfaces on **page 2** of the Safety brief (the metrics grid) as:

- **Row 1 · tile:** "DVIR compliance" — last 7 days, fleet-wide.
- **Row 2 · bar chart:** "DVIR compliance" — 6 monthly bars, current
  month flagged as MTD.

Both are color-coded on the same scale: green ≥ 90%, amber 50–89%,
red < 50%.

## The formula

```
                         completed DVIR rows in window
compliance %  =  ───────────────────────────────────────────────  ×  100
                  Σ (working days per driver) × 4   in window

         where "working day"   = HOS_DailyLogs row with
                                 drivedurationms > 0 or ondutydurationms > 0
         where "× 4"          = pre-trip + post-trip (FMCSA 396.11/396.13)
                                 × tractor + trailer (one asset class each)
```

### Numerator — completed DVIRs

A "completed DVIR" is one row in the Samsara **DVIRs** sheet for which
the asset is present:

- rows with a non-empty `vehicle.name`  → counted as a tractor DVIR
- rows with a non-empty `trailer.name`  → counted as a trailer DVIR
- a row with both populated counts twice (once for each asset class)

This double-count is **intentional**: it mirrors the denominator's
`× 4` expansion (pre + post × tractor + trailer), so a perfect day for
one driver — one pre-trip + one post-trip, both with tractor and
trailer attached — produces 4 numerator rows against 4 denominator
slots = 100%.

### Denominator — required DVIRs

For each driver in the window, count their **working days**, then
multiply by **4**:

- × 2 because FMCSA requires both a pre-trip and post-trip DVIR each
  working day (49 CFR 396.11 / 396.13)
- × 2 because a typical X-Trux working day pairs a tractor with a
  trailer, and the DVIR is per-asset (the per-driver compliance page
  splits them out separately, the fleet-wide page collapses them into
  one × 4 multiplier)

A driver with 5 working days in the window owes (5 × 4) = 20 DVIR
asset-rows in that window.

**Two different working-day sources, one for each surface:**

| Surface | Working-day source | Why |
|---|---|---|
| Page-2 tile (last 7d) | `HOS_DailyLogs` (drive or on-duty > 0) | Most accurate — catches full no-DVIR days too |
| Page-2 6-month trend  | `DVIRs` sheet (unique driver+date) | `HOS_DailyLogs` only pulls last 7d (`samsara_main.py`), so prior months have no rows; DVIRs fetch ~190 days, so they're the only sheet with enough history to populate the bar chart |

This is a deliberate trade-off — the monthly trend uses DVIRs as a
self-referential proxy: "of the days a driver showed up enough to
submit at least one DVIR, what % of the four required ones did they
file?" A driver who drove but submitted zero DVIRs for the whole day
is invisible in the trend, but visible in the live 7d tile.

### Capping at 100%

Some Samsara DVIR records list multiple vehicles or multiple trailers
per session — the row exporter writes one row per attached asset. That
inflates the numerator above the denominator and would render bars like
**150%** or **312%** on the monthly trend.

The fleet-wide monthly trend (`_dvir_compliance_monthly`) **clamps each
month at 100%** before rendering. The current-period tile
(`_dvir_compliance_current`) doesn't clamp — if the live 7-day window
reads > 100%, that itself is a signal worth seeing.

## Where it lives in code

| Function | File | Returns |
|---|---|---|
| `_dvir_compliance_current(sheets, days=7)` | `src/safety_compliance_email.py` | `float` % (or `None` if no data) |
| `_dvir_compliance_monthly(sheets)` | `src/safety_compliance_email.py` | `(["Jan",…], [pct,…])` × 6 months, capped at 100 |
| `compute_inspection_compliance(sheets, days)` | `src/scorecard_email.py` | per-driver dicts the live tile reduces over |

`_dvir_compliance_current` is a thin reducer over
`compute_inspection_compliance` (sum done_total / sum expected_total)
so the two numbers stay reconciled — the page-7 per-driver
inspection-compliance table totals to the same % the row-1 tile
shows.

`_dvir_compliance_monthly` re-implements the same expected/completed
math against month-bucketed data, since `compute_inspection_compliance`
takes a single `days=` window rather than month buckets.

## Where the brief renders it

```
_safety_summary_block_inline()           # src/safety_compliance_email.py
  └─ _snap_tile("DVIR compliance", …)    # row 1, 4th column
  └─ _bar_chart("DVIR compliance", …)    # row 2, 4th column
build_page2_metrics() → wraps the above into the page-2 "Safety metrics"
```

Page-2 grid layout after this was added:

```
Row 1 (4 tiles, 25% each):  Fleet score | DVIR open | Missing logs | DVIR compliance %
Row 2 (4 bars,  25% each):  HOS         | DVIR defs | Coached      | DVIR compliance trend
Row 3 (3 bars,  25% each):  Events      | Dismissed | Speed o/limit| (spacer)
```

## Known caveats

- **The per-driver DVIR audit page** (logical p12,
  `build_page_dvir_detail_by_driver`) uses a *different, naive count*:
  `completed = len(group)` over raw DVIR rows for the driver. Because
  one inspection session can produce multiple rows (tractor + trailer
  in one go), that page shows ratios like **Required 16 · Completed 50
  · 312%**. The fleet-wide tile on page 2 is the authoritative
  compliance number; the per-driver page is the audit trail, not the
  scorecard.

- **HOS data dependency (7d tile).** If `HOS_DailyLogs` is missing or
  its driver/date columns can't be resolved by `_find_col`, the live
  tile renders as "—". The 6-month bar chart depends on `DVIRs`
  instead and falls back to its own "data pending" tile from
  `_bar_chart` if that's empty too.

- **Working day ≠ DVIR-required day exactly.** The 7-day tile proxies
  "driving day" with any HOS day where drive or on-duty exceeded zero
  (can over-count drivers with on-duty-not-driving time who never
  operated a CMV — rare in X-Trux's pattern). The 6-month trend
  proxies it with "submitted at least one DVIR that day" — *under*-counts
  when a driver drove but filed zero DVIRs (those days disappear from
  the trend's denominator). Both proxies skew small and in opposite
  directions, so the live tile and the trend bars triangulate
  reality rather than agree exactly.

- **HOS_DailyLogs fetch window is 7 days, not configurable per-source.**
  Set in `samsara_main.py` (`_dlog_start = now - timedelta(days=7)`).
  If a longer monthly trend ever becomes the priority, widen that
  fetch and switch `_dvir_compliance_monthly` back to the HOS-based
  denominator — the function is structured so the two backends are
  swappable.
