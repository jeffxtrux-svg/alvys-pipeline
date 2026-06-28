---
title: Lewis Drug
type: concept
tags: [customers, active, regional-sd, pharmacy]
sources: ["raw/xfreight-customers-additional.md", "raw/xfreight-customer-portfolio.md", "raw/fuel-surcharge-matrix-ccfs.pdf"]
related: ["[[Customer Portfolio]]", "[[Financial Performance]]"]
---

# Lewis Drug

Lewis Drug is a regional pharmacy and retail chain headquartered in Sioux Falls, South Dakota. XFreight runs three recurring regional delivery routes for Lewis Drug stores. One of several South Dakota regional accounts.

## Summary

Active regional SD account with three confirmed routes: Madison, Brookings, and Huron. Rates run ~$399–$698/load depending on route. All three routes appeared in the June 2026 AR window, confirming the relationship is active. Estimated monthly revenue ~$11,500–13,000 based on 2–3 loads per route per week.

## Key Ideas

- **Three active routes** — LewMad (Madison, ~$399/load), LewBro (Brookings, ~$428/load), LewHur (Huron, ~$698/load). Huron commands the highest rate, consistent with longer distance from Sioux Falls.
- **High-cadence regional account** — approximately 2–3 runs per route per week; consistent replenishment pattern typical of pharmacy/retail.
- **Confirmed active June 2026** — all three route codes appeared in the Alvys AR aging report (June 3, 2026).
- **Steady, low-complexity revenue** — regional hauls, predictable cadence, no complex accessorial schedule noted.

## What We Know

| Field | Value |
|---|---|
| Status | Active, June 2026 |
| Industry | Regional pharmacy / retail (South Dakota) |
| Route: Madison | LewMad — ~$399/load |
| Route: Brookings | LewBro — ~$428/load |
| Route: Huron | LewHur — ~$698/load |
| Load frequency | ~2–3x/week per route |
| Est. monthly revenue | ~$13,500–14,000 |
| File on record | `08 - Sales/Customers/Lewis Drug/Lewis Drug.xlsx` |
| Entity | X-TRUX INC (confirmed from Alvys load data) |

## Fuel Surcharge

Lewis Drug uses the **CCFS FSC matrix** (same matrix as Johnson Brothers SD):

- **Index**: USTUCUR — EIA U.S. No. 2 Diesel Retail Price (weekly, national)
- **Effective date**: 10/23/2023
- **Formula**: Look up current USTUCUR diesel price → apply matrix % to base linehaul rate
- **Current range**: ~29–34% FSC at mid-2020s diesel prices ($3.50–$4.00/gal)

The route rates observed in Alvys AR ($399–$698/load) likely reflect all-in invoiced amounts including FSC already applied. Full matrix in `raw/fuel-surcharge-matrix-ccfs.pdf`.

## Open Questions / Watch

- What's in `Lewis Drug.xlsx` — rate agreement or rate sheet? Confirm whether quoted rates are base-only or all-in (base + FSC).
- Does volume have seasonality? (Pharmacy replenishment is generally stable, but holiday/Q4 could spike.)
- Is there a master shipper or broker agreement on file?

## Connections

- [[Customer Portfolio]] — Lewis Drug in context of the SD regional customer mix.
- [[Financial Performance]] — contributes ~$11,500–13,000/month; confirm from QB P&L.

## History

| Date | Event |
|---|---|
| 2026-06-03 | All three routes (LewMad, LewBro, LewHur) appear in Alvys AR aging report — relationship confirmed active |
| 2026-06-28 | Page updated with route/rate data from Alvys AR aging report |

## Sources

- `raw/xfreight-customers-additional.md` — Lewis Drug mention.
- `raw/xfreight-customer-portfolio.md` — portfolio context.
- `raw/fuel-surcharge-matrix-ccfs.pdf` — CCFS FSC matrix (USTUCUR index, effective 10/23/2023).
- Alvys AR aging report (June 3, 2026) — route codes and rate actuals.
