---
title: Driver Roster
type: concept
tags: [drivers, operations, settlement, mileage]
sources: ["raw/xfreight-drivers-roster.md", "raw/xfreight-settlement-week.md"]
related: ["[[Owner-Operator Program]]", "[[Safety Program]]", "[[Daily Scorecard Email]]", "[[Financial Performance]]"]
---

# Driver Roster

The XFreight driver roster as of December 2024 (snapshot from `XFreight Goals.xlsx`) and the settlement week cycle that governs driver pay and reporting.

## Summary

As of the 2024-12-26 snapshot, 21 drivers were named in the goals spreadsheet with truck assignments. The live "Active Trucks · MTD" tile on page 1 of the brief shows ~15 — reflecting actual drivers running loads, with turnover since the snapshot. The settlement week runs **Wednesday 3:00 PM Central → Wednesday 2:59 PM Central**.

## Key Ideas

- **Roster snapshot (Dec 2024) ≠ current active drivers.** Use the brief's live tile for current count.
- Weekly driver mileage target: **2,750 mi/wk** in the brief (`DRIVER_TARGET_MILES`); Jeff's worksheet says 2,800. The brief's figure is authoritative.
- Settlement week boundary: **Wed 3pm CT**. Chosen when fewer loads are in transit to simplify which week a load's pay belongs to.
- The brief shows 5 settlement weeks (current partial + 4 complete prior).

## Settlement Week Cycle

| Attribute | Value |
|---|---|
| Start / end | Wednesday 3:00 PM Central |
| `SETTLEMENT_DOW` | 2 (Wednesday, Monday=0) |
| `SETTLEMENT_HOUR` | 15 (3pm) |
| `SETTLEMENT_WEEKS` | 5 (current partial + 4 prior) |
| Timezone | `CHI_TZ = "America/Chicago"` |

**Driver mileage target:** `DRIVER_TARGET_MILES = 2750` mi/wk. The "Drivers below target · this week" tile on page 7 counts drivers with `0 < miles < 2750`. Drivers with exactly 0 miles (didn't run) are not flagged on this tile — covered separately.

**Pay timing:** Driver Rate on Alvys loads lands when a load **settles**, not when it delivers. The rate-per-mile cost-out filters to settled-only loads to avoid deflating the per-mile read with unsettled loads showing $0 Driver Rate.

## Driver Roster (Dec 2024 Snapshot)

21 active drivers + 20 "Future" reserved slots (XFreight Goal.xlsx has slots 1–41):

| Driver | Truck # |
|---|---|
| Ben | 43193 |
| BradM | 43195 |
| Brian U | 41184 |
| Bryan M | 43200 |
| CharleneK | 38168 |
| DavidH | 44202 |
| Eugene | 42189 |
| Gary | 42186 |
| HelenH | 39172 |
| Joseph Hanson | 38165 |
| JoshT | 441029 |
| JSilveria | 44201 |
| KHarmon (no Kozy) | 41182 |
| Lonnie | 43199 |
| Michael Winovich | 43192 |
| MikeH | 42188 |
| MNewman | 43194 |
| Shane | 44204 |
| SteveS | 43198 |
| Toddb | 42187 |
| ToddS | 44205 |

> **Note on discrepancy:** This is a Dec 2024 snapshot. The brief's live tile shows ~15 active trucks as of mid-2026. Use the live tile, not this list, for current count.

> **Mileage target discrepancy:** The goals worksheet says 2,800 mi/wk; the brief uses 2,750 mi/wk (`DRIVER_TARGET_MILES`). The brief is the live authoritative target.

## Where Drivers Appear in the Brief

| Page | Content |
|---|---|
| Page 2 | MVR + license status + DOT medical card expiry by name |
| Page 3 | Safety events + HOS violations + DVIR defects + coaching needs (with Ack) |
| Page 4 | Speed-over-limit % per driver (6mo / 3mo / MTD) + comment + trend phrase |
| Page 7 | Mileage by settlement week (5 weeks, by driver name) |
| Page 8 | Fleet MPG (per truck) |
| Page 9 | Fleet idle (per truck, 5 settlement weeks) |

## Settlement Worksheet

Live worksheet (as of seed date): `DispatchFiles/Shared Documents/Alvys Settlements/baSettlmentWorksheek06032026.xlsx`

Columns: Driver Pay per Mile, Mileage, Truck Pay, Deductions, Total Fuel, Fuel Advances, Gallons, MPG, FCP Fuel Deduction, Settlement, IS Out of Balance, Pay Miles, Fuel Advance, Stops, Stop Pay.

One sheet: "Truk-Way Leasing Drivers 2775 — This is for Driver Settlements Paid to Driver or Truck."

## Equipment Roster (Live)

`DispatchFiles/Shared Documents/equipnow10.xlsx` — daily Mon–Fri grid showing truck/driver/tanker/CA chains + notes for each weekday of the current week.

## Driver Contract Files

Per-driver contracts: `06 - Safety & Compliance/Drivers/{Driver Name}/{Driver Name}.docx`. Contains the rate agreement + startup loan terms ($4,880 down + ~$3,000 licensing ≈ $7,880 total, repaid over ~32 weeks via reduced mileage rate).

## Connections

- [[Owner-Operator Program]] — pay rates and terms.
- [[Safety Program]] — BradM (truck 43195) written warning (Mar 2026 DOT inspection).
- [[Daily Scorecard Email]] — driver mileage page 7, safety pages 3–4.
- [[Rate-Per-Mile Goal]] — driver pay per mile is the variable leg.
- [[Truk-Way Leasing]] — OO groups paid through Truk-Way.

## Sources

- `raw/xfreight-drivers-roster.md`
- `raw/xfreight-settlement-week.md`
