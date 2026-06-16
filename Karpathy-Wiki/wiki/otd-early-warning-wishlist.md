---
title: OTD Early Warning Wishlist
type: concept
tags: [operations, otd, wishlist, planning, brief]
sources: ["raw/xfreight-otd-early-warning-wishlist.md"]
related: ["[[Brief Roadmap]]", "[[Daily Scorecard Email]]", "[[Jeff JB Tracking Philosophy]]", "[[Employee Responsibilities]]", "[[Data Pipeline Architecture]]"]
---

# OTD Early Warning Wishlist

A planned new brief page — **not yet built as of 2026-06-15**. It is Jeff's highest-priority gap in the current brief stack: a morning view that shows, before the day starts, how many trucks are projected to be late to today's deliveries. It is the first forward-looking page in a brief stack that is currently lagging-KPI only.

## Summary

Jeff wants a page that answers "how many trucks are going to be late today, and which ones?" — surfaced at 5am so the team can act before a service failure becomes a customer call after the fact. The data sources already exist in the pipeline; this is a rearrangement of data already computed for other pages. Scoped to ship on **exactly two briefs**: Executive (first) and Operations (when built).

## What Jeff Wants

Two acceptable shapes:
- **Headline tile:** count of trucks projected late today on page 1 of the Operational brief (e.g., "3 of 17 trucks delivering today projected late").
- **One-pager:** every driver delivering today — one row per driver — with current ETA vs. scheduled delivery appointment and an on-time / at-risk / late flag.

Goal: **planning room**. A late delivery caught at 5am is recoverable; caught at noon, it is an explanation after the fact.

## Why High-Leverage

- The brief today reports on yesterday (lagging). This is the first *forward-looking* page.
- Owns naturally to Jackson + Dan per [[Employee Responsibilities]] (on-time delivery; truck coverage / dispatch).
- Nobody currently has this view in one place — it is pieced together ad-hoc from Alvys + Samsara.

## Data Sources (Already in Pipeline)

| Source | Data |
|---|---|
| **Alvys** | `Trips` / `Loads` / `Stops` — scheduled delivery appointment time, stop sequence, consignee, customer, load #. Filter to stops with appointment on today (America/Chicago) that are still open. |
| **Samsara** | `Vehicles` / `VehicleStats` — current lat/lng, speed, last-known-time per tractor. Combine with destination address to compute remaining drive time. |
| **Driver ↔ Truck join** | Alvys trip carries driver + truck; Samsara keyed by truck/asset name. Same join used on MPG and Speed pages. |

## Scoping Decisions (Jeff, 2026-06-15)

**"Late" definition:** Past the **delivery appointment time stored in Alvys**. Not an appointment window, not a buffered version — the appointment time itself is the line.

**ETA source — preference order:**
1. **Preferred:** Alvys UI "miles to delivery" and "estimated time to delivery" fields via API (if they exist). The Alvys UI already shows these for every load. Investigate first: run the pipeline, open `output/_debug/sample_loads.json` and `sample_trips.json`, grep for `eta`, `nextStop`, `distance`, `mileage`, `location`, `lastLocationAt`. The legacy schema in `src/column_mappings.py` (~lines 847–851) has placeholder columns for `Location`, `Next Stop`, `ETA`, `Next Appointment`, and `Location Update` all mapped to `None` with comment `# UI real-time` — the original author looked for these and did not find them. Worth re-investigating against the current API.
2. **Fallback (approved 2026-06-15):** build own algorithm from Samsara current location → Alvys delivery address vs. appointment time.

**Brief scope:** Executive brief (Phase 1) and Operations brief (Phase 2, when built). **Explicitly NOT on:** Safety brief, Financial brief, MTD upload, or driver report.

## Still Open

- Today-only vs. today + next 24h rolling window.
- Three status buckets (on-time / at-risk / late) vs. five (early / on-time / tight / at-risk / late).

## What "Done" Looks Like

A page titled "Today's deliveries — on-time risk" with:
- Header tile: `X of Y trucks projected late today` (red if ≥ 1).
- Table: Driver · Truck · Customer · Stop city · Appt time (CT) · Current location · Remaining drive · ETA · Slack vs appt · Status pill.
- Sorted by status (Late → At-risk → On-time), then by Appt time.
- Action items under Jackson + Dan's `owner:` field in the Risk Watch strip.

## Dependencies / Build Sequence

This is Phase 1 in the forward-looking brief roadmap per [[Brief Roadmap]]. Build this before the Operations brief and before the [[Driver Report Wishlist]] (which consumes some of the same data).

## Connections

- [[Brief Roadmap]] — OTD page is Phase 1 of the forward-looking additions.
- [[Jeff JB Tracking Philosophy]] — OTD is the one forecast page Jeff explicitly wants on the executive brief.
- [[Employee Responsibilities]] — Jackson + Dan own on-time delivery.
- [[Data Pipeline Architecture]] — Alvys and Samsara are the two sources.

## Sources

- `raw/xfreight-otd-early-warning-wishlist.md` — captured 2026-06-15 from Jeff on the drive home.
