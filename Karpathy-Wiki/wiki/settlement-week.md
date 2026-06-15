---
title: Settlement Week
type: concept
tags: [operations, drivers, pay, schedule, alvys]
sources: ["raw/xfreight-settlement-week.md"]
related: ["[[Driver Roster]]", "[[Owner-Operator Program]]", "[[Rate-Per-Mile Goal]]", "[[Daily Scorecard Email]]"]
---

# Settlement Week

## Summary

A **settlement week** at XFreight runs from **Wednesday 3:00 PM Central** to the following **Wednesday 2:59 PM Central**. This cycle gates when drivers are paid and determines which week's per-mile rate applies to each load.

## Key Ideas

- Week boundary: **Wednesday 3:00 PM CT** (not calendar week, not Monday).
- The per-mile rate for any load is locked at **dispatch date** — not delivery, not settlement.
- A single settlement week typically contains loads at **two different per-mile rates** (loads dispatched Tuesday still on the old rate; dispatched Wednesday onward on the new rate).
- The brief shows the **current partial week + 4 prior complete weeks** — five settlement weeks total.

## The Cycle

Constants in `src/scorecard_email.py`:

| Constant | Value | Meaning |
|---|---|---|
| `SETTLEMENT_DOW` | 2 | Wednesday (Monday=0) |
| `SETTLEMENT_HOUR` | 15 | 3pm CT |
| `SETTLEMENT_WEEKS` | 5 | Current partial + 4 complete |
| `CHI_TZ` | `"America/Chicago"` | All timestamps converted here first |

Why Wednesday 3pm? Not documented. Likely chosen to place the week boundary mid-week/mid-day, when fewer loads are in transit, simplifying which week a load's pay belongs to.

## Dispatch Date Locks the Rate

**Owner-op loaded + empty per-mile rate is revised every Wednesday.** A load's rate is set the moment it is dispatched, based on the rate effective on that calendar day.

- Load **dispatched on Tuesday** → uses **that week's** mileage rate (even if it delivers Friday or the following Monday).
- Load **dispatched on Wednesday or later** → uses the **new** week's mileage rate.

The Wednesday 3pm settlement-week boundary doesn't itself change pay rates; the rate-change event is the Wednesday rate revision applied to new dispatches from that point forward.

## Where Settlement Week Appears on the Brief

- **Page 7 — Driver mileage by settlement week** (`build_page4`). Per-driver rows showing miles in each of the last 5 settlement weeks; current partial week is tinted. Below-target tile counts drivers with `0 < miles < 2750` in the **current** settlement week (drivers with 0 miles are separately flagged, not here).
- **Page 9 — Fleet idle** (`build_page_idle`). Same 5-week breakdown for idle hours / idle % / idle-gallons / MPG per truck.
- **Driver mileage target:** `DRIVER_TARGET_MILES = 2750` mi/wk (raised from 2,000 in PR #88 — see [[Recent Decisions 2026-06-05]]).

## Driver Pay Timing

Owner-operator pay lands when a load **settles**, not when it delivers. There is a lag of a few days between delivery and settlement. The rate-per-mile cost-out (see [[Rate-Per-Mile Goal]]) filters to settled-only loads because including unsettled loads would deflate the per-mile pay rate.

The `RPM_GOAL_PAY_WINDOW_DAYS = 10` trailing window in the cost-out captures roughly one-and-a-half rate weeks, smoothing the week-over-week rate change into a stable read while still tracking the current rate closely.

## Connections

- [[Owner-Operator Program]] — rate revision schedule; the $1.89/mi loaded+empty rate is the current baseline (a recent reference point, not a fixed rate).
- [[Rate-Per-Mile Goal]] — cost-out filter: settled-only loads; 10-day trailing window.
- [[Driver Roster]] — per-driver mileage targets and the 2,750 mi/wk goal.
- [[Daily Scorecard Email]] — pages 7 and 9 use the settlement-week cycle.

## Sources

- `raw/xfreight-settlement-week.md`
