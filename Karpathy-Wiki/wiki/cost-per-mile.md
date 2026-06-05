---
title: Cost Per Mile
type: concept
tags: [finance, kpi, overhead, cost-out]
sources: ["raw/xfreight-cost-per-mile-breakdown.md"]
related: ["[[Rate-Per-Mile Goal]]", "[[Financial Performance]]"]
---

# Cost Per Mile

Office overhead per mile — the "Jeff's Number" tab of `Goals and Trends.xlsx`. Feeds the overhead leg of the [[Rate-Per-Mile Goal]] cost-out. Currently pinned at **$0.98/mi** in the code while the live QB-derived figure ($0.80/mi) is being validated.

## Summary

Total office expense averages **$0.78/mi (2025)** and **$0.80/mi (2026 YTD)**. The three largest cost buckets are wages (36%), lease payments (15%), and insurance (~14%). The code pin of $0.98 buffers the live figure to absorb the 2026 insurance rate hike and lower-mileage months.

## Key Ideas

- 2025 average: $0.7810/mi on 202,618 monthly miles.
- 2026 YTD average: $0.8034/mi on ~173,034 monthly miles (15% fewer miles = higher $/mi on fixed costs).
- April 2026 was the highest single-month: $0.8671/mi.
- The $0.98 pin represents a conservative buffer above actuals; when actuals converge with it, unpin.

## 2025 Annual Average (per mile)

| Line Item | $/mi |
|---|---|
| **Employee Wages & Benefits** | **$0.2844** |
| Telephone and Internet | $0.0215 |
| Utilities | $0.0104 |
| Office Rent | $0.0437 |
| Building Insurance | $0.0012 |
| Property Taxes | $0.0023 |
| Office Supplies | $0.0246 |
| Bank Charges | $0.0012 |
| **Liability Insurance** | **$0.0760** |
| Cargo Insurance | $0.0097 |
| Trailer Insurance | $0.0213 |
| Life Insurance | $0.0050 |
| Dues and Subscriptions | $0.0008 |
| Automobile Expense | $0.0021 |
| Customer Meals (50%) | $0.0010 |
| **Truck Fees and Tolls** | **$0.0662** |
| Professional Fees | $0.0453 |
| **Lease Payments** | **$0.1207** |
| Signage and Inspections | $0.0057 |
| Drug Testing | $0.0014 |
| Licensing | $0.0011 |
| Trailer Maintenance | $0.0422 |
| Bad Debt Expense | $0.0033 |
| Depreciation Expense | $0.0343 |
| Interest Expense | $0.0331 |
| Management Fees | $0.0031 |
| **TOTAL 2025** | **$0.7810** |

## Top Three Drivers

1. **Employee Wages & Benefits: $0.2844/mi** — 36% of overhead.
2. **Lease Payments: $0.1207/mi** — 15%. Likely shifts to debt service post-[[SBA 504 Financing]].
3. **Insurance (liability + cargo + trailer): $0.107/mi combined** — ~14%.

## Quarterly View (2025)

| Quarter | Avg Miles/mo | Office $/mi |
|---|---|---|
| Q1 | 205,074 | $0.7711 |
| Q2 | 204,547 | $0.7936 |
| Q3 | 208,786 | $0.7903 |
| Q4 | 192,064 | $0.7691 |
| **YTD** | **202,618** | **$0.7810** |

Remarkably stable — $0.77–0.79 range, no large seasonal swing.

## 2026 YTD (Jan–Apr)

| Month | Miles | Office $/mi |
|---|---|---|
| Jan | 175,459 | $0.7435 |
| Feb | 174,651 | $0.6615 |
| Mar | 172,735 | $0.8141 |
| Apr | 171,786 | **$0.8671** |
| **YTD avg** | **173,034** | **$0.8034** |

The mileage drop from 2025 (~203K) to 2026 (~173K) is -15%. Fixed costs (wages, rent, insurance) spread over fewer miles → higher per-mile cost.

## Pin vs. Live Gap

| Version | $/mi |
|---|---|
| 2025 actual | $0.78 |
| 2026 YTD actual | $0.80 |
| `RPM_GOAL_OVERHEAD_PIN` (code) | **$0.98** |
| **Gap** | **~$0.18/mi buffer** |

The buffer absorbs: insurance rate hike (~$0.07–0.10), lower-mile months (~$0.05–0.08), Truk-Way allocations.

**When to unpin:** When the Data-check banner shows live ≈ pin for several consecutive days, set `RPM_GOAL_OVERHEAD_PIN = None`.

## Post-SBA 504 Change

If [[SBA 504 Financing]] closes, the **Lease Payments** line ($0.12/mi) will partially convert to **Interest Expense** + **Depreciation** on owned assets. The net per-mile cost may shift. The rate-per-mile cost-out will auto-adjust once the live QB calc is unpinned.

## Connections

- [[Rate-Per-Mile Goal]] — this is the overhead leg.
- [[Financial Performance]] — monthly mileage context.
- [[SBA 504 Financing]] — lease-to-own shift will change cost structure.

## Sources

- `raw/xfreight-cost-per-mile-breakdown.md`
