# Truk-Way Leasing, LLC — the third entity (seeded 2026-06-05 from OneDrive)

> Source: `03 - Finance/Financials/Profit and Loss/Truk-Way Pand L 2025.xlsx`,
> `Health Insurance 2025/TRUK-Way-Leasing-LLC-SD-12026-(health-vision) (4) copy.xlsx`,
> QB_TrialBalance.xlsx, payroll references in Acrisure WC audit invoices,
> `Goals and Trends.xlsx` Truk-Way per-mile P&L contribution.

## What Truk-Way actually does

Truk-Way Leasing, LLC is much more than its name suggests. It's **three things at once:**

### 1. Trailer + equipment leasing entity
- Leases trailers (and possibly tractors) to X-Trux for use in the asset fleet
- This is where some of the lease expense on X-Trux's P&L originates
- Per-mile P&L contribution: shows up as separate line in `Goals and Trends.xlsx` Truk-Way column

### 2. **Employer of record for W-2 office staff** ← the big surprise
- Truk-Way provides **employee health + vision insurance through Wellmark Blue Cross / Blue Shield SD**
- 2026 renewal options being evaluated (Oct 2025 worksheet):
  - CompleteBlue 5000 Silver
  - myBlue HDHP 6250 HSA Silver
  - CompleteBlue Primary 6250 Silver
  - SimplyBlue 6000
- This means **Audra Newman, dispatchers, and other W-2 employees are technically employees of Truk-Way, not X-Trux or X-Linx**
- Drivers (owner-operators) are 1099 contractors of X-Trux — different structure
- Workers' Comp audit (Inv 29033 in the Acrisure dispute) covers Truk-Way payroll

### 3. The driver-pay aggregator for owner-op groups
- Per Jeff's Alvys onboarding note (March 2024): *"I have 2 owner operator groups with multiple trucks, we pay the truck, however need a settlement for the driver also."*
- These owner-op GROUPS are likely paid through Truk-Way (which then pays each driver)
- Truk-Way's settlement worksheet (`baSettlmentWorksheek06032026.xlsx`) confirms: **"Truk-Way Leasing Drivers 2775 — This is for Driver Settlements Paid to Driver or Truck"**

So Truk-Way is the **payment hub** for both employees AND owner-op groups.

## Truk-Way financial size

From QB Trial Balance:
- **YTD 2026 total balance: $3,829,186** (as of June 5, 2026 — Jan-Dec 2026 accrual basis)
- May 21, 2026 snapshot: $3,739,358 — growing ~$90K/month
- Truk-Way has its own balance sheet, P&L, cash flow report
- A separate P&L workbook `Truk-Way Pand L 2025.xlsx` (last touched Jan 2026)

## Per-mile contribution to X-Trux cost-out

Truk-Way's net contribution shows up as a line in `Goals and Trends.xlsx` "Jeff's Number" tab. The 2025 numbers fluctuated wildly month-to-month:
- Range: -$1.31/mi to +$0.20/mi (per-mile basis)
- Net positive contribution: ~$0.07/mi annual average
- December 2025: -$2.65/mi (unusual outlier)

The volatility suggests Truk-Way's monthly net depends on:
- Trailer maintenance costs (variable)
- Insurance and license renewals (lumpy)
- Inter-company allocations (likely manual)

## Relationship to NJ entities (future)

QuickBooks has 5 company files:
1. X-Trux Inc (live)
2. X-Linx Inc (live)
3. Truk-Way Leasing LLC (live)
4. NJ Trailers (not yet live — refresh tokens absent)
5. NJ Properties LLC (not yet live — refresh tokens absent)

The NJ entities likely connect to the **SBA 504 building + business purchase** in progress (see `xfreight-sba-504-financing.md`). When that closes:
- NJ Properties LLC owns the real estate
- NJ Trailers may hold additional trailer inventory
- Both go live in QB after closing
- Pipeline `_companies()` function in `src/qb_main.py` will pick them up once the refresh tokens are set

## Why this matters for the brief

- **Page-1 entity tiles** currently show X-Trux + X-Linx ("XFreight" pair). Truk-Way is NOT in the headline entity tiles.
- Truk-Way's per-truck P&L tab IS in the Google Sheets KPI dashboard (per the `Sheets dashboard` doc) — added separately because it tracks asset performance differently.
- The rate-per-mile cost-out (`RPM_GOAL_OVERHEAD_COMPANIES`) defaults to X-Trux + X-Linx — Truk-Way's overhead isn't included unless explicitly added.

## Truk-Way as financial signal

If you want to understand XFreight's full economic picture:
- **Revenue side:** X-Trux + X-Linx (what the brief shows)
- **Cost side:** X-Trux + X-Linx (operating) + Truk-Way (asset leasing, payroll, benefits)
- **NJ entities:** Future real estate and additional trailers

The 5-entity structure exists because it separates:
1. Customer-facing brands (X-Trux as carrier, X-Linx as broker)
2. Asset ownership (Truk-Way owns trailers)
3. Employer of record (Truk-Way pays W-2s)
4. Future real estate (NJ Properties)

This is a **common small-mid trucking-company structure** — separates liability, optimizes for tax/insurance, and isolates risk.

## Open questions

- Does Truk-Way also lease tractors, or just trailers? (P&L would clarify)
- Are the owner-op group payments routed through Truk-Way, or directly X-Trux → owner-op?
- What's the lease arrangement between Truk-Way and X-Trux? (per-mile? flat monthly?)
- Why is the Truk-Way per-mile contribution so volatile in 2025?
- Post-SBA-504 closing, how will the consolidated structure look?

These are worth pulling from QuickBooks deeper or asking JB directly.
