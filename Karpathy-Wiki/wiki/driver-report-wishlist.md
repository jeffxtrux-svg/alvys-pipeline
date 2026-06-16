---
title: Driver Report Wishlist
type: concept
tags: [operations, drivers, wishlist, planning, brief]
sources: ["raw/xfreight-driver-report-wishlist.md"]
related: ["[[Brief Roadmap]]", "[[Dan Tracking Driver Connection]]", "[[Safety Program]]", "[[Driver Roster]]", "[[OTD Early Warning Wishlist]]", "[[Owner-Operator Program]]"]
---

# Driver Report Wishlist

A planned per-driver report — **not yet built as of 2026-06-15**. It is the second major brief-stack wishlist item from Jeff's June 15 conversation. Unlike every existing brief (which goes to management), this report goes **to the drivers themselves**.

## Summary

Jeff wants a personalized weekly snapshot sent to each driver showing where they stand on every dimension that matters to their day and their paycheck: location/status, mileage, safety score, coaching items, and license/medical expirations. Every piece of data already exists in the pipeline — this is a rearrangement, not a new pull. Dan Heeren is the natural sponsor given his driver-connectedness.

## What Jeff Wants

A per-driver report sent to each driver containing:

| Bucket | Content |
|---|---|
| **Where they're sitting** | Current location / status / next appointment / load they're on. |
| **Operating** | Miles last week, settlement-week pace, on-time delivery record, idle %, MPG vs. fleet. |
| **Safety** | Samsara safety score, coaching items open/closed, recent events, DVIR status, license/medical/MVR expirations on the horizon. |
| **Overall report card** | Pulls it all together — the driver sees their own snapshot the way the office sees them. |

## Why High-Leverage

- **First non-management audience** in the brief stack — opens a new product surface.
- **Retention lever.** Drivers leave when they feel invisible or miscounted. A trusted weekly snapshot is a retention asset.
- **Safety + coaching closeout.** Drivers who can see their own safety trajectory respond faster to coaching items than those who hear about it second-hand.
- **Dan-aligned.** Dan is the most driver-connected leader; he will be the sponsor and QA reviewer (see [[Dan Tracking Driver Connection]]).

## Data Sources (Already in Pipeline)

| Bucket | Source | Pipeline Location |
|---|---|---|
| Location / next stop | Samsara live + Alvys trips | `samsara_client`, Trips sheet |
| Miles + settlement week | Alvys driver mileage by settlement week | `build_page4` |
| MPG + idle + speed | Alvys + Samsara | `build_page_fleet`, `build_page_idle` |
| Safety score | Samsara per-driver safety score | `samsara_client.fetch_driver_safety_scores`, `build_page2b` |
| Coaching items + DVIR | Samsara safety events | `build_page2` |
| License / medical / MVR | SambaSafety + Alvys Drivers sheet | `build_page9` |

## Open Scoping Questions

1. **Cadence.** Daily, weekly, or both? Weekly aligned to settlement week is the natural default since pay is weekly.
2. **Delivery channel.** Email / text / in-cab tablet / Samsara driver app push?
3. **Format.** PDF (complex) vs. simple HTML email / mobile card (more likely for drivers).
4. **Personalization scope.** Driver-only data, or fleet-relative context (e.g., "your MPG is 6.8 — fleet avg is 6.4, top quartile")?
5. **Action surface.** Read-only vs. actionable (driver acknowledges coaching items)?
6. **Opt-out / privacy.** Mandatory or opt-in? What escalates to dispatch if a driver does not open/respond?
7. **Pay alignment.** Include settlement-week pay summary, or keep to operational + safety only?
8. **Audience.** All drivers equally, or different reports for X-Trux owner-operators vs. Truk-Way W-2 drivers?

## Build Sequence

Per [[Brief Roadmap]] this is Phase 3+:
- **Phase 1:** OTD early-warning page on executive brief (see [[OTD Early Warning Wishlist]]).
- **Phase 2:** Operations brief built (Jackson + Dan primary).
- **Phase 3:** Per-driver report, building on top of Phase 1 + 2 data.

## Product Ownership

- **Sponsor:** Dan Heeren (driver-connected; owns the relationship question).
- **Safety-data QA:** Audra Newman (owns safety inputs — will catch drift between this and the Safety brief).

## Connections

- [[Brief Roadmap]] — build sequence; this is Phase 3+.
- [[Dan Tracking Driver Connection]] — Dan sponsors; his skepticism means the data must be defensible.
- [[Safety Program]] — safety inputs; Audra QA.
- [[Driver Roster]] — current driver list.
- [[OTD Early Warning Wishlist]] — must land before this report.
- [[Owner-Operator Program]] — different driver types may get different report shapes.

## Sources

- `raw/xfreight-driver-report-wishlist.md` — captured 2026-06-15 from Jeff.
