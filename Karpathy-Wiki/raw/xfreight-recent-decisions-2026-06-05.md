# XFreight pipeline — decisions made 2026-06-05 (seeded same day)

> Source: PRs #86, #87, #88, #89, #90, #91, #92, #93 in `jeffxtrux-svg/alvys-pipeline`,
> plus the chat log of changes the user requested while iterating on the
> rendered scorecard PDF.

This file captures the WHY behind a batch of changes shipped on a single
day of iteration, so future readers don't lose the rationale.

## Driver acknowledgment column on safety events (PR #86)

**Problem:** Safety events on the page-1 detail table didn't show whether the driver had signed their Samsara coaching session. Management couldn't tell at a glance which events had been closed out.

**Decision:** Add an **Ack** column to the page-1 "Safety events — last 7 days" table AND the "Coaching needs assigned" table. Green ✓ when the driver signed a Samsara coaching session (Status = `completed` with `Completed At` timestamp at or after the event); em-dash otherwise.

**How:** `compute_samsara` builds `out["coaching_acks"]` = per-driver list of UTC ack timestamps from the CoachingSessions sheet. The render uses `_ack_after(driver, event_ts)` to look up acks.

## Coaching list visibility policy (PR #86 + #88)

**Decision:** Two-tier policy on the Coaching needs assigned list.

- **Monitor** (events < `COACH_EVENT_THRESHOLD = 2`) — single events. Drops off after 7 days from last event. Ack column reads "n/a" because single events don't need driver acknowledgment.
- **Assign coaching** (events ≥ 2) — stays on the list until the driver signs, then for `_ACK_KEEP_DAYS = 3` more days as a closeout indicator.

**Rationale:** A monitor item is "we noticed this; nothing to do unless it repeats." Forcing acknowledgment on those would muddy the signal. Coaching items are real interventions — they should stay visible until closed and provide a brief tail so the recent-resolution is visible at a glance.

## MVR violation window: 365d → 90d (PR #88)

**Decision:** `VIOLATION_WINDOW_DAYS = 90` (was 365).

**Rationale:** Surface recent risk, not the full year of historical record. Flows through to both the page-1 "New violations" tile (now reads "90D") and the page-2 "Recent violations & MVR alerts" section. Historical MVRs still live in SambaSafety.

## Driver weekly mileage target: 2000 → 2750 (PR #88)

**Decision:** `DRIVER_TARGET_MILES = 2750`.

**Rationale:** 2000 mi/wk had grown stale as the active rate. New target reflects the current expectation for owner-operators.

## Fleet miles MTD — silent bug fix (PR #88)

**Problem:** Page 8 "Fleet miles · MTD" tile was reading 530,379 mi for 5 days of June (~1,580 mi/truck/day on a ~15-truck fleet — physically impossible).

**Root cause:** Two compounding bugs.

1. **MTD filter no-op on the Trips path.** Samsara's v1 `/fleet/trips` returns `endMs` (Unix millis), but the column probe was only looking for `endtime` / `end time`. No match → `t_end = None` → the `if t_end:` block was skipped → we summed the full `SAMSARA_DAYS_BACK = 90` day window instead of MTD.
2. **Excluded-truck filter wasn't applied to the headline.** `_is_excluded_truck` (JW Logistics / brokerage / rentals) was filtering only the per-truck MPG list, NOT the `fleet_miles` / `fleet_mpg` / `fleet_gallons` totals on the tile.

**Fix:** Probe `endms` and `startms` too, parse millis with `unit="ms"`, log a loud WARNING if no date column matches (so the failure can't go silent again), and apply `_is_excluded_truck` to the agg DataFrame BEFORE the headline rollup. Same fix on the IFTA fallback path.

## MC #375851 surfaced on page 10 (PR #88)

**Decision:** Replace the page-10 "DOT Number" tile with a "Carrier Identity" tile showing DOT #841776 as the headline and MC #375851 as the sub-pill. Also added to the section header and source-line footer.

**Why now:** The MC # had never been recorded anywhere in code or docs. User shared it during iteration. Also added a "Carrier identity (ground truth)" table to `docs/knowledge-base/architecture.md` so future agents have an anchor.

## AR aging row — 91+ tile was clipped (PR #89)

**Problem:** Page-1 "Alvys AR — aging by due date" showed only 4 of 5 buckets — 91+ was missing from the rendered PDF.

**Root cause:** The outer brief container is a fixed 4-column table (section headers use `colspan='4'`, and the PDF post-processor hard-applies `table-layout:fixed`). Trying to fit 5 sibling `<td>` tiles into one `<tr>` of a 4-column layout overflows the page right edge and the 5th tile gets silently clipped.

**Fix:** Wrap the 5 aging tiles in a nested 5-column `<table>` inside a single `<td colspan='4'>`. Outer 4-col layout intact, inner 5-col table fills the row, all five tiles render.

## STOP / Sit-down speed escalations to Bottom Line (PRs #90 + #91)

**Decision:** Bottom Line now names drivers whose page-4 speed-over-limit comment says "STOP this driver now" or "Need to sit down with this driver" — EXCEPT drivers showing improvement ("falling fast" or "improving" trend phrases).

**Why exclude improvers:** Drivers actively fixing their speeding shouldn't be named in the morning escalation list. They still appear on page 4 with the alert, but not on page 1.

**Refactor (PR #91):** The first implementation duplicated the page-4 rubric thresholds. Refactored so both the page-4 detail and the BL exclusion use the **same** `compute_speed_comment` generator. The two physically cannot disagree.

**Format:**
```
STOP-THIS-DRIVER speed escalations (pg 4): NAME (3.8% peak, MTD 4.4%); ... +N more.
Sit-down conversations needed on speed (pg 4): NAME (2.6% peak, MTD 1.2%); ...
```

Capped at 5 names per tier with a "+N more" tail.

## All cron schedules pinned year-round to Central wall-clock (PR #92)

**Decision:** Every workflow uses a dual-cron + CT-hour-gate pattern so the wall-clock Central time stays constant across DST transitions with zero manual cron edits.

**Year-round Central schedule:**

| Time (CT) | Job |
|---|---|
| 2:30am | SambaSafety merge |
| 4:00am / 11:00am / 5:00pm | Alvys + Samsara + QB pulls |
| 4:30am / 1:00pm / 5:30pm | Sheets KPI dashboard |
| 5:00am (+ backups) | Scorecard email |
| 7:15am / 1:00pm | Karpathy-Wiki librarian |

See `xfreight-daily-schedule.md` for the full pattern + per-workflow gate sets.

**Also fixed in #92:** SambaSafety now runs ~2.5 hours before the scorecard primary (was firing at the same minute as the scorecard, leaving the scorecard reading yesterday's workbook on races).

## Added jb@xfreight.net to scorecard recipients (PR #93)

**Decision:** Scorecard email's `SCORECARD_TO_EMAILS` env var is now `jeff@xfreight.net,jb@xfreight.net`. JB receives both the daily brief AND the failure-notification email if the morning job breaks.
