---
title: Recent Decisions 2026-06-05
type: concept
tags: [decisions, pipeline, prs, changelog]
sources: ["raw/xfreight-recent-decisions-2026-06-05.md", "raw/xfreight-coaching-ack-from-safety-events-2026-06-06.md", "raw/xfreight-owner-operator-program.md", "raw/xfreight-settlement-week.md"]
related: ["[[Daily Scorecard Email]]", "[[Safety Program]]", "[[Daily Schedule]]", "[[Key People]]", "[[Owner-Operator Program]]", "[[Driver Roster]]", "[[Coaching Ack]]"]
---

# Recent Decisions — 2026-06-05 / 2026-06-06

A log of the pipeline changes shipped on June 5–6, 2026 (PRs #86–#97) and the rationale behind each. Preserved here so future readers don't lose the why.

## Summary

Nine PRs spanning two days: driver acknowledgment tracking, coaching list visibility policy, MVR window narrowing, mileage target update, fleet-miles MTD bug fix, MC # surfaced on page 10, AR aging layout fix, speed escalation in Bottom Line, cron DST hardening, JB added to scorecard recipients, and documentation of the dispatch-date-locks-rate rule.

## PR Log

### PR #86 — Driver Acknowledgment Column on Safety Events

**Problem:** Safety events on page 1 didn't show whether the driver had signed their Samsara coaching session.

**Decision:** Add an **Ack** column to:
- Page-1 "Safety events — last 7 days" table.
- "Coaching needs assigned" table.

**How:** `compute_samsara` builds `out["coaching_acks"]` = per-driver list of UTC ack timestamps from CoachingSessions sheet. `_ack_after(driver, event_ts)` returns ✓ when the driver's coaching session `Status = completed` + `Completed At ≥ event_ts`.

### PR #86 + #88 — Coaching List Visibility Policy

**Decision:** Two-tier policy:
- **Monitor** (< 2 events) — drops off 7 days after last event. Ack = "n/a."
- **Assign coaching** (≥ 2 events) — stays until driver signs, then 3 more days (`_ACK_KEEP_DAYS = 3`).

**Rationale:** Single events don't warrant acknowledgment; forcing it muddies the signal. Coaching items are real interventions — keep visible until closed.

### PR #88 — MVR Violation Window: 365d → 90d

**Decision:** `VIOLATION_WINDOW_DAYS = 90` (was 365).

**Rationale:** Surface recent risk, not full-year history. Page-1 "New violations" tile now reads "90D."

### PR #88 — Driver Weekly Mileage Target: 2000 → 2750

**Decision:** `DRIVER_TARGET_MILES = 2750`.

**Rationale:** 2000 mi/wk had grown stale as the actual operating expectation.

### PR #88 — Fleet Miles MTD Silent Bug Fix

**Problem:** Page 8 "Fleet miles · MTD" tile showed 530,379 mi for 5 days of June — physically impossible (~1,580 mi/truck/day on ~15 trucks).

**Root cause:** Two compounding bugs:
1. MTD filter was a no-op on the Trips path — Samsara returns `endMs` (Unix millis) but the column probe only looked for `endtime`/`end time`. No match → `t_end = None` → 90-day window used instead of MTD.
2. `_is_excluded_truck` filter applied only to the per-truck MPG list, NOT to the `fleet_miles` headline total.

**Fix:**
- Probe `endms` and `startms` (case variants); parse millis with `unit="ms"`.
- Log a loud WARNING if no date column matches (can't go silent again).
- Apply `_is_excluded_truck` to the aggregation DataFrame BEFORE the headline rollup.
- Same fix on the IFTA fallback path.

### PR #88 — MC #375851 Surfaced on Page 10

**Decision:** Replace the page-10 "DOT Number" tile with a "Carrier Identity" tile: DOT #841776 as headline + MC #375851 as sub-pill. Added to section header and source-line footer too.

**Why:** The MC # had never been recorded in code or docs. Also added a "Carrier identity (ground truth)" table to `docs/knowledge-base/architecture.md`.

### PR #89 — AR Aging Row: 91+ Tile Was Clipped

**Problem:** Page-1 AR aging showed only 4 of 5 buckets — 91+ was missing from the rendered PDF.

**Root cause:** The outer brief container is a fixed 4-column table. 5 sibling `<td>` tiles in one `<tr>` overflow the page right edge; the 5th tile gets silently clipped.

**Fix:** Wrap the 5 aging tiles in a **nested 5-column `<table>`** inside a single `<td colspan='4'>`. Outer 4-col layout intact; inner 5-col table fills the row.

### PRs #90 + #91 — Speed Escalations to Bottom Line

**Decision:** Bottom Line now names drivers whose page-4 comment is "STOP this driver now" or "Need to sit down" — **except** drivers showing "falling fast" or "improving" trend phrases.

**Why exclude improvers:** Drivers fixing their speeding shouldn't be named in morning escalation. They still appear on page 4.

**PR #91 refactor:** First implementation duplicated the rubric thresholds. Refactored: both page-4 detail and Bottom Line use the **same** `compute_speed_comment` generator — they physically cannot disagree.

**Format:**
```
STOP-THIS-DRIVER speed escalations (pg 4): NAME (3.8% peak, MTD 4.4%); ... +N more.
Sit-down conversations needed on speed (pg 4): NAME (2.6% peak, MTD 1.2%); ...
```
Capped at 5 names per tier + "+N more."

### PR #92 — All Cron Schedules Pinned to Central Wall-Clock (DST Pattern)

**Decision:** Every workflow uses dual-cron + CT-hour-gate. All times are fixed Central year-round. Zero manual cron edits at DST flip.

**Also fixed in #92:** SambaSafety moved to 2:30am (was firing at the same minute as the scorecard primary, leaving the scorecard reading yesterday's SambaSafety workbook on races).

### PR #93 — JB Added to Scorecard Recipients

**Decision:** `SCORECARD_TO_EMAILS = jeff@xfreight.net,jb@xfreight.net`. JB receives both the daily brief AND the failure-notification email.

### PR #97 — Dispatch Date Locks the Per-Mile Rate (Docs)

**Change:** Documented the dispatch-date-locks-rate rule in `xfreight-owner-operator-program.md` and `xfreight-settlement-week.md`.

**Rule:** A load's per-mile rate is set by its **dispatch date**, not delivery date or settlement date.
- Load dispatched on a **Tuesday** → uses that week's rate for the entire load.
- Load dispatched on **Wednesday or later** → uses the **new** week's rate.

A single settlement week (Wed 3pm CT → Wed 2:59pm CT) therefore contains loads at two different per-mile rates. The settlement worksheet accounts for both bands.

**Why it matters:** Drivers know exactly what they earn at the moment of dispatch — no ambiguity. The pipeline's 10-day trailing window in `RPM_GOAL_PAY_WINDOW_DAYS` is set specifically to blend across the weekly rate boundary and produce a stable read.

See [[Owner-Operator Program]] § "The Dispatch Date Locks the Rate" for full detail.

## 2026-06-06 — Coaching Ack Fix (Post-PR #86 Correction)

**Problem:** The Ack column on the "Coaching needs assigned" table was always em-dash for every "Assign coaching" driver — including Michael Hall, who had completed his session eight days earlier.

**Root cause:** Samsara's `/coaching/sessions` REST endpoint returns HTTP 404 on every run. `_safe_get` swallowed the error, CoachingSessions was always a 1-row placeholder, and `out["coaching_acks"]` was always empty.

**Fix:** `compute_samsara` now derives ack state directly from each safety event's `coachingStatus` field on the SafetyEvents sheet. `all_coached = True` when every event for the driver in the 30-day window has status in `{coached, dismissed, recognized}`. A new **Coach** column (from `coachedBy.name`) was added between Action and Ack. The dead `coaching_acks` builder and `_ack_after` helper were removed.

This fix **supersedes the PR #86 approach** documented in the section above.

→ Full root-cause analysis: [[Coaching Ack]].

## Connections

- [[Daily Scorecard Email]] — most changes target this artifact.
- [[Safety Program]] — driver Ack, coaching policy, speed escalation, MVR window.
- [[Coaching Ack]] — June 6 fix to ack derivation (supersedes PR #86).
- [[Daily Schedule]] — DST cron pattern hardened.
- [[Key People]] — JB Sweere added to recipients.
- [[FMCSA CSA Scorecard]] — MC # surfaced on page 10.
- [[Owner-Operator Program]] — dispatch-date rate rule documented.
- [[Driver Roster]] — settlement week cycle; dispatch rate context.

## Sources

- `raw/xfreight-recent-decisions-2026-06-05.md` — PRs #86–#93.
- `raw/xfreight-coaching-ack-from-safety-events-2026-06-06.md` — June 6 coaching-ack fix.
- `raw/xfreight-owner-operator-program.md` — dispatch-date-locks-rate rule.
- `raw/xfreight-settlement-week.md` — settlement week cycle + dispatch date context.
