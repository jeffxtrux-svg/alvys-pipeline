---
title: Truk-Way Leasing
type: concept
tags: [entities, leasing, payroll, finance]
sources: ["raw/xfreight-truk-way-leasing.md"]
related: ["[[XFreight Entities]]", "[[Owner-Operator Program]]", "[[Cost Per Mile]]", "[[SBA 504 Financing]]", "[[QuickBooks Integration]]"]
---

# Truk-Way Leasing

Truk-Way Leasing, LLC is XFreight's third active QB entity. Despite the name, it serves three distinct roles: **trailer/equipment leasing**, **employer of record for W-2 office staff**, and **payment hub for owner-operator groups**.

## Summary

Truk-Way is much more than an equipment-leasing entity. It provides health/vision insurance to W-2 employees (Audra, dispatchers, etc.) through Wellmark Blue Cross, handles inter-company equipment leases to X-Trux, and acts as the payment intermediary for owner-op groups. QB Trial Balance YTD 2026: ~$3.8M and growing ~$90K/month. Truk-Way's per-mile P&L contribution is volatile (range -$1.31/mi to +$0.20/mi in 2025).

## Key Ideas

- Truk-Way is the **employer of record for W-2 employees**, not X-Trux or X-Linx. This separates driver (1099 contractor) and staff (W-2 employee) payrolls.
- Truk-Way is expected to be central to the [[SBA 504 Financing]] transaction — its assets (trailers, possibly equipment) may be what's being purchased.
- Per-mile contribution is highly volatile — probably due to lumpy maintenance costs, insurance renewals, and intercompany allocation timing.
- **NOT in the page-1 entity tiles.** Truk-Way has its own per-truck P&L tab on the Google Sheets KPI dashboard only.

## Three Roles

### 1. Trailer + Equipment Leasing

- Leases trailers (and possibly tractors) to X-Trux.
- The **Lease Payments** line on X-Trux's P&L ($0.1207/mi in 2025) flows from this arrangement.
- Post-[[SBA 504 Financing]], lease payments may shift to debt service (own vs. rent).
- Truk-Way has its own P&L in `03 - Finance/Financials/Profit and Loss/Truk-Way Pand L 2025.xlsx`.

### 2. Employer of Record (W-2 Staff)

- Provides **Wellmark Blue Cross / Blue Shield SD** health + vision insurance for office staff.
- 2026 plan options evaluated (Oct 2025): CompleteBlue 5000 Silver, myBlue HDHP 6250 HSA Silver, CompleteBlue Primary 6250 Silver, SimplyBlue 6000.
- Workers' comp (Truk-Way payroll) is covered by the Acrisure WC audit (Inv 29033 — part of the [[Acrisure Dispute]]).
- This means **Audra Newman, dispatchers, and other W-2 employees are technically Truk-Way employees**, not X-Trux or X-Linx employees.

### 3. Owner-Op Group Payment Hub

- Jeff told Alvys onboarding (March 2024): *"I have 2 owner operator groups with multiple trucks, we pay the truck, however need a settlement for the driver also."*
- Settlement worksheet header: "Truk-Way Leasing Drivers 2775 — This is for Driver Settlements Paid to Driver or Truck."
- Truk-Way pays the group/truck owner, who then pays individual drivers.

## Financial Size

| Metric | Value |
|---|---|
| QB Trial Balance YTD 2026 | ~$3,829,186 (as of Jun 5, 2026) |
| Monthly growth | ~$90K/month |
| Per-mile contribution (2025 range) | -$1.31/mi to +$0.20/mi |
| Dec 2025 outlier | -$2.65/mi (unusual) |

The large balance reflects asset holdings (trailers, leased equipment) plus intercompany activity.

## Why the Structure Exists

The five-entity structure separates:
1. Customer-facing brands (X-Trux = carrier, X-Linx = broker).
2. Asset ownership (Truk-Way owns trailers).
3. Employer of record (Truk-Way pays W-2s).
4. Future real estate (N&J Properties).

This is common in small-to-mid trucking: separates liability, optimizes for tax/insurance, and isolates risk across entities.

## How Truk-Way Appears in the Pipeline

- **Google Sheets KPI dashboard:** per-truck P&L tab for Truk-Way asset performance.
- **QB Trial Balance:** `QB_TrialBalance.xlsx` includes Truk-Way.
- **Overhead pool:** Truk-Way overhead is NOT included in `RPM_GOAL_OVERHEAD_COMPANIES` by default — only X-Trux + X-Linx are pooled.
- **`Goals and Trends.xlsx` "Jeff's Number" tab:** per-mile Truk-Way contribution column (the volatile -$1.31 to +$0.20 range).

## Post-SBA 504 Changes

If [[SBA 504 Financing]] closes:
- Truk-Way's leased assets may transfer to N&J Trailers.
- The X-Trux Lease Payments line shifts to Interest + Depreciation.
- N&J Properties LLC holds the real estate.
- The pipeline's `_companies()` in `src/qb_main.py` picks up the new entities automatically once refresh tokens are seeded.

## Open Questions

- Does Truk-Way lease tractors, or only trailers?
- What's the exact lease structure (per-mile? flat monthly?)?
- Why was the Dec 2025 per-mile contribution -$2.65 (so far below the normal range)?
- Post-SBA close, how will the entity structure look?

## Connections

- [[XFreight Entities]] — one of the five entities.
- [[Owner-Operator Program]] — Truk-Way is the payment hub for OO groups.
- [[Cost Per Mile]] — Truk-Way's lease payments are in the overhead breakdown.
- [[SBA 504 Financing]] — expected to restructure Truk-Way's role.
- [[Acrisure Dispute]] — Truk-Way's WC audit (Inv 29033) is part of the dispute.
- [[QuickBooks Integration]] — one of three live QB company files.

## Sources

- `raw/xfreight-truk-way-leasing.md`
