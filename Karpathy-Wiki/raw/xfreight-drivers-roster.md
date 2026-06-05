# XFreight driver roster + mileage goals (seeded 2026-06-05 from OneDrive)

> Source: `XFreight - Claude Working Files/03 - Finance/Financials/Goals and Trends/XFreight Goals.xlsx`
> (last modified 2024-12-26 — may be out of date for current roster).

## Mileage goals per driver (legacy spreadsheet)

- **Weekly goal:** 2,800 miles/driver
- **Monthly goal:** 11,200 miles/driver
- Total slots: 21 active + 20 reserved future slots = 41 trucks max in the goal sheet

> **Note on discrepancy:** the scorecard email's `DRIVER_TARGET_MILES` constant is **2,750 mi/wk** (after PR #88 raised it from 2,000). The hand-maintained Goals worksheet has it at **2,800 mi/wk**. These should be reconciled — likely the brief's 2,750 is the current authoritative target and the worksheet hasn't been updated.

## Active roster (as of 2024-12-26 snapshot)

21 drivers with truck assignments:

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

> **Note on fleet size discrepancy:** the roster lists 21 drivers but the page-1 "Active Trucks · MTD" tile reports ~15. The roster is a 2024-12-26 snapshot and likely includes drivers who have since left; the brief tile is live from the Alvys feed. Use the live tile for current count, not this roster.

## Cross-references with other artifacts

- **Daily safety detail (page 3, 4):** drivers from the roster appear by name in the Samsara Safety Events and Speed-Over-Limit tables.
- **Per-driver speed comments (page 4):** the page-4 rubric generates "STOP this driver" / "Need to sit down" / etc. callouts (see `xfreight-safety-program.md`).
- **Per-driver weekly mileage (page 7):** the brief's "Driver mileage by settlement week" table is sourced from Alvys, not this roster — but the names should match.

## Settlement worksheets

- Live worksheet (latest as of seed): `DispatchFiles/Shared Documents/Alvys Settlements/baSettlmentWorksheek06032026.xlsx`
- Columns include: Driver Pay per Mile, Mileage, Truck Pay, Deductions, Total Fuel, Fuel Advances, Gallons, MPG, FCP Fuel Deduction, Settlement, IS Out of Balance, Pay Miles, Fuel Advance, Stops, Stop Pay.

## Equipment roster (live)

- `DispatchFiles/Shared Documents/equipnow10.xlsx` — daily Mon-Fri equipment grid showing which truck/driver/tanker/CA chains plus notes for each weekday of the current week.

## Recruiting paperwork pattern

Individual driver contracts are stored under `06 - Safety & Compliance/Drivers/{Driver Name}/`. Example: `06 - Safety & Compliance/Drivers/Lacey Campbell/Lacey Campbell.docx` — a Rate Agreement template that includes a startup loan ($4,880 down payment + ~$3,000 licensing = ~$7,880 total) repaid through reduced mileage rates over ~32 weeks. Signed by Jeff Hannahs (X-Trux) on one side and the driver on the other.
