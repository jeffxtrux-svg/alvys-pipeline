# XFreight cost-per-mile breakdown — "Jeff's Number" (seeded 2026-06-05 from OneDrive)

> Source: `03 - Finance/Financials/Goals and Trends/Goals and Trends.xlsx`
> ("Jeff's Number" tab, last modified 2026-06-04).

## The headline numbers

These are the office-overhead-per-mile components that feed into the rate-per-mile cost-out (see `xfreight-rate-per-mile-goal.md`).

### 2025 annual average

- **Total Office Expense per Mile: $0.7810** ($202,618 average monthly miles)
- 2026 YTD (Jan-Apr): **$0.8034 per mile** (rising)
- **2026 Goal Office Overhead: $0.98** ← this is `RPM_GOAL_OVERHEAD_PIN`

The pin at $0.98 includes a buffer over the live 2025 average ($0.78) to account for the 2026 liability-insurance rate hike that bumped costs (PR-era note: insurance was folded into the overhead instead of carried as a separate $0.07/mi surcharge).

## Itemized 2025 average (per mile)

| Line item | 2025 avg $/mi |
|---|---|
| Employee Wages and Benefits | $0.2844 |
| Telephone and Internet | $0.0215 |
| Utilities | $0.0104 |
| Office Rent | $0.0437 |
| Building Insurance | $0.0012 |
| Property Taxes | $0.0023 |
| Office Supplies | $0.0246 |
| Bank Charges | $0.0012 |
| **Liability Insurance** | **$0.0760** |
| **Cargo Insurance** | $0.0097 |
| Trailer Insurance | $0.0213 |
| Life Insurance | $0.0050 |
| Dues and Subscriptions | $0.0008 |
| Automobile Expense | $0.0021 |
| Customer Meals (50%) | $0.0010 |
| **Truck Fees and Tolls** | $0.0662 |
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
| **2025 TOTAL** | **$0.7810** |

## Biggest cost components

The three biggest office-overhead cost lines:

1. **Employee Wages & Benefits — $0.2844/mi** (36% of overhead)
2. **Lease Payments — $0.1207/mi** (15% of overhead)
3. **Liability Insurance — $0.0760/mi** (10% of overhead)

Insurance (liability + cargo + trailer combined) = **$0.107/mi (~14%)**.

## Truk-Way contribution

A separate `Truk-Way` line tracks per-mile from Truk-Way Leasing. Variable month-to-month (range -$1.31 to +$0.20 in 2025). Net **profit per mile contribution**: tiny in absolute terms but the Truk-Way per-truck P&L tab on the Sheets dashboard tracks it.

## Quarterly view (2025)

| Quarter | Avg Miles | Office $/mi |
|---|---|---|
| Q1 | 205,074 | $0.7711 |
| Q2 | 204,547 | $0.7936 |
| Q3 | 208,786 | $0.7903 |
| Q4 | 192,064 | $0.7691 |
| YTD | 202,618 | **$0.7810** |

Cost is fairly steady — $0.77-0.79 range with no large seasonal swing.

## 2026 YTD (through April)

| Month | Miles | Office $/mi |
|---|---|---|
| Jan-26 | 175,459 | $0.7435 |
| Feb-26 | 174,651 | $0.6615 |
| Mar-26 | 172,735 | $0.8141 |
| Apr-26 | 171,786 | $0.8671 |
| **YTD avg** | **173,034** | **$0.8034** |

Notable:
- Miles per month is **lower than 2025** (~173K vs ~203K, -15%). Fewer trucks active.
- Per-mile cost is **higher than 2025** (-15% miles → fixed costs spread over fewer miles).
- Apr 2026 jumped to $0.8671/mi — biggest single-month overhead this year.

## Goal vs actual gap

- **2025 actual:** $0.7810
- **2026 pin:** $0.98
- **Gap:** $0.20/mi target buffer

When the live overhead converges with the pin ($0.98), unpin and use live (set `RPM_GOAL_OVERHEAD_PIN = None`). Currently the live is ~$0.80 and the pin is $0.98 — significant gap. The buffer absorbs:
- Insurance rate hike (~$0.07-0.10/mi)
- Lower-mile months (~$0.05-0.08/mi)
- Truk-Way intercompany allocations

## Cross-reference

This is the data that underlies the **Liability Insurance** comment in commits about RPM_GOAL_INSURANCE_SURCHARGE:

- Before: `$0.92` overhead pin + `$0.07` insurance surcharge = $0.99/mi
- After (current): `$0.98` overhead pin + `$0.00` insurance surcharge = $0.98/mi
- Same effective total, simpler bookkeeping.
